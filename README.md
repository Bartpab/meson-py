# MesonPY
## Backend Side (Py)
```python
from MesonPy.BackendApplication import BackendApplication
from MesonPy import Constants

import controllers
import services.local as localServices
import services.shared as sharedServices

if __name__ == '__main__':
    # Init the backend application service
    app = BackendApplication(id='[APP ID]', server_secret='XXXX', client_secret='YYYY')

    # The RPC is a low-level service that will serve function to clients.
    # rpcService = app.getSharedService('com.rpc')

    # By using __session__ as a karg, the application will automatically inject the session
    # of the client who's calling the method
    # rpcService.register('hello', lambda __session__: print('hello from {}'.format(__session__.id)))
    # rpcService.register('add2', lambda x, y: x + y)

    # The service injector will inject local services to each instance,
    # and give access to shared services across the application
    serviceInjector = app.getSharedService(Constants.SERVICE_SERVICE_INJECTOR)

    # Define our to-be-injected local services, each local service get its instance context
    logger.info('Searching for local services in {}'.format(localServices.__name__))
    serviceInjector.addLocalServiceClasses(
        localServices
    )
    # Define our shared services, each shared service get its application context
    logger.info('Searching for shared services in {}'.format(sharedServices.__name__))
    serviceInjector.addSharedServiceClasses(
        sharedServices
    )
    # Load controllers
    # Controllers are built on top of RPC services to provide more
    # functionality and more context persistency accross the application.
    # Sessions are wrapped within instance contexts. Each instance context holds its local
    # memory pool, its local services and have access to a shared memory pool and services.
    logger.info('Searching for controllers in {}'.format(controllers.__name__))
    app.loadControllers(controllers)

    # Serve our application
    app.run()
```
controllers/FooController.py
```python
import asyncio

class FooController:
    @asyncio.coroutine
    def actionBar(self, instanceContext):
    	instanceContext.emit('hello.world')
	localService = instanceContext.getLocalService('services.local.MyLocalService')
        var = localService.HelloWorld()
	return var

```
services/local/MyLocalService.py
```python
class MyLocalService:
    def __init__(self, instanceContext):
        self.instanceContext = instanceContext
	self.instanceContext.on('hello.world', self.log)
    def HelloWorld(self):
    	return 'Hello world!'
    def log(self):
    	print('Event!')
```
