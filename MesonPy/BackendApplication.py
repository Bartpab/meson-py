import asyncio
import logging
import websockets

from MesonPy.FrontalController import BackendFrontalController, Kernel
from MesonPy.Communication.Pipeline import CommunicationPipeline

from MesonPy.Communication.OutcomingHandler.FormatRouter import OutcomingJSONRouter
from MesonPy.Communication.IncomingHandler.FormatRouter import IncomingJSONRouter
from MesonPy.Communication.IncomingHandler.OperationRouter import BackendOperationRouter
from MesonPy.Communication.OutcomingHandler.OperationRouter import BackendOperationReturnRouter

logger = logging.getLogger(__name__)

class BackendApplication:
    def __init__(self):
        self.kernel = Kernel()
        self.pipelines = set()

    @asyncio.coroutine
    def onOpenningPipeline(self, pipeline):
        self.pipelines.add(pipeline)

        yield from pipeline.websocket.send('handshake')
        result = yield from pipeline.websocket.recv()

        if result:
            self.buildFrontalController(pipeline, result)
        else:
            pipeline.abort()

    def onClosingPipeline(self, pipeline):
        self.pipelines.remove(pipeline)

    def buildFrontalController(self, pipeline, protocol='json'):
        logger.info('Building Frontal Controller on pipeline=%s, protocol=%s', pipeline, protocol)

        if protocol not in ('json'):
            raise ValueError('Wrong protocol.')

        # Build incoming pipeline
        incomingPipeline = pipeline.getIncomingPipeline()
        inRoot = incomingPipeline.getRootHandler()
        # Set all format routers (JSON, MessagePack, XML, ...)
        incomingFormatRouter = IncomingJSONRouter(inRoot)
        # Operation router
        operationRouter = BackendOperationRouter(incomingFormatRouter)
        # Build outcoming pipeline
        outcomingPipeline = pipeline.getOutcomingPipeline()
        outRoot = outcomingPipeline.getRootHandler()
        # Set the format router according to the right protocol
        outcomingFormatRouter = OutcomingJSONRouter(outRoot)
        #
        operationReturnRouter = BackendOperationReturnRouter(outcomingFormatRouter)
        # Build our frontal controller and we are good to go
        return BackendFrontalController(self.kernel, operationRouter, operationReturnRouter)

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
            asyncio.get_event_loop().stop()

    def run(self):
        start_server = websockets.serve(self.handler, '127.0.0.1', 4242)
        loop = asyncio.get_event_loop()
        logger.info('Starting server at 127.0.0.1:4242')
        loop.run_until_complete(start_server)
        loop.run_forever()
        logger.info('Closing server at 127.0.0.1:4242')
