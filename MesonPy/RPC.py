import inspect
import functools
import asyncio
import logging

class FrontendRPCService:
    def __init__(self, oRefFrontendRPCPipeline):
        self._oRefFrontendRPCPipeline = None

    def setPipeline(self, oRefFrontendRPCPipeline):
        self._oRefFrontendRPCPipeline = oRefFrontendRPCPipeline
    
    def getLogger(self):
        return logging.getLogger('MesonPy.Frontend.RPC')

    def getPipeline(self):
        if self._oRefFrontendRPCPipeline is None:
            raise Exception('RPC is currently no possible because the pipeline had not been set.')
        
        return self._oRefFrontendRPCPipeline
    
    def isAvailable(self):
        return self._oRefFrontendRPCPipeline is not None

    def analyzeRPCResponse(self, name, fn):
        try:
            fn.result()
        except asyncio.TimeoutError:
            self.getLogger().warning('Timeout of RPC %s.', name)
        except Exception as e:
            self.getLogger().error(e)

    def rpc(self, name, timeout=None):
        def wrapper(*args):
            self.getLogger().debug('Request the execution of RPC %s', name)
            result = self.getPipeline().request(name, args)
            if timeout is not None:
                callback = functools.partial(self.analyzeRPCResponse, name)
                fn = asyncio.ensure_future(asyncio.wait_for(result, timeout))
                fn.add_done_callback(callback)
                return fn
            else:
                return result
        return wrapper 

class BackendRPCService:
    def __init__(self, app):
        self._rpc = {}
    
    @asyncio.coroutine
    def wrap(self, method):
        ret = yield from method()
        self.getLogger().info(ret)
        return ret
    
    def getLogger(self):
        return logging.getLogger('MesonPy.Backend.RPC')

    def handle(self, name, args, session):
        self.getLogger().info('Schedule execution of RPC %s for %s', name, session.id)
        method           = self.getRPC(name)
        executableMethod = self.injectArgs(session, method, args)
        return asyncio.ensure_future(self.wrap(executableMethod))
    
    def getRPC(self, name):
        return self._rpc[name]

    def register(self, name, method):
        self._rpc[name] = method

    def injectArgs(self, session, method, args):
        if type(args) is dict:
            method = functools.partial(method, **args)
        elif type(args) is list:
            method = functools.partial(method, *args)

        argspecs = inspect.getfullargspec(method)

        # Inject execution context
        if '__session__' in argspecs.args or '__session__' in argspecs.kwonlyargs:
            method = functools.partial(method, __session__=session)

        return method