import os
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "aim"
AGENTS_DIR = CONFIG_DIR / "agents"
CONVERSATIONS_DIR = CONFIG_DIR / "conversations"

ENV_VAR_MAP = {
    "api_key": "AIM_API_KEY",
    "api_base": "AIM_API_BASE",
    "model": "AIM_MODEL",
}

DEFAULTS = {
    "api_key": "",
    "api_base": "https://api.openai.com/v1",
    "model": "gpt-3.5-turbo",
}


def ensure_dirs():
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    ensure_dirs()
    config_file = CONFIG_DIR / "config.json"
    cfg = {}
    if config_file.exists():
        cfg = json.loads(config_file.read_text())
    for key, env in ENV_VAR_MAP.items():
        val = os.environ.get(env)
        if val:
            cfg[key] = val
    for key, default in DEFAULTS.items():
        cfg.setdefault(key, default)
    return cfg


def save_config(cfg):
    config_file = CONFIG_DIR / "config.json"
    config_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
