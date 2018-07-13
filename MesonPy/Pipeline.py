import binascii
import asyncio
import functools

from Cryptodome.Cipher import AES
from MesonPy.AESCipher import encrypt, decrypt

import inspect
import logging
logger = logging.getLogger(__name__)

class PipelineBuilder:
    def __init__(self, pipeline):
        self._chain = [pipeline]

    def add(self, pipeline):
        self._chain.append(pipeline)
        return self
    
    def getChain(self):
        return self._chain

    def build(self, parent=None):
        for pipeline in self.getChain():
            if parent is not None:pipeline.setParent(parent)
            parent = pipeline
        return self.getChain()[0]

class PipelineInterception:
    def __init__(self, value):
        self.value = value
        self._continue = True
    
    def shouldContinue(self):
        return self._continue
    
    def stopPropagation(self):
        self._continue = False
    
    def set(self, value):
        self.value = value
    
    def get(self):
        return self.value

class IPipeline:
    def setParent(self, parent):
        pass
    def addChild(self, child):
        pass
    
    def onIncoming(self, interceptor):
        pass
    
    def onOutcoming(self, interceptor):
        pass
    
    def isOpened(self):
        pass
    
    """
        Function called when the socket is closed
    """
    def onClosed(self):
        pass
    
    def onOpened(self):
        pass
        
class BasePipeline:
    def __init__(self):
        self._childs = []
        self._parent = None
        self._isOpened = True
    
    def getParent(self):
        return self._parent
    
    def getChilds(self):
        return self._childs
    
    def setParent(self, parent):
        self._parent = parent
        parent.addChild(self)
        
    def addChild(self, child):
        self._childs.append(child)

    def onIncoming(self, interceptor):
        self.interceptIncoming(interceptor)
        if interceptor.shouldContinue():
            for child in self.getChilds():
                child.onIncoming(interceptor)
        else:
            logger.info('Pipeline propagation is stopped.')
    
    def onOutcoming(self, interceptor):
        self.interceptOutcoming(interceptor)
        if interceptor.shouldContinue() and self.getParent() is not None:
            self.getParent().onOutcoming(interceptor)

    def interceptIncoming(self, interceptor):
        pass
    
    def interceptOutcoming(self, interceptor):
        pass

    def interceptClose(self):
        pass

    def onClosed(self):
        self.interceptClose()
        for child in self.getChilds():
            child.onClosed()

class SecurityPipeline(BasePipeline):
    def __init__(self, bKey, bIV):
        BasePipeline.__init__(self)
        self._bKey  = bKey
        self._bIV   = bIV
    
    def createAES(self):
        aes = AES.new(self._bKey, AES.MODE_CBC, self._bIV)
        return aes
    
    def interceptIncoming(self, interceptor):
        try:
            oAES        = self.createAES()
            encodedMsg  =  binascii.a2b_hex(interceptor.get().strip())
            strDecoded  = decrypt(encodedMsg, oAES)
            interceptor.set(strDecoded)
        except binascii.Error:
            interceptor.stopPropagation()
            logger.warning('Received message is not in hex format: %s', interceptor.get())
    
    def interceptOutcoming(self, interceptor):
        oAES            = self.createAES()
        encoded         = encrypt(interceptor.get(), oAES)
        strHex_encoded  = binascii.b2a_hex(encoded).decode('utf8')
        interceptor.set(strHex_encoded)
    

class SerializerPipeline(BasePipeline):
    def __init__(self, protocol, serializerService):
        BasePipeline.__init__(self)
        self._protocol = protocol
        self._serializerService = serializerService
    
    def getSerializerService(self):
        return self._serializerService
    
    def getProtocol(self):
        return self._protocol
    
    def interceptIncoming(self, interceptor):
        interceptor.set(self.getSerializerService().deserialize(interceptor.get(), protocol=self.getProtocol()))
    
    def interceptOutcoming(self, interceptor):
        interceptor.set(self.getSerializerService().serialize(interceptor.get(), protocol=self.getProtocol()))


class NormalizerPipeline(BasePipeline):
    def __init__(self, normalizerService):
        BasePipeline.__init__(self)
        self._normalizerService = normalizerService
    
    def getNormalizerService(self):
        return self._normalizerService
    
    def interceptIncoming(self, interceptor):
        interceptor.set(self.getNormalizerService().denormalize(interceptor.get()))
    
    def interceptOutcoming(self, interceptor):
        interceptor.set(self.getNormalizerService().normalize(interceptor.get()))

class SessionPipeline(BasePipeline):
    def __init__(self, sessionManager):
        BasePipeline.__init__(self)
        self._sessionManager = sessionManager
        self._session        = self.getSessionManager().new()
    
    def getSessionManager(self):
        return self._sessionManager

    def getSession(self):
        return self._session
    
    def interceptIncoming(self, interceptor):
        interceptor.set((self.getSession(), interceptor.get()))     
    
    def interceptClose(self):
        self.getSessionManager().remove(self.getSession())

class BackendRPCException(Exception):
    def __init__(self, message, backendStackFrame=None):
        Exception.__init__(self, message)
        self._backendStackFrame = backendStackFrame
    
    def getBackendStack(self):
        return self._backendStackFrame
class FrontendRPCPipeline(BasePipeline):
    def __init__(self, oRefFrontendRPCService):
        BasePipeline.__init__(self)
        self._ticketCounter = 0
        self._currentFutures = {}
        oRefFrontendRPCService.setPipeline(self)       
    
    def createTicket(self):
        self._ticketCounter += 1
        return self._ticketCounter
    
    def getCurrentFutures(self):
        return self._currentFutures
    
    def getCurrentFuture(self, ticketId):
        if ticketId not in self.getCurrentFutures():
            return None
        else:
            return self.getCurrentFutures()[ticketId]
    
    def interceptIncoming(self, interceptor):
        normalizeData = interceptor.get()

        if '__operation__' in normalizeData and normalizeData['__operation__'] == 'RPC':
            interceptor.stopPropagation()
            ticketId = normalizeData['__ticket__']
            error    = normalizeData['__error__'] if '__error__' in normalizeData else None
            ret      = normalizeData['__return__'] if '__return__' in normalizeData else None        
            future   = self.getCurrentFuture(ticketId)
            
            if future is None:
                logger.warning('An answer to an unknown RPC has been received: %s', ticketId)
                return
            else:
                logger.info('Received return of the RPC request #%s', ticketId)
            
            if error is not None:    
               error = BackendRPCException(error['message'], error['stack'] if 'stack' in error else None)
               future.set_exception(error)
            else:
                future.set_result(ret)

    def remove(self, ticketId, fn):
        del self._currentFutures[ticketId]
    
    def request(self, methodName, args):
        ticketId = self.createTicket()
        self._currentFutures[ticketId] = asyncio.Future()
        self._currentFutures[ticketId].add_done_callback(functools.partial(self.remove, ticketId))

        request = {
            '__ticket__': ticketId,
            '__operation__': 'RPC',
            '__payload__': {
                'method': methodName,
                'args': args
            }
        }

        logger.info('Sending RPC request #%s to execute %s', ticketId, methodName)

        interceptor = PipelineInterception(request)
        self.onOutcoming(interceptor) # Send it 
        
        return self._currentFutures[ticketId]
    
    def onClosed(self):
        for ticketId, future in self.getCurrentFutures().items():
            logger.warning('Cancelling the execution of RPC #%s', ticketId)
            future.cancel()

class BackendRPCPipeline(BasePipeline):
    def __init__(self, rpcHandler):
        BasePipeline.__init__(self)
        self._rpcHandler    = rpcHandler
        self._runningTasks  = {}
    
    def getRPCHandler(self):
        return self._rpcHandler
    
    def onSuccess(self, methodName, mixedResult, ticket, fn):
        normalizedData = {
            "__ticket__": ticket,
            "__operation__": 'RPC',
            "__return__": mixedResult,
            "__error__": None
        }    
        interceptor = PipelineInterception(normalizedData)
        self.onOutcoming(interceptor) # Send it back
    
    def onFailed(self, methodName, oException, ticket, fn):
        stack = [inspect.getframeinfo(frame) for frame in fn.get_stack()]
        stack = [dict(frame._asdict()) for frame in stack]
        
        normalizedData = {
            "__ticket__": ticket,
            "__operation__": 'RPC',
            "__return__": None,
            "__error__": {
                'stack': stack,
                'message': str(oException),
                'instance': oException
            }
        }

        logger.error('RPC %s has failed because: %s', methodName, oException)
        logger.exception(oException)

        interceptor = PipelineInterception(normalizedData)
        self.onOutcoming(interceptor) # Send it back  
    
    """
        Handle and send the result of the RPC process task
    """
    def sendResult(self, methodName, ticket, fn):
        try:
            result = fn.result()
            self.onSuccess(methodName, result, ticket, fn)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.onFailed(methodName, e, ticket, fn)     
        finally:
            self.removeTask(ticket)
    
    """
        Remove current task from the catalog
    """
    def removeTask(self, ticket):
        del self._runningTasks[ticket]

    """
        Cancel current RPC process tasks
    """
    def cancelTasks(self):
        for ticket, task in self._runningTasks:
            task.cancel()
    
    
    """
        Attach RPC process task within the pipeline
    """
    def attachProcessTask(self, methodName, ticket, task):
       callback = functools.partial(self.sendResult, methodName, ticket) # Send Result
       task.add_done_callback(callback)
       self._runningTasks[ticket] = task

    def interceptIncoming(self, interceptor):
        session, recvMsg = interceptor.get()    
        logger.info('Intercept message')
        if '__operation__' in recvMsg and '__ticket__' in recvMsg:
            ticket = recvMsg['__ticket__']
            if recvMsg['__operation__'] == 'RPC' and '__payload__' in recvMsg:
                interceptor.stopPropagation()
                payload    = recvMsg['__payload__']
                methodName = payload['method']
                args       = payload['kargs'] if 'kargs' in payload else (payload['args'] if 'args' in payload else [])
                task        = self.getRPCHandler().handle(methodName, args, session)
                self.attachProcessTask(methodName, ticket, task)
            # RPC heartbeat
            if recvMsg['__operation__'] == 'RPC_HEARTBEAT':
                logger.info('RPC heartbeat request for "{}"'.format(ticket))
                if ticket not in self._runningTasks:
                    logger.warning('No RPC is running as "{}"'.format(ticket))
                    interceptor = PipelineInterception({
                        '__operation__': 'RPC_HEARTBEAT',
                        '__ticket__': ticket,
                        '__status__': 'out'
                    })
                    self.onOutcoming(interceptor) # Send it back
                else:
                    logger.warning('A RPC is still running as "{}"'.format(ticket))
                    interceptor = PipelineInterception({
                        '__operation__': 'RPC_HEARTBEAT',
                        '__ticket__': ticket,
                        '__status__': 'still'
                    })
                    self.onOutcoming(interceptor) # Send it back
    def interceptClose(self):
        self.cancelTasks()

class BackendPubSub(BasePipeline):
    def __init__(self, localPubSubService):
        pass

class PipelineEntry(BasePipeline):
    def __init__(self, connectionHandler):
        BasePipeline.__init__(self)
        self._connectionHandler = connectionHandler
    
    def getConnectionHandler(self):
        return self._connectionHandler
    
    def interceptOutcoming(self, interceptor):
        strMessage = interceptor.get()
        interceptor.stopPropagation()
        self.send(strMessage)

    def send(self, rawMessage):
        self.getConnectionHandler().send(rawMessage)