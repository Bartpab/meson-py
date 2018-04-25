class ApplicationContext:
    def __init__(self, app):
        self.app = app
        self._sharedServices = {}

    def addSharedService(self, name, service):
        self._sharedServices[name] = service
    
    def getSharedService(self, name):
        return self._sharedServices[name]
    
    def getSharedServices(self):
        return self._sharedServices