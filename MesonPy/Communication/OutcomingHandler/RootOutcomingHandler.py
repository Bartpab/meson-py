import logging

from MesonPy.Communication.OutcomingHandler.BaseMessageSender import BaseSendMessageHandler

logger = logging.getLogger(__name__)

class RootSendMessageHandler(BaseSendMessageHandler):
    def __init__(self, sendPipeline):
        BaseSendMessageHandler.__init__(self)
        self.sendPipeline = sendPipeline

    def intercept(self, sendMsg):
        logger.info('Sending %s', sendMsg)
        self.sendPipeline.process(sendMsg)
        # We hit rock bottom, don't go further
        return None, False
