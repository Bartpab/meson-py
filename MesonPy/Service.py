
class ServiceManager:
    def __init__(self):
        self.services = {}
    def register(self, name, service):
        self.services[name] = service
    def get(self, name):
        return self.services[name]