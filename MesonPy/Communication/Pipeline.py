import asyncio
import logging
import websockets

from MesonPy.Communication.IncomingHandler.RootIncomingHandler import RootReceivedMessageHandler
from MesonPy.Communication.OutcomingHandler.RootOutcomingHandler import RootSendMessageHandler

logger = logging.getLogger(__name__)

class ReceivedMessagePipeline:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.rootHandler = RootReceivedMessageHandler()
        self.handlers = []

    def getRootHandler(self):
        return self.rootHandler

    @asyncio.coroutine
    def process(self):
        try:
            message = yield from self.pipeline.recv_message()
            self.getRootHandler().co.send(message)
        except Exception as e:
            return

class SendMessagePipeline:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.rootHandler = RootSendMessageHandler(self)

    def getRootHandler(self):
        return self.rootHandler

    def process(self, sendMsg):
        if type(sendMsg) is not str:
            raise Exception('Send message should be a string !')
        # Let the event loop to handle
        asyncio.ensure_future(self.pipeline.send(sendMsg))


class CommunicationPipeline:
    def __init__(self, websocket):
        self.sendQueue = asyncio.Queue()
        self.receivedQueue = asyncio.Queue()
        self._close = False
        self.websocket = websocket
        self.outcomingPipeline = SendMessagePipeline(self)
        self.incomingPipeline = ReceivedMessagePipeline(self)
        self.processIncomingMessageCo = self.process_co()
        self.wsClosingFuture = None

    def getIncomingPipeline(self):
        return self.incomingPipeline

    def getOutcomingPipeline(self):
        return self.outcomingPipeline

    @asyncio.coroutine
    def close_websocket(self):
        if self.websocket.state_name not in ('CLOSING', 'CLOSED'):
            yield from self.websocket.close()

    def abort(self):
        # Wait for closing
        yield from self.close_websocket()
        self._close = True

    def close(self):
        if self._close:
            return

        logger.info('Closing the pipeline of %s', self.websocket)
        self._close = True

        tasks = [self.consumer_task, self.producer_task, self.process_task]

        for task in tasks:
            task.cancel()

        # Wait for closing
        self.wsClosingFuture = asyncio.ensure_future(self.close_websocket())

    @asyncio.coroutine
    def recv_message(self):
        if self._close:
            raise Exception('The websocket is closed or closing')
        rcvMsg = yield from self.receivedQueue.get()
        return rcvMsg

    @asyncio.coroutine
    def send(self, sendMsg):
        yield from self.sendQueue.put(sendMsg)

    @asyncio.coroutine
    def consume(self):
        try:
            while not self._close:
                message = yield from self.websocket.recv()
                yield from self.receivedQueue.put(message)
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning('The websocket had been closed')
        finally:
            logger.info('Closing incoming pipeline of %s', self.websocket)
            self.close()

    @asyncio.coroutine
    def produce(self):
        try:
            while not self._close:
                if self.sendQueue is None:
                    break
                try:
                    message = yield from self.sendQueue.get()
                except Exception as e:
                    continue

                logger.debug('Sending %s to %s', message, self.websocket)

                try:
                    yield from asyncio.wait_for(self.websocket.send(message), 5)
                except asyncio.TimeoutError as e:
                    logger.warning('Time out on %s', message)

                logger.debug('Sent %s to %s', message, self.websocket)
        except Exception as e:
            logger.error(e)
            raise e
        finally:
            logger.info('Closing outcoming pipeline of %s', self.websocket)
            self.close()
    @asyncio.coroutine
    def process_co(self):
        try:
            while not self._close:
                yield from self.getIncomingPipeline().process()
        except Exception as e:
            logger.error(e)
            raise e
        finally:
            logger.info('Closing incoming message processor')

    @asyncio.coroutine
    def run(self):
        logger.info('Running communication pipeline for %s', self.websocket)
        try:
            self.consumer_task = asyncio.ensure_future(self.consume())
            self.producer_task = asyncio.ensure_future(self.produce())
            # Run a concurrent task to process our incoming messages
            self.process_task = asyncio.ensure_future(self.processIncomingMessageCo)
            # If at least one had finished, exit the pipeline
            done, pending = yield from asyncio.wait([self.consumer_task, self.producer_task, self.process_task], return_when=asyncio.FIRST_COMPLETED)
        finally:
            logger.info('Exiting communication pipeline for %s', self.websocket)

    @asyncio.coroutine
    def wait_close(self):
        tasks = [self.consumer_task, self.producer_task, self.process_task, self.wsClosingFuture]
        yield from asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)

    def __str__(self):
        return 'Communication Pipeline, addr={}, ws state={}'.format(self.websocket.remote_address, self.websocket.state_name)
