import asyncio
import logging
import uuid

import MesonPy.Constants as Constants

from MesonPy.Processor.RPC import RPCProcessor, RPCService
from MesonPy.Processor.PubSub import PubSubProcessor, PubSubService

logger = logging.getLogger(__name__)

class Session:
    def __init__(self, sessionId, frontalController):
        self.front = frontalController
        self.id = sessionId
        self.closeCallbacks = []

    def close(self):
        for callback in self.closeCallbacks:
            callback(self)

    def onClose(self, callback):
        if callback not in self.closeCallbacks:
            self.closeCallbacks.append(callback)

class SessionManager:
    def __init__(self):
        self._sessions = {}
        self.newCallbacks = []
        self.closeCallbacks = []

    def onNew(self, callback):
        self.newCallbacks.append(callback)

    def generateId(self):
        return uuid.uuid4().int

    def sessions(self):
        return self._sessions

    def new(self, frontalController):
        session = Session(self.generateId(), frontalController)
        logger.info('New session, id={}'.format(session.id))
        self._sessions[session.id] = session

        # Call everybody who wants to know about a new session
        for callback in self.newCallbacks:
            callback(session)

        return session

    def remove(self, session):
        self._sessions[session.id].close()
        del self._sessions[session.id]

class ServiceManager:
    def __init__(self):
        self.services = {}
    def register(self, name, service):
        self.services[name] = service
    def get(self, name):
        return self.services[name]

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
    def run(self):
        tasks = {}
        while not self._close:
            try:
                stackContext = self.getContext()
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
            except TypeError as e:
                continue
            except Exception as e:
                logger.error(e)

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
