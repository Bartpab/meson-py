import logging
import asyncio
import functools
import inspect

logger = logging.getLogger(__name__)

from MesonPy.Processor.Processor import iProcessor

class RPCInstruction:
    """
        Remote Procedure Call
    """
    def __init__(self, methodName, method):
        self.methodName = methodName
        self.method = method

    @asyncio.coroutine
    def executeLogic(self, procCtx):
        executableMethod = procCtx.injectArgs(self.method)

        ret = executableMethod()

        if inspect.isgenerator(ret):
            ret = yield from asyncio.ensure_future(executableMethod())

        return ret

    def canHandleInstruction(self, instructionCtx):
        return 'method' in instructionCtx.payload and instructionCtx.payload['method'] == self.methodName

    def __str__(self):
        return '{}'.format(self.methodName)

import inspect
class RPCExecutionContext:
    def __init__(self, instructionCtx):
        self.session = instructionCtx.session
        payload = instructionCtx.payload

        if 'kargs' in payload and payload['kargs']:
            self.args = payload['kargs']
        elif 'args' in payload and payload['args']:
            self.args = payload['args']
        else:
            self.args = []

    def injectArgs(self, method):
        if type(self.args) is dict:
            method = functools.partial(method, **self.args)
        elif type(self.args) is list:
            method = functools.partial(method, *self.args)

        argspecs = inspect.getfullargspec(method)
        # Inject execution context
        if '__session__' in argspecs.args or '__session__' in argspecs.kwonlyargs:
            method = functools.partial(method, __session__=self.session)

        return method

class RPCService:
    def __init__(self, rpcProcessor):
        self.rpcProcessor = rpcProcessor
    def register(self, name, method):
        self.rpcProcessor.register(name, method)
class UnknownRemoteProcedure(Exception):
    def __init__(self, procedureName):
        Exception.__init__(self, 'Unknown Remote Procedure "{}" is called'.format(procedureName))
class RPCProcessor(iProcessor):
    def __init__(self):
        self.instructions = {}
        self.executionQueue = asyncio.Queue()

    def register(self, name, method):
        self.instructions[name] = RPCInstruction(name, method)

    def findSuitableInstruction(self, instructionCtx):
        suitableInstructions = []
        for name, instruction in self.instructions.items():
            if instruction.canHandleInstruction(instructionCtx):
                suitableInstructions.append(instruction)

        if len(suitableInstructions) == 0:
            logger.warning('No suitable instruction found for context=%s', instructionCtx)
            return None
        elif len(suitableInstructions) > 1:
            logger.error('Multiple instructions found for context=%s', instructionCtx)
        else:
            return suitableInstructions[0]

    def push(self, instructionCtx):
        asyncio.ensure_future(self.executionQueue.put(instructionCtx))

    @asyncio.coroutine
    def step(self, stackContext):
        logger.info('Step on %s', self)

        try:
            instructionCtx = yield from self.executionQueue.get()
        except RuntimeError:
            return

        try:
            logger.info('Will handle instruction request %s', instructionCtx)
            instruction = self.findSuitableInstruction(instructionCtx)

            if instruction is None:
                raise UnknownRemoteProcedure(instructionCtx.payload['method'])

            logger.info('Found executable logic for instruction request %s, logic=%s', instructionCtx, instruction)
            logger.info('Execute RPC %s', instructionCtx)
            instructionCtx.ret = yield from asyncio.ensure_future(instruction.executeLogic(RPCExecutionContext(instructionCtx)))
            logger.info('RPC %s had been executed', instructionCtx)

        except Exception as e:
            logger.info('RPC %s had failed, error=%s', instructionCtx, e)
            instructionCtx.error = e
            raise e

        finally:
            instructionCtx.done() # Context can be closed

    def canHandleOperation(self, instructionCtx):
        return instructionCtx.operationType == 'RPC' and 'method' in instructionCtx.payload
