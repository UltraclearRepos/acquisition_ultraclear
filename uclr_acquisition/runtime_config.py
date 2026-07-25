class RuntimeConfig:
    _DEFAULT_CONFIG = {
        'usg_enabled': False,
        'active_trackers': [],
        'mems_enabled': False,
        'sync_output': None,
    }

    def __init__(self):
        self._config = dict()

    def set_value(self, key, value):
        self._config[key] = value

    def __getitem__(self, key):
        return self._config.get(key, self._DEFAULT_CONFIG[key])


runtime_config = RuntimeConfig()
