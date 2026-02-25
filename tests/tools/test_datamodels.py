import pytest
from pathlib import Path
import numpy as np

from data_pipeline.tools.datamodels import AlbumMetadata, AudioWithMetadata, EmbeddingWithMetadata, Song


class TestAlbumMetadata:
    def test_create_with_all_fields(self):
        meta = AlbumMetadata(album_id=1, title="My Album", artist_name="Artist", url="http://example.com")
        assert meta.album_id == 1
        assert meta.title == "My Album"
        assert meta.artist_name == "Artist"
        assert meta.url == "http://example.com"

    def test_equality(self):
        a = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        b = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        assert a == b

    def test_inequality(self):
        a = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        b = AlbumMetadata(album_id=2, title="T", artist_name="A", url="u")
        assert a != b


class TestAudioWithMetadata:
    def test_create_with_all_fields(self, tmp_path):
        meta = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        audio = AudioWithMetadata(file_path=tmp_path / "track.mp3", metadata=meta)
        assert audio.file_path == tmp_path / "track.mp3"
        assert audio.metadata is meta

    def test_file_path_is_path_type(self, tmp_path):
        meta = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        audio = AudioWithMetadata(file_path=tmp_path / "track.mp3", metadata=meta)
        assert isinstance(audio.file_path, Path)

    def test_equality(self, tmp_path):
        meta = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        a = AudioWithMetadata(file_path=tmp_path / "track.mp3", metadata=meta)
        b = AudioWithMetadata(file_path=tmp_path / "track.mp3", metadata=meta)
        assert a == b


class TestEmbeddingWithMetadata:
    def test_create_with_all_fields(self, tmp_path):
        meta = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        embedding = np.zeros(1280)
        item = EmbeddingWithMetadata(file_path=tmp_path / "track.mp3", embedding=embedding, metadata=meta)
        assert item.file_path == tmp_path / "track.mp3"
        assert item.metadata is meta
        np.testing.assert_array_equal(item.embedding, embedding)

    def test_embedding_is_numpy_array(self, tmp_path):
        meta = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        item = EmbeddingWithMetadata(
            file_path=tmp_path / "track.mp3",
            embedding=np.random.rand(1280),
            metadata=meta
        )
        assert isinstance(item.embedding, np.ndarray)

    def test_embedding_dimension(self, tmp_path):
        meta = AlbumMetadata(album_id=1, title="T", artist_name="A", url="u")
        embedding = np.zeros(1280)
        item = EmbeddingWithMetadata(file_path=tmp_path / "track.mp3", embedding=embedding, metadata=meta)
        assert item.embedding.shape == (1280,)


class TestSong:
    def test_create_with_all_fields(self):
        song = Song(id=1, title="My Song", artist="Artist", album="Album", filepath="/path/to/file.mp3", embedding=[0.1, 0.2])
        assert song.id == 1
        assert song.title == "My Song"
        assert song.artist == "Artist"
        assert song.album == "Album"
        assert song.filepath == "/path/to/file.mp3"
        assert song.embedding == [0.1, 0.2]

    def test_equality(self):
        a = Song(id=1, title="T", artist="A", album="Al", filepath="f", embedding=[])
        b = Song(id=1, title="T", artist="A", album="Al", filepath="f", embedding=[])
        assert a == b
