import json

from MesonPy.Communication.OutcomingHandler.BaseMessageSender import BaseSendMessageHandler

class OutcomingJSONRouter(BaseSendMessageHandler):
    def intercept(self, sendMsg):
        return json.dumps(sendMsg), False
