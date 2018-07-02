import asyncio
import functools
import websockets
import logging

logger = logging.getLogger(__name__)
from MesonPy.Pipeline import PipelineInterception, PipelineEntry     

class ConnectionHandler:
    def __init__(self, socketHandler):
        self._rootPipeline              = PipelineEntry(self)
        self._socketHandler             = socketHandler
        
        self._runTask                   = asyncio.ensure_future(self.run())
        self._runTask.add_done_callback(self.analyzeRunResult)

        self._connectionLostCallbacks   = []
        self._currentMessageTries       = {}
        self._sendMessageCounter        = 0

    def getRunTask(self):
        return self._runTask

    def getSendTicket(self):
        self._sendMessageCounter += 1
        self._currentMessageTries[self._sendMessageCounter] = 0
        return self._sendMessageCounter
    
    def hasExpiredTries(self, ticketId):
        return self._currentMessageTries[ticketId] > 3

    def getRootPipeline(self):
        return self._rootPipeline

    def getSocketHandler(self):
        return self._socketHandler
    
    def close(self, reason="Unknown reason"):
        asyncio.ensure_future(self.getSocketHandler().close()).add_done_callback(lambda fn: logger.info('Websocket is closed.'))
        self.connectionClosed(reason)
        self.getRunTask().cancel()
        logger.info('Closing because: %s', reason)

    def onConnectionLost(self, callback):
        self._connectionLostCallbacks.append(callback)

    def connectionClosed(self, reason="Unknown reason"):
        self.getRootPipeline().onClosed()

        for callback in self._connectionLostCallbacks:
            callback(self, reason)

    @asyncio.coroutine
    def processMessage(self, message):
        pipelineInterceptor = PipelineInterception(message)
        logger.debug('Sending message to the pipeline')
        self.getRootPipeline().onIncoming(pipelineInterceptor)
    
    @asyncio.coroutine
    def processSend(self, ticketId, message):
        logger.debug('Sending message, ticket is %s', ticketId)
        yield from self.getSocketHandler().send(message)      
        logger.debug('Sent message, ticket is %s', ticketId)
   
    """
        Send back the message, will create a ticket to track if it has been sent or failed a number of 
        time
    """
    def send(self, message, ticketId=None):
        ticketId = self.getSendTicket() if ticketId is None else ticketId
        
        if self.hasExpiredTries(ticketId):
            logger.error('Expired tries to send message n°%s', ticketId)
            return

        sendTask = asyncio.ensure_future(self.processSend(ticketId, message))
        callback = functools.partial(self.analyzeSentProcessResult, ticketId, message)
        sendTask.add_done_callback(callback)

    def analyzeRunResult(self, fn):
        try:
            fn.result()
        except asyncio.CancelledError:
            logger.info('The connection task had been stopped.')
        except Exception as e:
            logger.exception('Unhandle exception has occured while running: %s', e)
    
    def analyzeSentProcessResult(self, ticketId, message, fn):
        try:
            fn.result()
            del self._currentMessageTries[ticketId] # Don't need it
        except websockets.exceptions.ConnectionClosed as e:
             self.connectionClosed(str(e))
        except asyncio.TimeoutError:
            self.send(message) # Reschedule
            logger.debug('Timeout for sending message %s, will reschedule it.', ticketId)
        except Exception as e:
            logger.exception('Unhandle exception has occured while sending message: %s', e)

    def analyzeMessageProcessResult(self, message, fn):
        try:
            fn.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception('Unhandle exception has occured while processing message: %s', e)

    @asyncio.coroutine
    def run(self):
        while True:
            try:
                msg = yield from asyncio.wait_for(self.getSocketHandler().recv(), timeout=10)
                logger.debug('Received message')
                msgHandlingTask = asyncio.ensure_future(self.processMessage(msg))
                msgHandlingTask.add_done_callback(functools.partial(self.analyzeMessageProcessResult, msg))
            
            except websockets.exceptions.ConnectionClosed as e:
                self.connectionClosed(str(e))
                return
            
            except asyncio.TimeoutError:
                try:
                    pong_waiter = yield from self.getSocketHandler().ping()
                    yield from asyncio.wait_for(pong_waiter, timeout=10)
                except asyncio.TimeoutError:
                    self.connectionClosed('Timeout from the client.')
                    return

