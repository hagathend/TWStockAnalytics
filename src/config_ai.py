"""AI 供應商設定的本地儲存（選用供應商 + 各家 API Key）。

存成 data/ai_settings.json，純本機明文儲存（不會提交進 git，見 .gitignore）。
與 .env 分開存放，是因為這裡的值要能在 Streamlit 執行期間即時讀寫、
不需要重啟程式套用 .env 才會生效。
"""

import json

from src.config import DATA_DIR

_CONFIG_PATH = DATA_DIR / "ai_settings.json"
_OLLAMA_CONFIG_PATH = DATA_DIR / "ollama_settings.json"
_SCRAPING_CONFIG_PATH = DATA_DIR / "scraping_settings.json"

PROVIDERS = ["claude", "gpt", "gemini"]

_DEFAULT = {"active_provider": "claude", "keys": {p: "" for p in PROVIDERS}}

_OLLAMA_DEFAULT = {
    "host": "http://localhost:11434",
    "model": "qwen2.5:7b",
    "auto_analyze_after_collect": True,
}

_SCRAPING_DEFAULT = {"firecrawl_api_key": ""}


def load_ai_settings() -> dict:
    if not _CONFIG_PATH.exists():
        return dict(_DEFAULT)
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    merged = dict(_DEFAULT)
    merged.update(data)
    merged["keys"] = {**_DEFAULT["keys"], **data.get("keys", {})}
    return merged


def save_ai_settings(settings: dict):
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def load_ollama_settings() -> dict:
    if not _OLLAMA_CONFIG_PATH.exists():
        return dict(_OLLAMA_DEFAULT)
    with open(_OLLAMA_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {**_OLLAMA_DEFAULT, **data}


def save_ollama_settings(settings: dict):
    with open(_OLLAMA_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def load_scraping_settings() -> dict:
    """Firecrawl 等內文擷取服務的設定（選用，沒設定就退回本機 Playwright）"""
    if not _SCRAPING_CONFIG_PATH.exists():
        return dict(_SCRAPING_DEFAULT)
    with open(_SCRAPING_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {**_SCRAPING_DEFAULT, **data}


def save_scraping_settings(settings: dict):
    with open(_SCRAPING_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
