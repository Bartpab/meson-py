import logging
import asyncio
import functools
from uuid import uuid4


from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler
from MesonPy.Processor.Processor import InstructionContext
from MesonPy.Processor.Processor import RPCProcessor

logger = logging.getLogger(__name__)

class ObjectManager:
    def __init__(self):
        self.objects = {}
        self.type = {}
        self.objectsByType = {}

    def registerInstance(self, obj, objCls):
        oid = id(obj)
        self.objects[oid] = obj
        self.type[oid] = objCls

        if objCls not in self.objectsByType:
            self.objectsByType[objCls] = []

        self.objectsByType[objCls].append(oid)

    def newInstance(self, objectClass):
        obj = objectClass()
        self.registerInstance(obj, objectClass)

class StackContext:
    def __init__(self):
        self.services = {}
    def register(self, name, service):
        self.services[name] = service
    def get(self, name):
        return self.services[name]

class Kernel:
    def __init__(self):
        self._close = False
        self.processors = []
        self.rpc = RPCProcessor()
        self.processors.append(self.rpc)

    def addProcessor(self, processor):
        self.processors.append(processor)
        return self

    def getStackContext(self):
        return

    def close(self):
        if not self._close:
            self._close = True
            logger.info('Exiting kernel')

    @asyncio.coroutine
    def run(self):
        tasks = {}
        while not self._close:
            stackContext = self.getStackContext()
            for proc in self.processors:
                if proc not in tasks:
                    tasks[proc] = asyncio.ensure_future(proc.step(stackContext))
            # Wait until one of the processors had finished its task
            done, pending = yield from asyncio.wait([task for task in tasks.values()], return_when= asyncio.FIRST_COMPLETED)
            #
            logger.debug('Instructions done %s', done)
            # Free the processor which task is done
            free = []
            for done_task in done:
                for proc, task in tasks.items():
                    if task == done_task:
                        free.append(proc)
            for free_proc in free:
                tasks.pop(free_proc)

    def findSuitableProcessor(self, instructionCtx):
        suitableProcessors = []
        for processor in self.processors:
            if processor.canHandleOperation(instructionCtx):
                suitableProcessors.append(processor)
        if len(suitableProcessors) == 0:
            logger.warning('No suitable processor found for instruction context %s', instructionCtx)
            return None
        elif len(suitableProcessors) > 1:
            raise Exception('Many processors could handle this instruction')
        else:
            return suitableProcessors[0]

    def stackForExecution(self, instructionCtx):
        logger.info('Stacking for execution, context=%s', instructionCtx)
        processor = self.findSuitableProcessor(instructionCtx)

        if processor is not None:
            logger.debug('instruction=%s, proc=%s', instructionCtx, processor)
            processor.push(instructionCtx)
        else:
            logger.warning('No processor found to execute this instruction, execution cancelled, context=%s', instructionCtx)


class BackendFrontalController(BaseReceivedMessageHandler):
    def __init__(self, kernel, requestHandler, responseHandler):
        BaseReceivedMessageHandler.__init__(self, requestHandler)
        self.responseHandler = responseHandler
        self.kernel = kernel
        self.kernelTask = asyncio.ensure_future(self.kernel.run())
        asyncio.ensure_future(self.kernelTask)

    def request_done(self, uid, future):
        """
            The kernel had returned a response from the instruction
        """
        logger.info('Instruction done, uid=%s', uid)
        instruction = future.result() # Get the result of our request. Might had failed though, send it anyway
        self.responseHandler.co.send((uid, instruction))

    def intercept(self, recvMsg):
        logger.debug('Instruction %s', recvMsg)
        uid, opcode, payload = recvMsg
        future = asyncio.Future()
        future.add_done_callback(functools.partial(self.request_done, uid))
        instrCtx = InstructionContext(opcode, payload, future)
        self.kernel.stackForExecution(InstructionContext(opcode, payload, future))
        return instrCtx, False

class FrontendFrontalController(BaseReceivedMessageHandler):
    def __init__(self, incomingHandler, outcomingHandler):
        BaseReceivedMessageHandler.__init__(self, incomingHandler)
        self.instructionsWaiting = {}
        self.incomingHandler = incomingHandler
        self.outcomingHandler = outcomingHandler

    @asyncio.coroutine
    def executeInstruction(self, instructionContext):
        """
            Send instruction to backend
        """

        uid = uuid4()
        uid = uid.int

        logger.debug('Executing instruction %s, uid=%s', instructionContext, uid)
        self.instructionsWaiting[uid] = asyncio.Future()
        # Send it to the pipeline
        self.outcomingHandler.co.send((uid, instructionContext))
        # Wait until the backend anwser
        ret, error = yield from self.instructionsWaiting[uid]

        logger.debug('Instruction %s had been executed and returned, uid=%s, ret=%s, error=%s', instructionContext, uid, ret, error)

        if error not in (None, 'None'):
            logger.error('Backend error: %s', error)
            raise Exception(error)
        else:
            return ret

    def intercept(self, recvMsg):
        uid, opcode, ret, error = recvMsg
        future = self.instructionsWaiting[uid]
        future.set_result((ret, error))
        # Stop right there
        return None, True
