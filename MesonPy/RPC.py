import inspect
import functools
import asyncio

class FrontendRPCService:
    def __init__(self, oRefFrontendRPCPipeline):
        self._oRefFrontendRPCPipeline = None

    def setPipeline(self, oRefFrontendRPCPipeline):
        self._oRefFrontendRPCPipeline = oRefFrontendRPCPipeline
    
    def getPipeline(self):
        if self._oRefFrontendRPCPipeline is None:
            raise Exception('RPC is currently no possible because the pipeline had not been set.')
        
        return self._oRefFrontendRPCPipeline
    
    def isAvailable(self):
        return self._oRefFrontendRPCPipeline is not None

    def rpc(self, name):
        @asyncio.coroutine
        def wrapper(*args):
            result = self.getPipeline().request(name, args)
            return result
        return wrapper 

class BackendRPCService:
    def __init__(self, app):
        self._rpc = {}
    
    @asyncio.coroutine
    def wrap(self, method):
        ret = yield method
        return ret
    
    def schedule(self, name, args, session):
        method = self.getRPC(name)
        return asyncio.get_event_loop().ensure_future(functools.partial(self.wrap, self.injectArgs(session, method, args)))
    
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