import json


class Configurator:

    def __init__(self):
        self._config = dict()

    def load_from_json(self, path):
        with open(path) as f:
            self._config = json.load(f)

    def __getitem__(self, key):
        return self._config[key]


config = Configurator()
