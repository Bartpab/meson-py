import asyncio
import logging
import websockets
import sys
import functools
import re
import inspect
import socket
import MesonPy.Constants as Constants

from MesonPy.ApplicationContext      import ApplicationContext

from MesonPy.ConnectionHandler       import ConnectionHandler

from MesonPy.CommunicationStrategies import AggregatedConnectionStrategy
from MesonPy.CommunicationStrategies import SecuredBackendConnectionStrategy
from MesonPy.CommunicationStrategies import SerializerStrategy
from MesonPy.CommunicationStrategies import NormalizerStrategy
from MesonPy.CommunicationStrategies import SessionStrategy
from MesonPy.CommunicationStrategies import BackendRPCStrategy

from MesonPy.Pipeline        import PipelineBuilder

from MesonPy.Instance        import InstanceManager
from MesonPy.Session         import SessionManager
from MesonPy.Normalizer      import NormalizerManager
from MesonPy.Serializer      import SerializerManager
from MesonPy.RPC             import BackendRPCService
from MesonPy.Controller      import ControllerManager
from MesonPy.ServiceInjector import ServiceInjector
from MesonPy.TaskExecutor    import TaskExecutor

logger          = logging.getLogger(__name__)

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

class BackendApplication:
    def __init__(self, id, server_secret="0000", client_secret="0000", singleClientMode=True):
        self.id             = id
        self.server_secret  = server_secret
        self.client_secret  = client_secret

        self.handlers = []

        self._connectionStrategy = AggregatedConnectionStrategy()

        self.context = ApplicationContext(self)
        self.singleClientMode = singleClientMode
        self.boot()

    def getConnectionStrategy(self):
        return self._connectionStrategy
    
    def getContext(self):
        return self.context
    
    def boot(self):
        # Register the most basic services
        self.getContext().addSharedService(Constants.SERVICE_RPC,                BackendRPCService(self.context))
        self.getContext().addSharedService(Constants.SERVICE_CONTROLLER,         ControllerManager(self.context))
        
        self.getContext().addSharedService(Constants.SERVICE_SERVICE_INJECTOR,   ServiceInjector(self.context))
        self.getContext().addSharedService(Constants.SERVICE_SESSION,            SessionManager(self.context))
        self.getContext().addSharedService(Constants.SERVICE_INSTANCE,           InstanceManager(self.context))
        
        self.getContext().addSharedService(Constants.SERVICE_NORMALIZE,          NormalizerManager(self.context))
        self.getContext().addSharedService(Constants.SERVICE_TASK_EXECUTOR,      TaskExecutor(self.context))
        self.getContext().addSharedService(Constants.SERVICE_SERIALIZER,         SerializerManager(self.context))

        self.getConnectionStrategy().stack(SecuredBackendConnectionStrategy(self.server_secret, self.client_secret))
        self.getConnectionStrategy().stack(SerializerStrategy(self.getContext().getSharedService(Constants.SERVICE_SERIALIZER)))
        self.getConnectionStrategy().stack(NormalizerStrategy(self.getContext().getSharedService(Constants.SERVICE_NORMALIZE)))
        self.getConnectionStrategy().stack(SessionStrategy(self.getContext().getSharedService(Constants.SERVICE_SESSION)))
        self.getConnectionStrategy().stack(BackendRPCStrategy(self.getContext().getSharedService(Constants.SERVICE_RPC)))

    def loadControllers(self, module):
        controllers = getControllers(module)
        
        for controller in controllers:
            self.getContext().getSharedService(Constants.SERVICE_CONTROLLER).add(controller())

    @asyncio.coroutine
    def handler(self, websocket, path):
        logger.info('New connection %s', websocket)
        
        try:
            handler         = ConnectionHandler(websocket)
            pipelineBuilder = PipelineBuilder(handler.getRootPipeline())
        
            keepConnected = yield from self.getConnectionStrategy().newConnection(websocket, pipelineBuilder)
            
            if keepConnected is True:
                logger.info('Building backend pipeline...')
                pipelineBuilder.build()
                logger.info('The new connection is ready to be used!')
                yield from handler.getRunTask()
            else:
                logger.warning('The connection does not match the current strategy.')
                handler.close('Invalid connection.')
        
        except websockets.exceptions.ConnectionClosed as e:
            handler.close(str(e))
        
        except asyncio.TimeoutError as e:
            handler.close('Timeout from the client.')
        
        except Exception as e:
            logger.exception(e)

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

    def notifyReadyStatusOnStdOut(self, port):
        #Sending ready signal
        print('Starting...')
        sys.stdout.flush()
        print('SERVING {} ON {}:{}'.format(self.id, '127.0.0.1', port))
        sys.stdout.flush()
        logger.info('Started server at 127.0.0.1:{}'.format(port))
       
    @asyncio.coroutine
    def run(self, port, serverCo):
        self.notifyReadyStatusOnStdOut(port)
        yield from asyncio.ensure_future(serverCo)
    
    """
        Init the server
        If run flag is set to False, will return the pending run task
    """
    def init(self, run=True):
        port = self.findUsablePort()
        self.start_server = websockets.serve(self.handler, '127.0.0.1', port, max_size=None)

        loop    = asyncio.get_event_loop()
        runTask = asyncio.ensure_future(self.run(port, self.start_server))

        if run is True:
            loop.run_until_complete(runTask)
        
        return runTask

