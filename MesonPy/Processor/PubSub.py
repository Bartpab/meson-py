import asyncio
import logging

from MesonPy.Processor.Processor import iProcessor
from MesonPy.Processor.Processor import InstructionContext

logger = logging.getLogger(__name__)

class PubSubService:
    def __init__(self, processor):
        self.processor = processor

    def publish(self, topic, domain, payload, author=None, targets=None):
        self.processor.publish(topic, domain, payload, author, targets)

    def subscribeClient(self, session, topic, domain):
        self.processor.subscribeClient(session, topic, domain)

class PubSubContext:
    def __init__(self):
        self.domains = {}
    def assertTopic(self, topic, domain):
        if domain not in self.domains:
            self.domains[domain] = {}
        if topic not in self.domains[domain]:
            self.domains[domain][topic] = []
    def sessions(self, topic, domain, *exclude):
        self.assertTopic(topic, domain)
        return [session for session in self.domains[domain][topic] if session not in exclude]
    def removeSessionSubscriptions(self, session):
        for domain, topicDict in self.domains.items():
            for topic, sessions in topicDict.items():
                self.domains[domain][topic] = [sess for sess in sessions if session != sess]
    def subscribeClient(self, session, topic, domain):
        session.onClose(self.removeSessionSubscriptions)
        self.assertTopic(topic, domain)
        if session not in self.domains[domain][topic]:
            self.domains[domain][topic].append(session)

class PubSubProcessor(iProcessor):
    def __init__(self):
        self.executionQueue = asyncio.Queue()
        self.context = PubSubContext()

    def canHandleOperation(self, instructionCtx):
        return instructionCtx.operationType == 'PUBSUB' and 'type' in instructionCtx.payload and 'topic' in instructionCtx.payload

    def push(self, instructionCtx):
        asyncio.ensure_future(self.executionQueue.put(instructionCtx))

    def publish(self, topic, domain, payload, author=None, targets=None):
        if author != None:
            logger.info('Publish about %s on %s by %s', topic, domain, author.id)
        else:
            logger.info('Publish about %s on %s', topic, domain)

        # Publish on given sessions
        if targets is not None:
            for session in targets:
                session.front.push(InstructionContext('PUBSUB', {
                    'type': 'publish',
                    'topic': topic,
                    'domain': domain,
                    'payload': payload
                }))
            return

        if author != None:
            sessions = self.context.sessions(topic, domain)
        else:
            sessions = self.context.sessions(topic, domain, author)

        if payload is None:
            payload = []

        for session in sessions:
            session.front.push(InstructionContext('PUBSUB', {
                'type': 'publish',
                'topic': topic,
                'domain': domain,
                'payload': payload
            }))
    def subscribeClient(self, session, topic, domain):
        logger.info('Subscribe about %s on %s by %s', topic, domain, session.id)
        self.context.subscribeClient(session, topic, domain)

    @asyncio.coroutine
    def step(self, stackContext):
        logger.info('Step on %s', self)

        try:
            instructionCtx = yield from self.executionQueue.get()
        except RuntimeError:
            return
        except TypeError:
            return

        if instructionCtx['type'] == 'subscribe':
            self.subscribeClient(instructionCtx.session,
                           instructionCtx.payload['topic'],
                           instructionCtx.payload['domain'] if 'domain' in instructionCtx.payload else '__default__')

        if instructionCtx['type'] == 'publish':
            self.publish(instructionCtx.session,
                         instructionCtx.payload['topic'],
                         instructionCtx.payload['domain'] if 'domain' in instructionCtx.payload else '__default__',
                         instructionCtx.payload['payload'] if 'payload' in instructionCtx.payload else None)