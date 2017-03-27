import logging
from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler
logger = logging.getLogger(__name__)

class BackendOperationRouter(BaseReceivedMessageHandler):
    """
        End-point for operation execution
    """
    def intercept(self, recvMsg):
        if '__operation__' in recvMsg and '__payload__' in recvMsg and '__ticket__':
            return (recvMsg['__ticket__'], recvMsg['__operation__'], recvMsg['__payload__']), False
        else:
            return recvMsg, True

# Incoming Handler
class FrontendOperationReturnRouter(BaseReceivedMessageHandler):
    def intercept(self, recvMsg):
        if '__operation__' in recvMsg and '__return__' in recvMsg and '__ticket__':
            logger.debug('Returned operation, uid=%s, type=%s, return=%s', recvMsg['__ticket__'], recvMsg['__operation__'], recvMsg['__return__'])
            return (recvMsg['__ticket__'],
                    recvMsg['__operation__'],
                    recvMsg['__return__'],
                    recvMsg['__error__'] if '__error__' in recvMsg else None), False
        else:
            return recvMsg, True
