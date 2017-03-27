# MesonPY
## Backend Side (Py)
```python
from MesonPy.BackendApplication import BackendApplication

if __name__ == '__main__':
    app = BackendApplication()
    app.kernel.rpc.register('hello', lambda: print('hello world'))
    app.kernel.rpc.register('add2', lambda x, y: x + y)
    app.run()
```
## Frontend Side (Py)
```python
from MesonPy.FrontendApplication import FrontendApplication

if __name__ == '__main__':
    app = FrontendApplication()
    app.start()
	app.rpc('hello') # Print "hello world" in the server process
    print(app.rpc('add2', (2, 1))) # 3
```