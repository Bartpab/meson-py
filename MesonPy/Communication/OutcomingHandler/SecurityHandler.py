from MesonPy.Communication.OutcomingHandler.BaseMessageSender import BaseSendMessageHandler
from MesonPy.AESCipher import encrypt, decrypt
from Crypto.Cipher import AES
import binascii
import logging

logger = logging.getLogger('Security.OUT')

class OutcomingSecurityHandler(BaseSendMessageHandler):
    def __init__(self, aes, parent=None):
        BaseSendMessageHandler.__init__(self, parent)
        self.aesKey = aes[0]
        self.aesIV  = aes[1]
    def intercept(self, recvMsg):
        aes = AES.new(self.aesKey, AES.MODE_CBC, self.aesIV)

        encoded = encrypt(recvMsg, aes)
        strHex_encoded = binascii.b2a_hex(encoded).decode('utf8')

        return strHex_encoded, False
