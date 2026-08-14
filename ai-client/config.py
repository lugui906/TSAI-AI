import os
import json

CONFIG_DIR = os.path.expanduser("~/.ai-assistant")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "backend": "ollama",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "aim_model": "opencode/deepseek-v4-flash-free",
    "window_width": 900,
    "window_height": 600,
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
                return config
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
