import inspect
import re
import logging

logger = logging.getLogger(__name__)

def fetchClasses(module, classes = None, visited = None, filter = None):
    if classes is None:
        classes = []
    if visited is None:
        visited = []

    if module in visited:
        return classes
    else:
        visited.append(module)

    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj):
            if filter is not None:
                if filter(obj):
                    classes.append(obj)
            else:
                classes.append(obj)
        elif inspect.ismodule(obj):
            fetchClasses(obj, classes, visited, filter)
    return classes

def getServices(module):
    services = fetchClasses(module, None, None, lambda obj: re.match(r"^(?P<name>\w+)Service$", obj.__name__))
    return services

class ServiceInjector:
    def __init__(self, appContext):
        self.appContext = appContext
        self.localServiceCls = []

    def getLocalServiceClasses(self):
        return self.localServiceCls

    def generateLocalServiceName(self, locService):
        m = re.search(r"^(?P<name>\w+)Service$", locService.__name__)
        if m is None:
            raise ValueError('The local service class {} has no valid name. It should be (\w+)Service !'.format(locService.__name__))
        return 'services.local.' + m.group('name')

    def addLocalServiceClasses(self, module):
        services = getServices(module)
        for serviceClass in services:
            logger.info('Found local service class {}'.format(serviceClass.__name__))
            self.localServiceCls.append(serviceClass)

    def addSharedServiceClasses(self, module):
        services = getServices(module)
        for serviceClass in services:
            logger.info('Found shared service class {}'.format(serviceClass.__name__))
            self.appContext.addSharedServices(serviceClass(self.appContext))
