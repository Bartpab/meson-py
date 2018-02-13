import asyncio
import logging
import websockets
import sys
import functools
import re
import inspect
import json
import bcrypt
import socket
import os
import pyscrypt
import pyaes
import binascii
import hashlib
from base64 import b64encode
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
import MesonPy.Constants as Constants

from MesonPy.FrontalController import BackendFrontalController
from MesonPy.Processor.Kernel import BackendKernel, ServiceManager
from MesonPy.Communication.Duplex import Duplex
from MesonPy.Communication.Pipeline import CommunicationPipeline
from MesonPy.AESCipher import encrypt

from MesonPy.Communication.OutcomingHandler.FormatRouter import OutcomingJSONRouter
from MesonPy.Communication.IncomingHandler.FormatRouter import IncomingJSONRouter
from MesonPy.Communication.IncomingHandler.SecurityHandler import IncomingSecurityHandler
from MesonPy.Communication.OutcomingHandler.SecurityHandler import OutcomingSecurityHandler

from MesonPy.Service.ServiceInjector import ServiceInjector
from MesonPy.Service.TaskExecutor import TaskExecutor

logger          = logging.getLogger(__name__)
consoleLogger   = logging.getLogger('MESON')
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
consoleFormatter = logging.Formatter('%(asctime)s :: %(levelname)s :: %(message)s')
ch.setFormatter(consoleFormatter)
consoleLogger.addHandler(ch)

def rpcAction(app, controller, action):
    @asyncio.coroutine
    def wrapper(*args, __session__):
        instanceManager = app.getSharedService(Constants.SERVICE_INSTANCE)
        kargs = {}
        kargs['instanceContext'] = instanceManager.getBySession(__session__)
        controllerAction = functools.partial(action, *args, **kargs)
        ret = yield from controllerAction()
        return ret
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
        return self.sharedServiceManager.get(name)

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
    def __init__(self, id, server_secret="0000", client_secret="0000", singleClientMode=True):
        self.id             = id
        self.server_secret  = server_secret
        self.client_secret  = client_secret

        self.kernel = BackendKernel()
        self.fronts = {}
        self.context = BackendApplicationContext(self)
        self.singleClientMode = singleClientMode
        self.boot()

    def boot(self):
        self.addSharedService(Constants.SERVICE_SERVICE_INJECTOR, ServiceInjector(self.context))
        self.addSharedService(Constants.SERVICE_INSTANCE, InstanceManager(self.context))
        self.addSharedService(Constants.SERVICE_TASK_EXECUTOR, TaskExecutor(self.context))
        self.rpcService = self.getSharedService(Constants.SERVICE_RPC)

    # Pipeline Event Management
    @asyncio.coroutine
    def onOpenningPipeline(self, pipeline):
        # Send a random salt
        salt = os.urandom(16)
        consoleLogger.info('Sending nonce %s', salt)
        yield from pipeline.websocket.send(salt)

        # Get the APP REQUEST from the client, encrypted with 256 bits AES key built on a PBKDF2 of the client secret
        # REQUEST [Encrypted Token] WITH [IV]
        consoleLogger.info('Waiting for the client REQUEST %s', pipeline.websocket.remote_address)
        request         = yield from asyncio.wait_for(pipeline.websocket.recv(), timeout=5)
        m               = re.search('REQUEST (?P<encoded>.*) WITH (?P<iv>.*)', request)
        consoleLogger.info('REQUEST received from %s', pipeline.websocket.remote_address)

        if m is None:
            pipeline.abort()

        encodedToken    = binascii.a2b_hex(m.group(1))
        iv              = binascii.a2b_hex(m.group(2))

        clientKEY       = hashlib.pbkdf2_hmac('sha1', self.client_secret.encode('utf-8'), salt, 1000, dklen=32)
        clientAES       = AES.new(clientKEY, AES.MODE_CBC, iv)

        decryptedToken  = re.search('({.*})', clientAES.decrypt(encodedToken).decode('utf-8').strip()).group(1)

        logger.debug(decryptedToken)
        token = json.loads(decryptedToken)

        # Check request token
        if token['salt'] is not salt and token['app_id'] is not self.id:
            logger.warning('Invalid client request detected')
            pipeline.abort()

        consoleLogger.info('Request from %s is valid!', pipeline.websocket.remote_address)

        serverKEY           = hashlib.pbkdf2_hmac('sha1', self.server_secret.encode('utf-8'), salt, 1000, dklen=32)
        serverIV            = os.urandom(16)
        serverAES           = AES.new(serverKEY, AES.MODE_CBC, serverIV)

        # Generate a random AES key of 256 bits
        session_randomKey   = hashlib.pbkdf2_hmac('sha1', os.urandom(32), salt, 1000, dklen=32)
        session_randomIV    = os.urandom(16)
        session_randomAES   = AES.new(session_randomKey, AES.MODE_CBC, session_randomIV)

        replyObj            = {'key': binascii.b2a_hex(session_randomKey).decode('utf8'), 'alg': 'AES_256', 'iv': binascii.b2a_hex(session_randomIV).decode('utf8')}
        replyToken          = json.dumps(replyObj)

        encodedReplyToken   = binascii.b2a_hex(encrypt(replyToken, serverAES)).decode('utf8')

        serverDecrypt = AES.new(serverKEY, AES.MODE_CBC, serverIV)

        logger.info(serverDecrypt.decrypt(encodedReplyToken))

        consoleLogger.info('Send the session key to %s', pipeline.websocket.remote_address)
        yield from pipeline.websocket.send('REPLY {} WITH {}'.format(encodedReplyToken, binascii.b2a_hex(serverIV).decode('utf8')))
        protocol = yield from pipeline.websocket.recv()

        if protocol:
            frontalController = self.buildFrontalController(pipeline, protocol, (session_randomKey, session_randomIV))
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

    def buildFrontalController(self, pipeline, protocol='json', aes=None):
        logger.info('Building Frontal Controller on pipeline=%s, protocol=%s', pipeline, protocol)

        consoleLogger.info('Building Frontal Controller on remote_addr=%s, protocol=%s', pipeline.websocket.remote_address, protocol)

        if aes is None:
            logger.warning('No AES had been defined.')

        if protocol not in ('json'):
            raise ValueError('Wrong protocol.')

        # Build incoming pipeline
        incomingPipeline = pipeline.getIncomingPipeline()
        inRoot = incomingPipeline.getRootHandler()
        incomingSecurity = IncomingSecurityHandler(aes, inRoot)
        incomingFormatRouter = IncomingJSONRouter(incomingSecurity)

        # Build outcoming pipeline
        outcomingPipeline = pipeline.getOutcomingPipeline()
        outRoot = outcomingPipeline.getRootHandler()
        outcomingSecurity = OutcomingSecurityHandler(aes, outRoot)
        outcomingFormatRouter = OutcomingJSONRouter(outcomingSecurity)

        lowerLevelDuplex = Duplex(incomingFormatRouter, outcomingFormatRouter)
        # Build our frontal controller and we are good to go
        return BackendFrontalController(self.kernel, lowerLevelDuplex)

    def onWebsocketClose(self, websocket):
        if self.singleClientMode == True:
            asyncio.get_event_loop().stop()

    @asyncio.coroutine
    def handler(self, websocket, path):
        logger.info('New connection %s', websocket)
        consoleLogger.info('New connection %s', websocket.remote_address)
        consoleLogger.info('Building communication pipeline %s', websocket.remote_address)
        pipeline = CommunicationPipeline(websocket)

        try:
            consoleLogger.info('Openning communication pipeline %s', websocket.remote_address)
            try:
                yield from self.onOpenningPipeline(pipeline)
                consoleLogger.info('Communication pipeline opened %s!', websocket.remote_address)
            except asyncio.TimeoutError as e: # Try a second time
                consoleLogger.info('Timeout on communication pipeline init, will try again...', websocket.remote_address)
                yield from self.onOpenningPipeline(pipeline)
                consoleLogger.info('Communication pipeline opened %s!', websocket.remote_address)
        except websockets.exceptions.ConnectionClosed as e:
            consoleLogger.error('Cannot open communication pipeline for %s, because ', websocket.remote_address, e)
            logger.error(e)
            self.onWebsocketClose(websocket)
            return
        except asyncio.TimeoutError as e:
            consoleLogger.error('Cannot open communication pipeline for %s in time...', websocket.remote_address)
            logger.error(e)
            self.onWebsocketClose(websocket)
            return

        try:
            yield from pipeline.run()
        finally:
            logger.info('Disconnection %s', websocket.remote_address)
            consoleLogger.info('Disconnection %s', websocket.remote_address)
            self.onClosingPipeline(pipeline)
            pipeline.close()
            #Wait for the pipeline to close
            yield from asyncio.ensure_future(pipeline.wait_close())
            self.onWebsocketClose(websocket)


    def findUsablePort(self):
        port = 4242
        found = False
        while not found:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(('127.0.0.1', port))
                found = True
            except socket.error as e:
                port = port + 1
            finally:
                s.close()
        return port

    def run(self):
        port = self.findUsablePort()

        self.start_server = websockets.serve(self.handler, '127.0.0.1', port, max_size=None)

        loop = asyncio.get_event_loop()

        #Sending ready signal
        print('Starting...')
        sys.stdout.flush()
        print('SERVING {} ON {}:{}'.format(self.id, '127.0.0.1', port))
        sys.stdout.flush()

        logger.info('Started server at 127.0.0.1:{}'.format(port))

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
