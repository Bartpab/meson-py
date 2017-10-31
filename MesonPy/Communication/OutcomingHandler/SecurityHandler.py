from MesonPy.Communication.OutcomingHandler.BaseMessageSender import BaseSendMessageHandler
from MesonPy.AESCipher import encrypt

class OutcomingSecurityHandler(BaseSendMessageHandler):
    def __init__(self, aes, parent=None):
        BaseSendMessageHandler.__init__(self, parent)
        self.aes = aes
    def intercept(self, recvMsg):
        encoded = encrypt(recvMsg, self.aes)
        return True, encoded
