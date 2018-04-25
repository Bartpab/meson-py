import uuid
import logging

logger = logging.getLogger(__name__)

class Session:
    def __init__(self, sessionId):
        self.id = sessionId

class SessionManager:
    def __init__(self, app):
        self._sessions = {}
        self.newCallbacks = []
        self.removedCallbacks = []

    def onNew(self, callback):
        self.newCallbacks.append(callback)
    def onRemove(self, callback):
        self.removedCallbacks.append(callback)

    def generateId(self):
        return uuid.uuid4()

    def sessions(self):
        return self._sessions

    def new(self):
        session = Session(self.generateId())
        logger.info('New session, id={}'.format(session.id))
        self._sessions[session.id] = session

        # Call everybody who wants to know about a new session
        for callback in self.newCallbacks:
            callback(session)

        return session

    def remove(self, session):
        del self._sessions[session.id]
        for removeCallback in self.removedCallbacks: removeCallback(session)
