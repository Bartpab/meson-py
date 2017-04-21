import asyncio
import logging
import websockets
import sys
import functools
import re
import inspect

from contextlib import suppress

import MesonPy.Constants as Constants

from MesonPy.FrontalController import BackendFrontalController
from MesonPy.Processor.Kernel import BackendKernel, ServiceManager
from MesonPy.Communication.Duplex import Duplex
from MesonPy.Communication.Pipeline import CommunicationPipeline

from MesonPy.Communication.OutcomingHandler.FormatRouter import OutcomingJSONRouter
from MesonPy.Communication.IncomingHandler.FormatRouter import IncomingJSONRouter

from MesonPy.Service.ServiceInjector import ServiceInjector

logger = logging.getLogger(__name__)

def rpcAction(app, controller, action):
    def wrapper(*args, __session__):
        instanceManager = app.getSharedService(Constants.SERVICE_INSTANCE)
        keywords = [arg for arg in inspect.getfullargspec(action).args if (arg is not 'self' and arg is not 'instanceContext')]

        kargs = {keywords[i]: args[i] for i in range(len(keywords))}
        kargs['instanceContext'] = instanceManager.getBySession(__session__)

        controllerAction = functools.partial(action, **kargs)

        return controllerAction()
    return wrapper

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

def getControllers(controllerModule):
    controllers = fetchClasses(controllerModule, None, None, lambda obj: re.match("(.*?)Controller", obj.__name__))
    return controllers

class InstanceContext:
    """
        An instance context hold all local data bound to a session.

        The instance context is injected in controller actions, each time the client is calling the backend logic
        through RPC calls.

        There are local services, shared services, local data pool, shared data pool, etc.
    """
    def __init__(self, session, sharedServiceManager):
        self.session = session
        self.sharedServiceManager = sharedServiceManager
        self.localServiceManager = ServiceManager()

    def getLocalService(self, name):
        return self.localServiceManager.get(name)
    def addLocalService(self, name, service):
        self.localServiceManager.register(name, service)

class InstanceManager:
    """
        Manage all instances
    """
    def __init__(self, appContext):
        self.sharedServiceManager = appContext.getSharedServiceManager()

        self.sharedServiceManager.get(Constants.SERVICE_SESSION).onNew(self.newInstance)
        self.serviceInjector = self.sharedServiceManager.get(Constants.SERVICE_SERVICE_INJECTOR)

        self.newCallbacks = set()
        self.instances = {}

    def getBySession(self, session):
        return self.instances[session.id]

    def onNew(self, callback):
        self.newCallbacks.add(callback)

    def newInstance(self, session):
        instanceCtx = InstanceContext(session, self.sharedServiceManager)

        for localServiceCls in self.serviceInjector.getLocalServiceClasses():
            locServiceName = self.serviceInjector.generateLocalServiceName(localServiceCls)
            instanceCtx.addLocalService(locServiceName, localServiceCls(instanceCtx))

        self.instances[session.id] = instanceCtx

        for callback in self.newCallbacks:
            callback(instanceCtx)

class BackendApplicationContext:
    def __init__(self, app):
        self.app = app

    def getSharedServiceManager(self):
        return self.app.getSharedServiceManager()
    def addSharedService(self, name, service):
        self.app.addSharedService(name, service)
    def getSharedService(self, name):
        return self.app.getSharedService(name)

class BackendApplication:
    def __init__(self):
        self.kernel = BackendKernel()
        self.fronts = {}
        self.context = BackendApplicationContext(self)
        self.boot()

    def boot(self):
        self.addSharedService(Constants.SERVICE_SERVICE_INJECTOR, ServiceInjector(self.context))
        self.addSharedService(Constants.SERVICE_INSTANCE, InstanceManager(self.context))
        self.rpcService = self.getSharedService(Constants.SERVICE_RPC)

    # Pipeline Event Management
    @asyncio.coroutine
    def onOpenningPipeline(self, pipeline):
        yield from pipeline.websocket.send('handshake')
        result = yield from pipeline.websocket.recv()
        if result:
            frontalController = self.buildFrontalController(pipeline, result)
            self.fronts[id(pipeline)] = frontalController
        else:
            pipeline.abort()
    def onClosingPipeline(self, pipeline):
        uid = id(pipeline)
        if uid in self.fronts:
            self.fronts[uid].exit()
            del self.fronts[uid]

    def getSharedServiceManager(self):
        return self.kernel.getContext().serviceManager
    def getSharedService(self, name):
        return self.kernel.getContext().service(name)
    def addSharedService(self, name, service):
        self.kernel.getContext().register_service(name, service)

    def generateRPCName(self, controllerName, actionName):
        return 'com.rpc.controllers.{}.{}'.format(controllerName, actionName)

    def loadControllers(self, module):
        controllers = getControllers(module)
        for controller in controllers:
            self.addController(controller())

    # Serve controller actions as rpc calls in a session context
    def addController(self, controller):
        m = re.search(r'(?P<name>\w+)Controller', controller.__class__.__name__)
        if m is not None:
            controllerName = m.group('name')
        else:
            logger.warning('Invalid controller name for {}'.format(controller.__class__.__name__))
            return

        logger.info('Found controller {}'.format(controllerName))

        methods = [getattr(controller, method) for method in dir(controller) if callable(getattr(controller, method))]

        actions = {}

        for method in methods:
            m = re.search(r'^action(?P<name>\w+)$', method.__name__)
            if m is not None:
                actions[m.group('name')] = method

        for name, action in actions.items():
            logger.info('Serving action "{}" of controller "{}" as RPC "{}"'.format(name, controllerName, self.generateRPCName(controllerName, name)))
            self.rpcService.register(self.generateRPCName(controllerName, name), rpcAction(self, controller, action))

    def buildFrontalController(self, pipeline, protocol='json'):
        logger.info('Building Frontal Controller on pipeline=%s, protocol=%s', pipeline, protocol)

        if protocol not in ('json'):
            raise ValueError('Wrong protocol.')

        # Build incoming pipeline
        incomingPipeline = pipeline.getIncomingPipeline()
        inRoot = incomingPipeline.getRootHandler()
        incomingFormatRouter = IncomingJSONRouter(inRoot)

        # Build outcoming pipeline
        outcomingPipeline = pipeline.getOutcomingPipeline()
        outRoot = outcomingPipeline.getRootHandler()
        outcomingFormatRouter = OutcomingJSONRouter(outRoot)

        lowerLevelDuplex = Duplex(incomingFormatRouter, outcomingFormatRouter)
        # Build our frontal controller and we are good to go
        return BackendFrontalController(self.kernel, lowerLevelDuplex)

    @asyncio.coroutine
    def handler(self, websocket, path):
        logger.info('New connection %s', websocket)
        pipeline = CommunicationPipeline(websocket)
        try:
            yield from self.onOpenningPipeline(pipeline)
        except websockets.exceptions.ConnectionClosed as e:
            logger.error(e)
            asyncio.get_event_loop().stop()
            return
        try:
            yield from pipeline.run()
        finally:
            logger.info('Disconnection %s', websocket)
            self.onClosingPipeline(pipeline)
            pipeline.close()
            #Wait for the pipeline to close
            yield from asyncio.ensure_future(pipeline.wait_close())
            asyncio.get_event_loop().stop()

    def run(self):
        self.start_server = websockets.serve(self.handler, '127.0.0.1', 4242)

        loop = asyncio.get_event_loop()

        #Sending ready signal
        sys.stdout.write('Sending ready signal: ')
        sys.stdout.flush()
        sys.stdout.write('0x4D454F57')
        sys.stdout.flush()
        sys.stdout.write('\n')
        sys.stdout.flush()

        logger.info('Started server at 127.0.0.1:4242')

        self.kernelTask = asyncio.ensure_future(self.kernel.run())
        self.server = loop.run_until_complete(self.start_server)

        loop.run_forever()

        self.server.close()
        self.kernel.close()

        loop.run_until_complete(self.server.wait_closed())

        logger.info('Cleaning remaining tasks...')
        pending = asyncio.Task.all_tasks()
        for task in pending:
            task.cancel()

        # Run loop until tasks are cancelled
        loop.run_until_complete(asyncio.wait(pending, return_when=asyncio.ALL_COMPLETED))
        loop.close()

        logger.info('Exiting backend application! Bye!')
