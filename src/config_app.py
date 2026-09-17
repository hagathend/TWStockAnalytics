"""App 本身的使用者設定（第一次使用引導是否完成、版本檢查快取）。存 data/app_settings.json，不提交。"""

import json

from src.config import DATA_DIR

_PATH = DATA_DIR / "app_settings.json"
_DEFAULT = {
    # None = 從沒設定過；app 會依「資料庫有沒有資料」判斷要不要顯示引導，
    # 既有使用者升級上來不會被迫重跑一次引導
    "onboarding_done": None,
    "disclaimer_accepted": False,
    "update_checked_at": None,
    "latest_release": None,
    # 券商手續費折扣（1＝無折扣，2.8 折填 0.28），交易紀錄自動試算手續費用
    "fee_discount": 1.0,
    # 每日自動收集的執行時間（HH:MM）；實際排程存在 Windows 工作排程器，這裡記住使用者選的時間
    "daily_task_time": "20:00",
}


def load_app_settings() -> dict:
    try:
        return {**_DEFAULT, **json.loads(_PATH.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(_DEFAULT)


def save_app_settings(changes: dict) -> dict:
    settings = {**load_app_settings(), **changes}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings
