import asyncio
import logging
import uuid

import MesonPy.Constants as Constants

from MesonPy.Processor.RPC import RPCProcessor, RPCService
from MesonPy.Processor.PubSub import PubSubProcessor, PubSubService

logger = logging.getLogger(__name__)
consoleLogger   = logging.getLogger('MESON')


class KernelContext:
    def __init__(self):
        self.serviceManager = ServiceManager()
    def service(self, name):
        return self.serviceManager.get(name)
    def register_service(self, name, service):
        self.serviceManager.register(name, service)
        return service

class BackendKernel:
    def __init__(self):
        self._close = False
        self.kernelContext = KernelContext()
        self.processors = []
        self.boot()

    def boot(self):
        self.getContext().register_service(Constants.SERVICE_SESSION, SessionManager())
        # RPC
        rpc = RPCProcessor()
        # Expose the RPC Service
        self.getContext().register_service(Constants.SERVICE_RPC, RPCService(rpc))
        self.processors.append(rpc)
        # Pub/Sub
        pubsub = PubSubProcessor()
        #Expose the Pub Sub Service
        self.getContext().register_service(Constants.SERVICE_PUBSUB, PubSubService(pubsub))

        self.processors.append(pubsub)

    def getContext(self):
        return self.kernelContext

    def close(self):
        if not self._close:
            self._close = True
            logger.info('Exiting kernel')

    @asyncio.coroutine
    def step_proc(self, proc):
        instructionCtx = yield from proc.step(self.getContext())
        logger.debug('Instruction done %s', instructionCtx)

    @asyncio.coroutine
    def run(self):
        idles = {}
        while not self._close:
            try:
                stackContext = self.getContext()
                for proc in self.processors:
                    if proc not in idles:
                        idles[proc.__class__.__name__] = asyncio.ensure_future(proc.idle())

                # Wait until one of the processors wakes up
                awakens, idlings = yield from asyncio.wait([idle for idle in idles.values()], return_when=asyncio.FIRST_COMPLETED)
                logger.debug('Processors awakened %s', list(awakens))
                # Add the instruction processing to our event loop
                for awakened_tasks in awakens:
                    asyncio.ensure_future(self.step_proc(awakened_tasks.result()))
                    del idles[awakened_tasks.result().__class__.__name__]
            except Exception as e:
                logger.error(e)
                consoleLogger.error(e)

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
            logger.debug('instruction=%s, proc=%s', instructionCtx, processor.__class__.__name__)
            processor.push(instructionCtx)
        else:
            logger.warning('No processor found to execute this instruction, execution cancelled, context=%s', instructionCtx)
