from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "tw_stock.db"

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
