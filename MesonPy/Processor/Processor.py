import logging
import asyncio
import functools

logger = logging.getLogger(__name__)

class InstructionContext:
    def __init__(self, operationType, payload, future = None):
        self.future = future
        self.operationType = operationType
        self.payload = payload
        self.ret = None
        self.error = None

    def done(self):
        if self.future is not None:
            self.future.set_result(self)
    def __str__(self):
        return 'operation={}, payload={}'.format(self.operationType, self.payload)

class iInstruction:
    def canHandleInstruction(self, context):
        raise NotImplementedError()
    def executeLogic(self, instructionCtx, procCtx):
        raise NotImplementedError()

class RPCInstruction:
    """
        Remote Procedure Call
    """
    def __init__(self, methodName, method):
        self.methodName = methodName
        self.method = method

    def executeLogic(self, instructionCtx, procCtx):
        executableMethod = procCtx.injectArgs(self.method, instructionCtx.payload)
        return executableMethod()

    def canHandleInstruction(self, instructionCtx):
        return 'method' in instructionCtx.payload and instructionCtx.payload['method'] == self.methodName

    def __str__(self):
        return 'RPC Instruction, method={}'.format(self.methodName)


class RPCExecutionContext:
    def __init__(self, instructionCtx):
        payload = instructionCtx.payload
        if 'kargs' in payload and payload['kargs']:
            self.args = payload['kargs']
        elif 'args' in payload and payload['args']:
            self.args = payload['args']
        else:
            self.args = []

    def injectArgs(self, method, payload):
        if type(self.args) is dict:
            return functools.partial(method, **self.args)
        elif type(self.args) is list:
            return functools.partial(method, *self.args)
        else:
            return method

class RPCProcessor:
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
        instructionCtx = yield from self.executionQueue.get()
        logger.info('Will handle instruction request %s', instructionCtx)
        instruction = self.findSuitableInstruction(instructionCtx)
        logger.info('Found executable logic for instruction request %s, logic=%s', instructionCtx, instruction)
        try:
            logger.info('Execute RPC %s', instructionCtx)
            instructionCtx.ret = instruction.executeLogic(instructionCtx, RPCExecutionContext(instructionCtx))
            logger.info('RPC %s had been executed', instructionCtx)
        except Exception as e:
            logger.info('RPC %s had failed, error=%s', instructionCtx, e)
            instructionCtx.error = e
            raise e
        finally:
            instructionCtx.done() # Context can be closed

    def canHandleOperation(self, instructionCtx):
        return instructionCtx.operationType == 'RPC' and 'method' in instructionCtx.payload
