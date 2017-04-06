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
from MesonPy.Processor.Kernel import BackendKernel
from MesonPy.Communication.Duplex import Duplex
from MesonPy.Communication.Pipeline import CommunicationPipeline

from MesonPy.Communication.OutcomingHandler.FormatRouter import OutcomingJSONRouter
from MesonPy.Communication.IncomingHandler.FormatRouter import IncomingJSONRouter


logger = logging.getLogger(__name__)

def rpcAction(app, controller, action):
    def wrapper(*args, __session__):
        keywords = [arg for arg in inspect.getfullargspec(action).args if (arg is not 'self' and arg is not 'instanceContext')]
        logger.debug(keywords)
        kargs = {keywords[i]: args[i] for i in range(len(keywords))}
        kargs['self'] = controller
        kargs['instanceContext'] = app.getInstanceContext(__session__)

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
    builders = fetchClasses(controllerModule, None, None, lambda obj: re.match("(.*?)Controller", obj.__name__))
    return builders

class InstanceContext:
    def __init__(self, session):
        self.session = session

class BackendApplication:
    def __init__(self):
        self.kernel = BackendKernel()
        self.fronts = {}
        self.instances = {}

        self.boot()

    def boot(self):
        self.sessionManager = self.getService(Constants.SERVICE_SESSION)
        self.sessionManager.onNew(self.newInstance)
        self.rpcService = self.getService(Constants.SERVICE_RPC)

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

    def getService(self, name):
        return self.kernel.getContext().service(name)

    def newInstance(self, session):
        self.instances[session.id] = InstanceContext(session)
    def getInstanceContext(self, session):
        return self.instances[session.id]
    def generateRPCName(self, controllerName, actionName):
        return 'com.rpc.controllers.{}.{}'.format(controllerName, actionName)

    def loadControllers(self, module):
        controllers = getControllers(module)
        for controller in controllers:
            self.addController(controller)

    # Serve controller actions as rpc calls in a session context
    def addController(self, controller):
        m = re.search(r'(?P<name>\w+)Controller', controller.__name__)
        if m is not None:
            controllerName = m.group('name')
        else:
            logger.warning('Invalid controller name for {}'.format(controller.__name__))
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
