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
from MesonPy.AESCipher import encrypt

class IConnectionStrategy:
    def newConnection(self, socketHandler):
        pass
    
    def closedConnection(self):
        pass
        
from MesonPy.Pipeline import SessionPipeline
class SessionStrategy(IConnectionStrategy):
    def __init__(self, oRefSessionManager):
        self._oRefSessionManager = oRefSessionManager
    
    def getSessionManager(self):
        return self._oRefSessionManager

    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        pipelineBuilder.add(SessionPipeline(self.getSessionManager()))
        return True

from MesonPy.Pipeline import NormalizerPipeline
class NormalizerStrategy(IConnectionStrategy):
    def __init__(self, normalizerService):
        self._normalizeService = normalizerService
    
    def getNormalizerService(self):
        return self._normalizeService
    
    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        pipelineBuilder.add(NormalizerPipeline(self.getNormalizerService()))
        return True

from MesonPy.Pipeline import FrontendRPCPipeline
class FrontendRPCPipeline(IConnectionStrategy):
    def __init__(self, oRefFrontendRPCHandler):
        self._oRefFrontendRPCHandler = oRefFrontendRPCHandler
    
    def getFrontendRPCHandler(self):
        return self._oRefFrontendRPCHandler
    
    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        pipelineBuilder.add(BackendRPCPipeline(self.getBackendRPCHandler()))
        return True      
from MesonPy.Pipeline import BackendRPCPipeline
class BackendRPCStrategy(IConnectionStrategy):
    def __init__(self, oRefBackendRPCHandler):
        self._oRefBackendRPCHandler = oRefBackendRPCHandler
    
    def getBackendRPCHandler(self):
        return self._oRefBackendRPCHandler

    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        pipelineBuilder.add(BackendRPCPipeline(self.getBackendRPCHandler()))
        return True
    
    @asyncio.coroutine
    def closedConnection(self, socketHandler):
        pass

from MesonPy.Pipeline import SerializerPipeline
class SerializerStrategy:
    def __init__(self, serializerService):
       self._serializerService = serializerService

    def getSerializerService(self):
        return self._serializerService

    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        pipelineBuilder.add(SerializerPipeline('json', self.getSerializerService()))
        return True
    
    @asyncio.coroutine
    def closedConnection(self, socketHandler):
        pass
 
from MesonPy.Pipeline import SecurityPipeline
class SecuredFrontendConnectionStrategy:
    def __init__(self, appId, serverSecret, clientSecret):
        self.clientSecret           = clientSecret
        self.serverSecret           = serverSecret 
        self.appId                  = appId
    
    def getAppID(self):
        return self.appId
    
    def getClientSecret(self):
        return self.clientSecret

    def getServerSecret(self):
        return self.serverSecret
    
    def createNonce(self):
        return os.urandom(16)
    
    def getLogger(self):
        return logging.getLogger('MesonPy.Frontend.Security')

    @asyncio.coroutine
    def getServerNonce(self, socketHandler):
        bSalt = yield from socketHandler.recv()
        self.getLogger().debug('Received nonce from backend %s', bSalt)
        return bSalt
    
    @asyncio.coroutine
    def sendClientRequest(self, socketHandler, bSalt):
        clientKEY           = hashlib.pbkdf2_hmac('sha1', self.getClientSecret().encode('utf-8'), bSalt, 1000, dklen=32)
        bIV                 = self.createNonce()
        clientAES           = AES.new(clientKEY, AES.MODE_CBC, bIV)

        requestToken       = {
            'id': self.getAppID()
        }
        jsonRequestToken   = json.dumps(requestToken)
        bEncodedReplyToken = binascii.b2a_hex(encrypt(jsonRequestToken, clientAES)).decode('utf8')
        bEncodedIV         = binascii.b2a_hex(bIV).decode('utf8')
        request            = 'REQUEST {} WITH {}'.format(bEncodedReplyToken, bEncodedIV)

        self.getLogger().debug('Sending request %s', request)

        yield from socketHandler.send(request)
    
    @asyncio.coroutine
    def getSessionKeyAndIV(self, socketHandler, bSalt):
        self.getLogger().debug('Waiting for reply')
        
        reply = yield from asyncio.wait_for(socketHandler.recv(), timeout=10)
        
        yield from socketHandler.send('OK')
        
        self.getLogger().debug('Received reply %s', reply)
        
        m        = re.search('REPLY (?P<encoded>.*) WITH (?P<iv>.*)', reply)
        
        if m is None: return None
        
        bEncodedToken      = binascii.a2b_hex(m.group(1))
        bServerIV          = binascii.a2b_hex(m.group(2))

        serverKey          = hashlib.pbkdf2_hmac('sha1', self.getServerSecret().encode('utf-8'), bSalt, 1000, dklen=32)
        serverAES          = AES.new(serverKey, AES.MODE_CBC, bServerIV)
        
        strDecryptedToken  = re.search('({.*})', serverAES.decrypt(bEncodedToken).decode('utf-8').strip()).group(1)
        serverToken        = json.loads(strDecryptedToken)

        sessionKey = binascii.a2b_hex(serverToken['key'])
        sessionIV  = binascii.a2b_hex(serverToken['iv'])

        return sessionKey, sessionIV
    
    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        # Create and send a public nonce
        bSalt = yield from self.getServerNonce(socketHandler)
        # Send our request
        yield from self.sendClientRequest(socketHandler, bSalt)
        # Wait for the backend replu
        result = yield from self.getSessionKeyAndIV(socketHandler, bSalt)
        # The result is invalid
        if result is None: return False
        # We get our sessions keys
        bSessionKey, bSessionIV = result
        # Build the security layer of the pipeline
        self.getLogger().info('Security layer is set.')
        pipelineBuilder.add(SecurityPipeline(bSessionKey, bSessionIV))
        return True
    
    @asyncio.coroutine
    def closedConnection(self, socketHandler):
        pass     
class SecuredBackendConnectionStrategy:
    def __init__(self, serverSecret, clientSecret):
        self.clientSecret           = clientSecret
        self.serverSecret           = serverSecret 
    
    def getClientSecret(self):
        return self.clientSecret

    def getServerSecret(self):
        return self.serverSecret

    def createNonce(self):
        return os.urandom(16)
    
    @asyncio.coroutine
    def sendNonce(self, socketHandler, nonce):
        yield from socketHandler.send(nonce)

    def getLogger(self):
        return logging.getLogger('MesonPy.Backend.Security')

    # Get the APP REQUEST from the client, encrypted with 256 bits AES key built on a PBKDF2 of the client secret
    # REQUEST [Encrypted Token] WITH [IV]
    @asyncio.coroutine
    def getEncryptedClientRequest(self, socketHandler):
        request = yield from asyncio.wait_for(socketHandler.recv(), timeout=5)
        self.getLogger().debug('Received request: %s', request)
        m       = re.search('REQUEST (?P<encoded>.*) WITH (?P<iv>.*)', request)
        if m is None:
            return None
        
        encodedToken    = binascii.a2b_hex(m.group(1))
        iv              = binascii.a2b_hex(m.group(2))

        return encodedToken, iv

    def validateClientRequest(self, bEncodedToken, bIV, bSalt):
        clientKEY       = hashlib.pbkdf2_hmac('sha1', self.getClientSecret().encode('utf-8'), bSalt, 1000, dklen=32)
        clientAES       = AES.new(clientKEY, AES.MODE_CBC, bIV)

        decryptedToken  = re.search('({.*})', clientAES.decrypt(bEncodedToken).decode('utf-8').strip()).group(1)
        dictToken       = json.loads(decryptedToken)
    
    def createSessionKeys(self, bSalt):
        # Generate a random AES key of 256 bits
        session_randomKey   = hashlib.pbkdf2_hmac('sha1', os.urandom(32), bSalt, 1000, dklen=32)
        session_randomIV    = self.createNonce()
        session_randomAES   = AES.new(session_randomKey, AES.MODE_CBC, session_randomIV)       

        return session_randomKey, session_randomIV, session_randomAES 
    
    @asyncio.coroutine
    def sendSessionKeyAndIV(self, socketHandler, sessionKey, sessionIV, bSalt):
        serverKEY           = hashlib.pbkdf2_hmac('sha1', self.getServerSecret().encode('utf-8'), bSalt, 1000, dklen=32)
        serverIV            = self.createNonce()
        serverAES           = AES.new(serverKEY, AES.MODE_CBC, serverIV)
        
        dictReplyObj            = {
            'key': binascii.b2a_hex(sessionKey).decode('utf8'), 
            'alg': 'AES_256', 
            'iv': binascii.b2a_hex(sessionIV).decode('utf8')
        }

        strReplyToken          = json.dumps(dictReplyObj)
        bEncodedReplyToken     = binascii.b2a_hex(encrypt(strReplyToken, serverAES)).decode('utf8')
        
        reply = 'REPLY {} WITH {}'.format(
                bEncodedReplyToken, 
                binascii.b2a_hex(serverIV).decode('utf8')
        )
        
        self.getLogger().debug('Sending reply %s', reply)
        yield from socketHandler.send(reply)
        self.getLogger().debug('Reply sent!')

        # Confirm the reception
        try:
            yield from asyncio.wait_for(socketHandler.recv(), timeout=3)
        except asyncio.TimeoutError:
            yield from socketHandler.send(reply)

    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        # Create and send a public nonce
        bSalt = self.createNonce()
        yield from self.sendNonce(socketHandler, bSalt)
        
        result = yield from self.getEncryptedClientRequest(socketHandler)
        
        if result is None:
            return False

        bEncodedToken, bIV = result
        isValid = self.validateClientRequest(bEncodedToken, bIV, bSalt)
        
        if isValid is False: return False
        
        bSessionKey, bSessionIV, oSessionAES = self.createSessionKeys(bSalt)
        
        yield from self.sendSessionKeyAndIV(socketHandler, bSessionKey, bSessionIV, bSalt)
        
        self.getLogger().info('Security layer is set.')
        pipelineBuilder.add(SecurityPipeline(bSessionKey, bSessionIV))
        
        return True
    
    @asyncio.coroutine
    def closedConnection(self, socketHandler):
        pass

class AggregatedConnectionStrategy(IConnectionStrategy):
    def __init__(self):
        self._stack = []

    def stack(self, oConnStrategy):
        self._stack.append(oConnStrategy)
        return self
    
    def getStack(self):
        return self._stack

    def getLogger(self):
        return logging.getLogger('MesonPy.Connection.Strategy')

    @asyncio.coroutine
    def newConnection(self, socketHandler, pipelineBuilder):
        for connStrat in self.getStack():
            self.getLogger().debug('Calling connection strategy: %s', connStrat.__class__.__name__)
            keep = yield from connStrat.newConnection(socketHandler, pipelineBuilder)
            if not keep: 
                self.getLogger().warning('Connection strategy "%s" has refused the current connection.', connStrat.__class__.__name__)
                return False
            self.getLogger().debug('Connection strategy "%s" has validated the current connection.', connStrat.__class__.__name__)
        return True

    def closedConnection(self, socketHandler):
        for connStrat in self.getStack():
            connStrat.closedConnection(socketHandler)
