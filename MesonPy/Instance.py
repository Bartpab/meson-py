from MesonPy.Service import ServiceManager
import MesonPy.Constants as Constants 
import logging

logger = logging.getLogger(__name__)
class InstanceContext:
    """
        An instance context hold all local data bound to a session.

        The instance context is injected in controller actions, each time the client is calling the backend logic
        through RPC calls.

        There are local services, shared services, local data pool, shared data pool, etc.
    """
    def __init__(self, session, appContext):
        self.session = session
        self.appContext = appContext
        self.localServiceManager = ServiceManager()
        self.eventListeners = {}

    def on(self, event, callback):
        if event not in self.eventListeners:
            self.eventListeners[event] = []
        if callback not in self.eventListeners[event]:
            self.eventListeners[event].append(callback)

    def emit(self, event, **kargs):
        if event in self.eventListeners:
            for callback in self.eventListeners[event]:
                callback(**kargs)


    def getSharedService(self, name):
        return self.appContext.getSharedService(name)

    def getLocalService(self, name):
        return self.localServiceManager.get(name)

    def addLocalService(self, name, service):
        self.localServiceManager.register(name, service)

class InstanceManager:
    """
        Manage all instances
    """
    def __init__(self, appContext):
        self.appContext = appContext

        self.appContext.getSharedService(Constants.SERVICE_SESSION).onNew(self.newInstance)
        self.serviceInjector = self.appContext.getSharedService(Constants.SERVICE_SERVICE_INJECTOR)

        self.newCallbacks = set()
        self.instances = {}

    def getBySession(self, session):
        return self.instances[session.id]

    def onNew(self, callback):
        self.newCallbacks.add(callback)

    def newInstance(self, session):
        instanceCtx = InstanceContext(session, self.appContext)

        localServices = []

        for localServiceCls in self.serviceInjector.getLocalServiceClasses():
            locServiceName = self.serviceInjector.generateLocalServiceName(localServiceCls)
            localService = localServiceCls(instanceCtx)
            localServices.append(localService)
            instanceCtx.addLocalService(locServiceName, localService)

        for localService in localServices:
            if hasattr(localService, 'boot') == True:
                logger.info('Booting local service {} for session {}'.format(localService.__class__.__name__, session.id))
                localService.boot()

        for localService in localServices:
            if hasattr(localService, 'afterBoot') == True:
                logger.info('After boot local service {} for session {}'.format(localService.__class__.__name__, session.id))
                localService.afterBoot()

        for localService in localServices:
            if hasattr(localService, 'bootDone') == True:
                localService.bootDone()

        self.instances[session.id] = instanceCtx

        for callback in self.newCallbacks:
            callback(instanceCtx)
