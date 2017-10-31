from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler
import binascii
class IncomingSecurityHandler(BaseReceivedMessageHandler):
    def __init__(self, aes, parent=None):
        BaseReceivedMessageHandler.__init__(self, parent)
        self.aes = aes
    def intercept(self, recvMsg):
        decoded = self.aes.decrypt(recvMsg).decode('utf-8')
        return True, decoded
