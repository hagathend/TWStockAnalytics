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


_CODEX_CONFIG_PATH = DATA_DIR / "codex_settings.json"
_CODEX_DEFAULT = {"executable": "codex", "model": "", "timeout_seconds": 300,
                  # 收集後自動分析新聞（每日排程與側邊欄「立即收集」都會執行）
                  "auto_analyze_after_collect": True,
                  # 新聞焦點最多挑幾檔（10／20／30／50）
                  "news_top_n": 50,
                  # 每日排程順便用 Codex 分析持股／觀察名單個股（每檔一次呼叫，預設關閉避免額度用光）
                  "auto_analyze_holdings": False,
                  "auto_analyze_watchlist": False}


def load_codex_settings() -> dict:
    if not _CODEX_CONFIG_PATH.exists():
        return dict(_CODEX_DEFAULT)
    return {**_CODEX_DEFAULT, **json.loads(_CODEX_CONFIG_PATH.read_text(encoding="utf-8"))}


def save_codex_settings(settings: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _CODEX_CONFIG_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def update_codex_settings(changes: dict) -> dict:
    """只改指定欄位，其他既有設定保留（不同頁面各自存自己的欄位，不會互相覆蓋）"""
    settings = {**load_codex_settings(), **changes}
    save_codex_settings(settings)
    return settings


# 每日報告要不要包含「我的持股」。預設不包含：報告會被下載成 PDF／Markdown 分享出去，
# 持股成本與損益屬於個人財務資料，要使用者主動打開才放進去。
_REPORT_CONFIG_PATH = DATA_DIR / "report_settings.json"
_REPORT_DEFAULT = {"include_holdings": False}


def load_report_settings() -> dict:
    if not _REPORT_CONFIG_PATH.exists():
        return dict(_REPORT_DEFAULT)
    return {**_REPORT_DEFAULT, **json.loads(_REPORT_CONFIG_PATH.read_text(encoding="utf-8"))}


def save_report_settings(settings: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _REPORT_CONFIG_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
