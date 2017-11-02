from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler
import binascii
import logging
from Crypto.Cipher import AES
from MesonPy.AESCipher import decrypt
logger = logging.getLogger('Security.IN')

class IncomingSecurityHandler(BaseReceivedMessageHandler):
    def __init__(self, aes, parent=None):
        BaseReceivedMessageHandler.__init__(self, parent)
        self.aesKey = aes[0]
        self.aesIV  = aes[1]
    def intercept(self, recvMsg):
        try:
            aes     = AES.new(self.aesKey, AES.MODE_CBC, self.aesIV)
            recvMsg =  binascii.a2b_hex(recvMsg)
            decoded = decrypt(recvMsg, aes)
            return decoded, False
        except Exception as e:
            logger.error(e)
            return None, True
