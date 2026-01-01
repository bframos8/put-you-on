from threading import Thread

class PipelineStage(Thread):
    def __init__(self, name:str):
        super().__init__(daemon=True)
        self.name = name
    
    def stop(self):
        pass