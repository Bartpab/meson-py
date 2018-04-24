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
        self.getSocketHandler().close()
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
        self.getRootPipeline().onIncoming(pipelineInterceptor)
    
    @asyncio.coroutine
    def processSend(self, message):
        yield from asyncio.wait_for(self.getSocketHandler().send(message), timeout=30)       

    """
        Send back the message, will create a ticket to track if it has been sent or failed a number of 
        time
    """
    def send(self, message, ticketId=None):
        messageTicket = self.getSendTicket() if id is None else ticketId
        
        if self.hasExpiredTries(ticketId):
            logger.error('Expired tries to send message n°%s', ticketId)
            return
        
        sendTask = asyncio.ensure_future(functools.partial(self.processSend, message))
        callback = functools.partial(self.analyzeSentProcessResult, messageTicket, message)
        sendTask.add_done_callback(callback)

    def analyzeRunResult(self, fn):
        try:
            fn.result()
        except asyncio.CancelledError:
            logger.info('The run task of this connection handler had been stopped.')
        except Exception as e:
            logger.exception('Unhandle exception has occured while running: %s', e)
    
    def analyzeSentProcessResult(self, id, message, fn):
        try:
            fn.result()
            del self._sendMessageCounter[id] # Don't need it
        except websockets.exceptions.ConnectionClosed as e:
             self.connectionClosed(str(e))
        except asyncio.TimeoutError:
            self.send(message) # Reschedule
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

