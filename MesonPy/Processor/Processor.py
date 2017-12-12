import logging
import asyncio
import functools

logger = logging.getLogger(__name__)

class InstructionContext:
    def __init__(self, operationType, payload, future = None, session = None):
        self.future = future
        self.session = session
        self.operationType = operationType
        self.payload = payload
        self.ret = None
        self.error = None

    def done(self):
        if self.future is not None:
            self.future.set_result(self)
    def __str__(self):
        return 'operation={}, {}'.format(self.operationType, ('session={}'.format(str(self.session.id)) if self.session != None else 'no session known'))

class iInstruction:
    def canHandleInstruction(self, context):
        raise NotImplementedError()
    def executeLogic(self, instructionCtx, procCtx):
        raise NotImplementedError()

class iProcessor:
    def canHandleOperation(self, instructionCtx):
        raise NotImplementedError()
    def push(self, instructionCtx):
        raise NotImplementedError()

    @asyncio.coroutine
    def idle(self):
        pass

    @asyncio.coroutine
    def step(self, stackContext):
        raise NotImplementedError()
