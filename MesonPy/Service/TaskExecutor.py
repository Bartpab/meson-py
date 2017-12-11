import asyncio
import concurrent.futures
from functools import partial

def NonBlockingTask(f):
    @asyncio.coroutine
    def wrapper(*args, **kargs):
        if 'instanceContext' in kargs:
            executor = kargs['instanceContext'].getSharedService('services.shared.TaskExecutor').getExecutor()
        else:
            executor = None

        loop    = asyncio.get_event_loop()
        kf      = partial(f, *args, **kargs)
        ret     = yield from loop.run_in_executor(executor, kf)
        return ret
    wrapper.__name__ = f.__name__
    return wrapper


class TaskExecutor:
    def __init__(self, appContext):
        self.appContext = appContext
        self.executor = concurrent.futures.ThreadPoolExecutor(None)

    def getExecutor(self):
        return self.executor
