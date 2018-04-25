import json

class IProtocolHandler:
    def serialize(self, normalizedData):
        pass
    def deserialize(self, strRawData):
        pass

class JSONHandler(IProtocolHandler):
    def serialize(self, normalizedData):
        return json.dumps(normalizedData)
    def deserialize(self, strRawData):
        return json.loads(strRawData)

class SerializerManager:
    def __init__(self, app):
        self._protocolHandler = {}
        self.setHandler('json', JSONHandler())
    
    def setHandler(self, strProtocol, handler):
        self._protocolHandler[strProtocol] = handler
        return self
    
    def getHandler(self, strProtocol):
        return self._protocolHandler[strProtocol]

    def serialize(self, normalizedData, protocol):
        return self.getHandler(protocol).serialize(normalizedData)
    
    def deserialize(self, strRawData, protocol):
        return self.getHandler(protocol).deserialize(strRawData)