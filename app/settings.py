"""
App-wide settings: persistent key/value store backed by a JSON file.
Provides defaults for system prompt and other preferences.
"""

import json
import os
from pathlib import Path


# XDG config dir: ~/.config/localai/
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "localai"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

DEFAULTS = {
    "default_system_prompt": "You are a helpful assistant.",
    "last_model": None,         # hf_id of the most recently used model
    "window_width": 1100,
    "window_height": 720,
}


def _load() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Settings:
    """
    Singleton-style settings object. Access via the module-level `settings`
    instance. Values are lazily loaded from disk.
    """

    def __init__(self):
        self._data = {**DEFAULTS, **_load()}

    def get(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        self._data[key] = value
        _save(self._data)

    @property
    def default_system_prompt(self) -> str:
        return self.get("default_system_prompt")

    @default_system_prompt.setter
    def default_system_prompt(self, value: str):
        self.set("default_system_prompt", value)

    @property
    def last_model(self):
        return self.get("last_model")

    @last_model.setter
    def last_model(self, value):
        self.set("last_model", value)


# Module-level singleton — import this in other modules:
#   from app.settings import settings
settings = Settings()
