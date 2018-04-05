import logging
import asyncio
import functools
from uuid import uuid4

import MesonPy.Constants as Constants

from MesonPy.Communication.Duplex import Duplex

from MesonPy.Communication.IncomingHandler.OperationRouter import BackendOperationRouter
from MesonPy.Communication.OutcomingHandler.OperationRouter import BackendOperationReturnRouter, PushOperationRouter

from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler
from MesonPy.Processor.Processor import InstructionContext

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

class BackendFrontalController:
    def __init__(self, kernel, lowerLevelDuplex):
        self.lowerLevelDuplex = lowerLevelDuplex

        self.operationRequestDuplex = Duplex(BackendOperationRouter(self.lowerLevelDuplex.incoming), BackendOperationReturnRouter(self.lowerLevelDuplex.outcoming))

        self.pushHandler = PushOperationRouter(self.lowerLevelDuplex.outcoming)

        opRequestCoroutine = self.operationRequestGenerator()
        next(opRequestCoroutine)
        self.operationRequestDuplex.incoming.sendTo(opRequestCoroutine)

        self.kernel = kernel
        # Register the front as a session
        sessionService = self.kernel.getContext().service(Constants.SERVICE_SESSION)
        self.session = sessionService.new(self)

    def request_done(self, uid, future):
        """
            The kernel had returned a response from the instruction
        """
        # Get the result of our request. Might had failed though, send it anyway
        instruction = future.result()
        self.operationRequestDuplex.outcoming.co.send((uid, instruction))

    @asyncio.coroutine
    def operationRequestGenerator(self):
        while True:
            uid, opcode, payload = yield
            logger.debug('Operation %s', opcode)
            future = asyncio.Future()
            future.add_done_callback(functools.partial(self.request_done, uid))
            instrCtx = InstructionContext(opcode, payload, future, self.session)
            self.kernel.stackForExecution(instrCtx)

    @asyncio.coroutine
    def operationPushGenerator(self):
        pass

    def push(self, instructionCtx):
        self.pushHandler.co.send('-1', instructionCtx)

    def exit(self):
        pass

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
            logger.error('Backend error: type=%s, message=%s', error['name'], error['message'])
            raise Exception(error['message'])
        else:
            return ret

    def intercept(self, recvMsg):
        uid, opcode, ret, error = recvMsg
        future = self.instructionsWaiting[uid]
        future.set_result((ret, error))
        # Stop right there
        return None, True
