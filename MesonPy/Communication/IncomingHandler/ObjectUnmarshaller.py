import logging
from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler

class ObjectUnmarshaller(BaseReceivedMessageHandler):
    """
        End-point for operation execution
    """
    def intercept(self, recvMsg):
        if type(recvMsg) is dict or type(recvMsg) is list :
            return (recvMsg['__ticket__'], recvMsg['__operation__'], recvMsg['__payload__']), False
        else:
            return recvMsg, True
