import json
from pathlib import Path

from dotenv import load_dotenv
import os

APP_NAME = "TWStockAnalytics"
BASE_DIR = Path(__file__).resolve().parent.parent

# 安裝版（Windows 安裝程式裝的）根目錄會有 .installed 標記檔。
# 安裝版的程式資料夾在更新時會被整個覆蓋，所以資料一定要放在程式資料夾以外：
#   %LOCALAPPDATA%\TWStockAnalytics\data
# 開發用的 git checkout 沒有標記檔，照舊用專案內的 data/，不影響既有資料。
# 環境變數 TWSTOCK_DATA_DIR 可以強制指定位置（測試、搬家用）。
IS_INSTALLED = (BASE_DIR / ".installed").exists()


def _resolve_data_dir() -> Path:
    override = os.getenv("TWSTOCK_DATA_DIR")
    if override:
        return Path(override)
    if IS_INSTALLED:
        local = os.getenv("LOCALAPPDATA")
        root = Path(local) if local else Path.home() / "AppData" / "Local"
        return root / APP_NAME / "data"
    return BASE_DIR / "data"


DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = DATA_DIR / "logs"

# 開發時讀專案根目錄的 .env；安裝版另外讀資料夾裡的 .env（使用者自己放的設定，更新時不會被覆蓋）
load_dotenv()
load_dotenv(DATA_DIR / ".env")

# 安裝版把 Chromium 放在程式資料夾的 ms-playwright，PDF 與新聞內文擷取要用
_BUNDLED_BROWSERS = BASE_DIR / "ms-playwright"
if _BUNDLED_BROWSERS.is_dir():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_BUNDLED_BROWSERS))

DB_FILE_NAME = "tw_stock.db"
DEFAULT_DB_DIR = DATA_DIR
# 資料庫可以搬到別的資料夾（例如空間比較大的磁碟）：位置記在資料夾裡的 storage_settings.json，
# App、每日排程、背景補資料都從這裡讀，所以搬一次各處一致。設定其餘的 json 仍留在 DATA_DIR（都很小）
STORAGE_SETTINGS_PATH = DATA_DIR / "storage_settings.json"
# 設定了自訂位置、但那裡找不到資料庫（例如外接硬碟沒接上）時的說明；這時暫時改用預設位置，畫面上會提醒
DB_LOCATION_ERROR: str | None = None


def _resolve_db_path() -> Path:
    global DB_LOCATION_ERROR
    try:
        custom = json.loads(STORAGE_SETTINGS_PATH.read_text(encoding="utf-8")).get("db_dir")
    except (OSError, ValueError, AttributeError):
        custom = None
    if custom:
        path = Path(custom) / DB_FILE_NAME
        if path.is_file():
            return path
        DB_LOCATION_ERROR = f"設定的資料庫位置找不到資料庫：{path}（磁碟沒接上或檔案被移走），暫時改用預設位置"
    return DEFAULT_DB_DIR / DB_FILE_NAME


DB_PATH = _resolve_db_path()

FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")

# 每日重點觀察名單，其新聞會額外用 RSS 做延伸搜尋
# 之後 AI 分析階段會改成從新聞內容自動判斷重點個股
WATCHLIST = {
    "2330": "台積電",
    "2317": "鴻海",
    "2454": "聯發科",
    "2308": "台達電",
    "2382": "廣達",
}
