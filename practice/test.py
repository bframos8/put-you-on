from pathlib import Path
import re
import os
        
def _test_title():
    album_dir = DOWNLOADS_DIR = Path(__file__).parent / "downloads"
    audio_extensions = {'.mp3', '.flac', '.wav', '.m4a', '.ogg'}
    audio_file_paths = [
        f for f in album_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in audio_extensions
    ]
    
    for num,path in enumerate(audio_file_paths):
        print(f'ALBUM NUMBER: {num}')
        print(path.stem)
        almost = str(path.stem)
        print(almost) 
        almost_2 = re.split(r"\d+\s-?\s", almost)
        print(almost_2[1])
        almost_3 = almost_2[1].replace("-", " ")
        print(almost_3)
        almost_4 = almost_3.capitalize()
        print(almost_4)
        
def _test_removing_file():
    album_dir = DOWNLOADS_DIR = Path(__file__).parent.parent / "data_pipeline" / "song_pipeline" / "downloads"
    audio_extensions = {'.mp3', '.flac', '.wav', '.m4a', '.ogg'}
    audio_file_paths = [
        f for f in album_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in audio_extensions
    ]
    for path in audio_file_paths[1:2]:
        print(f"Working on {str(path)}")
        os.remove(path)
        if not path.is_file():
            print(f'{str(path)} deleted')
    
if __name__ == "__main__":
    _test_removing_file()