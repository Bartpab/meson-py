import logging
import re
import asyncio
import functools

import MesonPy.Constants as Constants
from MesonPy.ModuleExplorer import fetchClasses

logger = logging.getLogger(__name__)

def getControllers(controllerModule):
    controllers = fetchClasses(controllerModule, None, None, lambda obj: re.match("(.*?)Controller", obj.__name__))
    return controllers

class ControllerManager:
    def __init__(self, app):
        self._rpcService = app.getSharedService(Constants.SERVICE_RPC)
        self._app = app
        self._map = {}
    
    def getAppContext(self):
        return self._app

    def generateRPCName(self, controllerName, actionName):
        return 'com.rpc.controllers.{}.{}'.format(controllerName, actionName)

    def createRPC(self, app, controller, action):
        @asyncio.coroutine
        def wrapper(*args, __session__):
            instanceManager = app.getSharedService(Constants.SERVICE_INSTANCE)
            kargs = {}
            kargs['instanceContext'] = instanceManager.getBySession(__session__)
            controllerAction = functools.partial(action, *args, **kargs)
            ret = yield from controllerAction()
            return ret
        return wrapper

    def getMap(self):
        return self._map

    def load(self, module):
        controllers = getControllers(module)
        
        for controller in controllers:
            self.add(controller())

    def add(self, controller):
        m = re.search(r'(?P<name>\w+)Controller', controller.__class__.__name__)
        if m is not None:
            controllerName = m.group('name')
        else:
            logger.warning('Invalid controller name for {}'.format(controller.__class__.__name__))
            return

        logger.info('Found controller {}'.format(controllerName))
        
        self._map[controllerName] = {}

        methods = [getattr(controller, method) for method in dir(controller) if callable(getattr(controller, method))]

        actions = {}

        for method in methods:
            m = re.search(r'^action(?P<name>\w+)$', method.__name__)
            if m is not None:
                actions[m.group('name')] = method

        for name, action in actions.items():
            rpcName = self.generateRPCName(controllerName, name)
            logger.info('Serving action "{}" of controller "{}" as RPC "{}"'.format(name, controllerName, rpcName))
            self._map[controllerName][name] = rpcName
            rpc = self.createRPC(self.getAppContext(), controller, action)
            self.getAppContext().getSharedService(Constants.SERVICE_RPC).register(rpcName, rpc)
