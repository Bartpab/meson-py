from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler
import logging

logger = logging.getLogger('Protocol.IN')

class BaseFormatRouter(BaseReceivedMessageHandler):
    """
        Used to detect and route messages in a given format
    """
    def __init__(self, parent=None):
        BaseReceivedMessageHandler.__init__(self, parent)

    def isCompatible(self, recvMsg):
        raise NotImplementedError(self.__class__.__name__)

    def unwrap(self, recvMsg):
        raise NotImplementedError(self.__class__.__name__)

    def intercept(self, recvMsg):
        # Is format handled and we can unwrap the data
        if self.isCompatible(recvMsg):
            return self.unwrap(recvMsg), False
        # Can't continue further
        else:
            return recvMsg, True

import json
class IncomingJSONRouter(BaseFormatRouter):
    def isCompatible(self, recvMsg):
        try:
            json.loads(recvMsg)
            return True
        except ValueError as e:
            logger.error(e)
            return False

    def unwrap(self, recvMsg):
        return json.loads(recvMsg)
