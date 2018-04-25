import asyncio
import functools
import websockets
import MesonPy.Constants as Constants
import logging

from MesonPy.ApplicationContext      import ApplicationContext

from MesonPy.ConnectionHandler       import ConnectionHandler

from MesonPy.CommunicationStrategies import AggregatedConnectionStrategy
from MesonPy.CommunicationStrategies import SecuredFrontendConnectionStrategy
from MesonPy.CommunicationStrategies import SerializerStrategy
from MesonPy.CommunicationStrategies import NormalizerStrategy
from MesonPy.CommunicationStrategies import FrontendRPCStrategy

from MesonPy.Pipeline        import PipelineBuilder

from MesonPy.Instance        import InstanceManager
from MesonPy.Session         import SessionManager
from MesonPy.Normalizer      import NormalizerManager
from MesonPy.Serializer      import SerializerManager
from MesonPy.RPC             import FrontendRPCService

logger = logging.getLogger(__name__)

class FrontendApplication:
    def __init__(self, id, server_secret="0000", client_secret="0000", singleClientMode=True, address="127.0.0.1", port=4242):
        self.server_secret = server_secret
        self.client_secret = client_secret
        
        self.address       = address
        self.port          = port
        
        self.id = id

        self._context               = ApplicationContext(self)
        self._connectionStrategy    = AggregatedConnectionStrategy()

        self._connectedCallbacks    = []

        self._handler           = None

        self.boot()
    
    def exit(self):
        self._handler.close('Exiting the application')

    def onConnected(self, callback):
        self._connectedCallbacks.append(callback)

    def getContext(self):
        return self._context
    
    def getConnectionStrategy(self):
        return self._connectionStrategy

    def boot(self):
        self.getContext().addSharedService(Constants.SERVICE_RPC,                FrontendRPCService(self.getContext()))
        self.getContext().addSharedService(Constants.SERVICE_NORMALIZE,          NormalizerManager(self.getContext()))
        self.getContext().addSharedService(Constants.SERVICE_SERIALIZER,         SerializerManager(self.getContext()))

        self.getConnectionStrategy().stack(SecuredFrontendConnectionStrategy(self.id, self.server_secret, self.client_secret))
        self.getConnectionStrategy().stack(SerializerStrategy(self.getContext().getSharedService(Constants.SERVICE_SERIALIZER)))
        self.getConnectionStrategy().stack(NormalizerStrategy(self.getContext().getSharedService(Constants.SERVICE_NORMALIZE)))
        self.getConnectionStrategy().stack(FrontendRPCStrategy(self.getContext().getSharedService(Constants.SERVICE_RPC)))
    
    def notifyConnected(self):
        for callback in self._connectedCallbacks:
            callback(self)

    @asyncio.coroutine
    def run(self):
        url = 'ws://{}:{}/'.format(self.address, self.port)
        logger.info('Connecting to %s', url)
        try:
            websocket       = yield from websockets.connect(url)
            handler         = ConnectionHandler(websocket)
            pipelineBuilder = PipelineBuilder(handler.getRootPipeline())
       
            keepConnected   = yield from self.getConnectionStrategy().newConnection(websocket, pipelineBuilder)
            
            if keepConnected is True:
                logger.info('Building frontend pipeline...')
                pipelineBuilder.build()
                self.notifyConnected()
                logger.info('The frontend is ready!')
                 # Wait until the handler task is stopped
                self._handler   = handler
                yield from handler.getRunTask()
            else:
                logger.error('The connection does not match the current strategy.')
                handler.close('The connection does not match the current strategy.')
                return
        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed as e:
            handler.close(str(e))
        except asyncio.TimeoutError as e:
            handler.close('Timeout from the server.')
        except Exception as e:
            handler.close(str(e))
            logger.exception(e)
        finally:
            logger.info('Closing frontend application...')
    
    """
        Init the server
        If run flag is set to False, will return the pending run task
    """
    def init(self, run=True):
        loop    = asyncio.get_event_loop()
        runTask = asyncio.ensure_future(self.run())

        self._runTask = runTask

        if run == True:
            loop.run_until_complete(runTask)
        
        return runTask        

            