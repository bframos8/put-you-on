from threading import Thread, Event

class PipelineStage(Thread):
    def __init__(self, name: str, stop_event: Event):
        super().__init__(daemon=True)
        self.name = name
        self.error: Exception | None = None
        self._stop_event = stop_event

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def stop(self):
        self._stop_event.set()
