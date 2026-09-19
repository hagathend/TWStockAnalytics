"""選股條件範本：把常用的篩選條件存起來，一鍵套用。存 data/screener_presets.json：{"範本名稱": {條件 key: 值}}。"""

import json

from src.config import DATA_DIR

_PATH = DATA_DIR / "screener_presets.json"


class PresetError(ValueError):
    pass


def load_presets() -> dict[str, dict]:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(presets: dict[str, dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")


def save_preset(name: str, values: dict) -> str:
    """同名會覆蓋（方便更新範本）"""
    name = (name or "").strip()
    if not name:
        raise PresetError("請輸入範本名稱")
    presets = load_presets()
    presets[name] = values
    _save(presets)
    return name


def delete_preset(name: str):
    presets = load_presets()
    if presets.pop(name, None) is not None:
        _save(presets)
