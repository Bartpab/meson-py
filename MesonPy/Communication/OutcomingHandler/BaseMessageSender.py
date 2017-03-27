import asyncio

class BaseSendMessageHandler:
    def __init__(self, parent = None):
        # Get coroutine
        self.parent = parent
        self.co = self.sendMessage()
        next(self.co)

    def intercept(self, sendMsg):
        raise NotImplementedError()

    def sendMessage(self):
        while True:
            sendMsg = yield
            interceptedSendMsg, stop = self.intercept(sendMsg)
            # Pass it down to the next
            if not stop and self.parent is not None:
                self.parent.co.send(interceptedSendMsg)
