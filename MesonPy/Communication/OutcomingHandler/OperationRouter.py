import logging
from MesonPy.Communication.OutcomingHandler.BaseMessageSender import BaseSendMessageHandler
logger = logging.getLogger(__name__)

class BackendOperationReturnRouter(BaseSendMessageHandler):
    def intercept(self, sendMsg):
        ticket, instruction = sendMsg
        normalizedData = {
            "__ticket__": ticket,
            "__operation__": instruction.operationType,
            "__return__": instruction.ret,
            "__error__": str(instruction.error)
        }
        return normalizedData, False

class FrontendOperationRouter(BaseSendMessageHandler):
    def intercept(self, sendMsg):
        ticket, instruction = sendMsg
        normalizedData = {
            "__ticket__": ticket,
            "__operation__": instruction.operationType,
            "__payload__": instruction.payload
        }
        logger.debug('Normalized requested instruction %s, result=%s, id=%s', instruction, normalizedData, ticket)
        return normalizedData, False
