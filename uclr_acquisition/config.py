import json

# Folder for Raspberry Pi MEMS WAV recordings, relative to the working directory
AUDIO_RAW_DIR = "audio_raw"

# Folder for each camera's recordings, relative to the working directory
CAMERA_VIDEO_DIRS = {
    "cam1": "video_cam1",
    "cam2": "video_cam2",
}


class Configurator:

    def __init__(self):
        self._config = dict()

    def load_from_json(self, path):
        with open(path) as f:
            self._config = json.load(f)

    def __getitem__(self, key):
        return self._config[key]

    def get(self, key, default=None):
        return self._config.get(key, default)


config = Configurator()
