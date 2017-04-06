import asyncio

class BaseReceivedMessageHandler:
    """
        The Received Message Handler is used to build a workchain to process any message received from the Communication pipeline

        It intercepts any message, process it and pass down the processed data through its child.
        It can be used to transform any JSON-encoded strings into normalized data, etc...
    """
    def __init__(self, parent=None):
        self.childs = []
        self.coChilds = []
        # Get coroutine
        self.co = self.messageReceived()
        next(self.co)

        if parent is not None:
            parent.registerChildHandler(self)

    def registerChildHandler(self, child):
        if child not in self.childs:
            self.childs.append(child)

    def intercept(self, recvMsg):
        raise NotImplementedError()

    def sendTo(self, coroutine):
        self.coChilds.append(coroutine)
        
    @asyncio.coroutine
    def messageReceived(self):
        while True:
            recvMsg = yield
            interceptedMessage, stop = self.intercept(recvMsg)
            # Pass it to the next handler of the pipeline if the stop flag is not set to true
            if not stop:
                for child in self.childs:
                    child.co.send(interceptedMessage)
                for coChild in self.coChilds:
                    coChild.send(interceptedMessage)
