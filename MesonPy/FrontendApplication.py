import websockets
import asyncio
import logging

from MesonPy.Processor.Processor import InstructionContext

from MesonPy.Communication.Pipeline import CommunicationPipeline
from MesonPy.FrontalController import FrontendFrontalController

from MesonPy.Communication.IncomingHandler.OperationRouter import FrontendOperationReturnRouter
from MesonPy.Communication.OutcomingHandler.OperationRouter import FrontendOperationRouter

from MesonPy.Communication.OutcomingHandler.FormatRouter import OutcomingJSONRouter
from MesonPy.Communication.IncomingHandler.FormatRouter import IncomingJSONRouter

logger = logging.getLogger(__name__)

class FrontendApplication:
    def __init__(self):
        self.pipeline = None
        self.frontalController  = None

    def onOpenningPipeline(self, pipeline):
        self.pipeline = pipeline

        handshake = yield from pipeline.websocket.recv()

        if handshake == 'handshake':
            logger.info('Received hanshake from server.')
        else:
            raise Exception('Wrong handshake message...')

        # Answer back, we want to exchange in json-formatted messages
        yield from pipeline.websocket.send('json')

        # Let's build the Frontal Controller
        incomingPipeline = pipeline.getIncomingPipeline()
        inRoot = incomingPipeline.getRootHandler()
        incomingFormatRouter = IncomingJSONRouter(inRoot)
        operationReturnRouter = FrontendOperationReturnRouter(incomingFormatRouter)
        #
        outcomingPipeline = pipeline.getOutcomingPipeline()
        outRoot = outcomingPipeline.getRootHandler()
        outcomingFormatRouter = OutcomingJSONRouter(outRoot)
        operationRouter = FrontendOperationRouter(outcomingFormatRouter)

        self.frontalController = FrontendFrontalController(operationReturnRouter, operationRouter)
        logger.info('Frontal controller initialized!')

    def onClosingPipeline(self, pipeline):
        pass

    def rpc(self, name, args=None):
        logger.debug('RPC name=%s, args=%s', name, args)
        if self.frontalController is None:
            raise Exception('Cannot make RPC because Frontal Controller is not initialized!')
        instructionCtx = InstructionContext('RPC', {'method': name, 'args': args})
        futureInstruction = asyncio.ensure_future(self.frontalController.executeInstruction(instructionCtx))
        asyncio.get_event_loop().run_until_complete(futureInstruction)
        return futureInstruction.result()

    @asyncio.coroutine
    def handler(self, pipelineOpening, addr, port):
        uri = 'ws://{}:{}'.format(addr, port)
        logger.info('Connecting to %s', uri)

        try:
            websocket = yield from websockets.connect(uri)
        except ConnectionRefusedError as e:
            logger.error('Cannot establish connection with the backend, addr=%s', uri)
            pipelineOpening.set_exception(Exception('Backend is unavailable'))
            return

        pipeline = CommunicationPipeline(websocket)

        try:
            yield from self.onOpenningPipeline(pipeline)
            logger.info('Pipeline initialized.')
            pipelineOpening.set_result(pipeline)
            yield from pipeline.run()

        except Exception as e:
            logger.error(e)

        finally:
            logger.info('Disconnection %s', websocket)
            pipeline.close()

    def start(self, addr="127.0.0.1", port="4242"):
        pipelineOpening = asyncio.Future()
        future = asyncio.ensure_future(self.handler(pipelineOpening, addr, port))

        asyncio.get_event_loop().run_until_complete(pipelineOpening)

        pipelineOpening.result()
        logger.info('Backend is avalailable!')

    def exit(self):
        if self.pipeline is not None:
            self.pipeline.close()
        asyncio.get_event_loop().run_until_complete(asyncio.ensure_future(self.pipeline.wait_close()))
