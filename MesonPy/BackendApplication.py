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

class BackendApplication:
    def __init__(self, id, server_secret="0000", client_secret="0000", singleClientMode=True):
        self.id             = id
        self.server_secret  = server_secret
        self.client_secret  = client_secret

        self._onExitCallback        = []
        self._onNewConnection       = []
        self._onConnectionClosed    = []

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
                handler.getSocketHandler().send('OK') # Send OK signal
                logger.info('The new connection is ready to be used!')
                self.notifyNewConnection(handler)
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

        finally:
            self.notifyConnectionClosed(handler)
            logger.info('Client has disconnected.')
            if self.singleClientMode is True:
                self.exit()

    def onConnectionClosed(self, callback):
        self._onNewConnection.append(callback)

    def notifyConnectionClosed(self, handler):
        for callback in self._onConnectionClosed:
            callback(self, handler)

    def onNewConnection(self, callback):
        self._onNewConnection.append(callback)

    def notifyNewConnection(self, handler):
        for callback in self._onNewConnection:
            callback(self, handler)

    def onExited(self, callback):
        self._onExitCallback.append(callback)

    def notifyExit(self):
        for callback in self._onExitCallback:
            callback(self)

    def exit(self):
        self.notifyExit()
        logger.info('Server is closed!')

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
            loop.run_forever()

        return runTask
