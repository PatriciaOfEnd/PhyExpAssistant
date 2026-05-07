from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json

from .paths import app_home

SETTINGS_DIR = app_home()
SETTINGS_PATH = SETTINGS_DIR / "settings.json"


@dataclass
class Settings:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    timeout_seconds: int = 120
    ui_theme: str = "light"
    ui_custom_background: str = "#f5f7fb"
    ui_custom_foreground: str = "#1f2937"

    @property
    def is_llm_ready(self) -> bool:
        return bool(self.api_key.strip() and self.model.strip() and self.base_url.strip())

    @property
    def masked_api_key(self) -> str:
        key = self.api_key.strip()
        if not key:
            return "未设置"
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}...{key[-4:]}"


def load_settings() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return Settings()
    defaults = asdict(Settings())
    defaults.update({key: value for key, value in data.items() if key in defaults})
    return Settings(**defaults)


def save_settings(settings: Settings) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
