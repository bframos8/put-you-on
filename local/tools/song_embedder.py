import os 
import numpy as np
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs

class SongEmbedder:
    def __init__(self):
        self.loader = MonoLoader()
        self.model = TensorflowPredictEffnetDiscogs()
    
    def load_song(self, filepath:str):
        song = self.loader(filename = filepath, samplerate = 16000, resampleQuality = 4)
        return song
    
    def embed_song(self,song):
        frame_embeddings = self.model(song)
        song_embedding = frame_embeddings.mean(axis=0)
        return song_embedding