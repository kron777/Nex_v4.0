from collections import deque


class MemorySystem:

    def __init__(self, max_events=5000):
        self.events = deque(maxlen=max_events)


    def store_tick(self, *args, **kwargs):

        event = {}

        if args:
            event["tick"] = args[0]

        event.update(kwargs)

        self.events.append(event)


    def summary(self):

        return {
            "events": len(self.events)
        }
