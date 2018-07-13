from MesonPy.FrontendApplication import FrontendApplication
from MesonPy.BackendApplication import BackendApplication

import asyncio
import logging
import signal
import sys
logger = logging.getLogger('TEST')
logging.getLogger().setLevel(logging.DEBUG)

from MesonPy.Constants import SERVICE_RPC, SERVICE_CONTROLLER

class MyFooController:
    @asyncio.coroutine
    def actionbar(self, instanceContext):
        logger.info('Action!')
        raise Exception('Oops')

@asyncio.coroutine
def run_two(frontRunTask, backRunTask):
    yield from backRunTask
    yield from frontRunTask   

@asyncio.coroutine
def async_run_test(frontendApp):
    logger.info('Running test case.')
    bar = frontendApp.getContext().getSharedService(SERVICE_RPC).rpc('com.rpc.controllers.MyFoo.bar', timeout=10)
    try:
        yield from bar()
    except Exception as e:
        logger.error(e)
    logger.info('Done')
    frontendApp.exit()

def run_test(frontendApp):
    asyncio.ensure_future(async_run_test(frontendApp))

def clear_test(back):
    asyncio.get_event_loop().stop()

def assert_controller_map(controllerMap):
    if 'MyFoo' not in controllerMap:
        raise Exception('My Foo is not available')
    if 'bar' not in controllerMap['MyFoo']:
        raise Exception('bar action is not in MyFoo controller')

def init_test(frontendApp, backendApp):
    logger.info('Init test case...')
    
    serviceController = backendApp.getContext().getSharedService(SERVICE_CONTROLLER)
    serviceController.add(MyFooController())
    controllerMap = serviceController.getMap()

    assert_controller_map(controllerMap)
    
    frontendApp.onConnected(lambda front: run_test(front))
    backendApp.onExited(lambda back: clear_test(back))
    
def test():
    front = FrontendApplication('meson_py.test')
    back  = BackendApplication('meson_py.test', singleClientMode=True)

    frontTask = front.init(False)
    backTask  = back.init(False)

    init_test(front, back)

    runTask   = asyncio.ensure_future(run_two(frontTask, backTask))

    signal.signal(signal.SIGINT, lambda: runTask.cancel())
    signal.signal(signal.SIGTERM, lambda: runTask.cancel())
    
    asyncio.get_event_loop().run_until_complete(runTask)
    asyncio.get_event_loop().run_forever()

if __name__ == '__main__':
    test()