from MesonPy.Communication.IncomingHandler.BaseMessageReceiver import BaseReceivedMessageHandler

class Duplex:
    def __init__(self, inHandler, outHandler):
        self.incoming = inHandler
        self.outcoming = outHandler
