from MesonPy.FrontendApplication import FrontendApplication
from MesonPy.BackendApplication import BackendApplication

import asyncio
import logging
import signal
import sys
logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s\t - %(levelname)s- %(message)s')
ch.setFormatter(formatter)
logging.getLogger().addHandler(ch)

@asyncio.coroutine
def run_two(frontRunTask, backRunTask):
    yield from backRunTask
    yield from frontRunTask   

def test():
    front = FrontendApplication('meson_py.test')
    front.onConnected(lambda front: print('Hello !'))
    back  = BackendApplication('meson_py.test')

    frontTask = front.init(False)
    backTask  = back.init(False)
    runTask   = asyncio.ensure_future(run_two(frontTask, backTask))

    signal.signal(signal.SIGINT, lambda: runTask.cancel())
    signal.signal(signal.SIGTERM, lambda: runTask.cancel())
    
    asyncio.get_event_loop().run_until_complete(runTask)
    
    asyncio.get_event_loop().run_forever()
if __name__ == '__main__':
    test()