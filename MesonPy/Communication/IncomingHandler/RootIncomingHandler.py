from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler

class RootReceivedMessageHandler(BaseReceivedMessageHandler):
    def intercept(self, recvMsg):
        return recvMsg, False
