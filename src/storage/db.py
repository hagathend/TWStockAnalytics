import sqlite3
from contextlib import contextmanager
from datetime import datetime

from src.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_price (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    change REAL,
    volume INTEGER,
    turnover INTEGER,
    PRIMARY KEY (date, market, code)
);

CREATE TABLE IF NOT EXISTS institutional (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    foreign_net INTEGER,
    trust_net INTEGER,
    dealer_net INTEGER,
    total_net INTEGER,
    PRIMARY KEY (date, market, code)
);

CREATE TABLE IF NOT EXISTS margin (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    margin_balance INTEGER,
    margin_buy INTEGER,
    margin_sell INTEGER,
    short_balance INTEGER,
    short_sell INTEGER,
    short_cover INTEGER,
    PRIMARY KEY (date, market, code)
);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    summary TEXT,
    content TEXT,
    related_code TEXT,
    published_at TEXT,
    collected_at TEXT
);

CREATE TABLE IF NOT EXISTS collect_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS ai_picks (
    date TEXT NOT NULL,
    rank INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    reason TEXT,
    PRIMARY KEY (date, rank)
);

CREATE TABLE IF NOT EXISTS ai_analysis_summary (
    date TEXT PRIMARY KEY,
    provider TEXT,
    summary TEXT,
    created_at TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        try:
            conn.execute("ALTER TABLE news ADD COLUMN content TEXT")
        except sqlite3.OperationalError:
            pass  # 欄位已存在（舊資料庫升級用，新建的資料庫已經在 SCHEMA 裡就有這欄）


def save_stock_price(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO stock_price
               (date, market, code, name, open, high, low, close, change, volume, turnover)
               VALUES (:date, :market, :code, :name, :open, :high, :low, :close, :change, :volume, :turnover)""",
            rows,
        )


def save_institutional(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO institutional
               (date, market, code, name, foreign_net, trust_net, dealer_net, total_net)
               VALUES (:date, :market, :code, :name, :foreign_net, :trust_net, :dealer_net, :total_net)""",
            rows,
        )


def save_margin(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO margin
               (date, market, code, name, margin_balance, margin_buy, margin_sell, short_balance, short_sell, short_cover)
               VALUES (:date, :market, :code, :name, :margin_balance, :margin_buy, :margin_sell, :short_balance, :short_sell, :short_cover)""",
            rows,
        )


def save_news(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        for row in rows:
            row = {"content": None, **row}  # content 是後來才加的欄位，不是每個來源都會提供
            conn.execute(
                """INSERT OR IGNORE INTO news
                   (date, source, title, url, summary, content, related_code, published_at, collected_at)
                   VALUES (:date, :source, :title, :url, :summary, :content, :related_code, :published_at, :collected_at)""",
                row,
            )


def log_step(step: str, status: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO collect_log (run_at, step, status, detail) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), step, status, detail),
        )


def query_stock_price(date: str, keyword: str | None = None):
    with get_conn() as conn:
        if keyword:
            like = f"%{keyword}%"
            cur = conn.execute(
                "SELECT * FROM stock_price WHERE date = ? AND (code LIKE ? OR name LIKE ?)",
                (date, like, like),
            )
        else:
            cur = conn.execute("SELECT * FROM stock_price WHERE date = ?", (date,))
        return [dict(r) for r in cur.fetchall()]


def query_institutional(date: str, keyword: str | None = None):
    with get_conn() as conn:
        if keyword:
            like = f"%{keyword}%"
            cur = conn.execute(
                "SELECT * FROM institutional WHERE date = ? AND (code LIKE ? OR name LIKE ?)",
                (date, like, like),
            )
        else:
            cur = conn.execute("SELECT * FROM institutional WHERE date = ?", (date,))
        return [dict(r) for r in cur.fetchall()]


def query_margin(date: str, keyword: str | None = None):
    with get_conn() as conn:
        if keyword:
            like = f"%{keyword}%"
            cur = conn.execute(
                "SELECT * FROM margin WHERE date = ? AND (code LIKE ? OR name LIKE ?)",
                (date, like, like),
            )
        else:
            cur = conn.execute("SELECT * FROM margin WHERE date = ?", (date,))
        return [dict(r) for r in cur.fetchall()]


def query_news(date: str, keyword: str | None = None):
    with get_conn() as conn:
        if keyword:
            like = f"%{keyword}%"
            cur = conn.execute(
                """SELECT * FROM news WHERE date = ? AND (title LIKE ? OR related_code LIKE ?)
                   ORDER BY published_at DESC""",
                (date, like, like),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM news WHERE date = ? ORDER BY published_at DESC", (date,)
            )
        return [dict(r) for r in cur.fetchall()]


def query_available_dates():
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT DISTINCT date FROM stock_price ORDER BY date DESC LIMIT 30"
        )
        return [r["date"] for r in cur.fetchall()]


def query_recent_logs(limit: int = 50):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM collect_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]


def query_code_history(table: str, code: str, limit: int = 30):
    """查詢特定股票代號在指定表格內、依日期排序的歷史紀錄（本地資料庫累積的部分）"""
    if table not in ("stock_price", "institutional", "margin"):
        raise ValueError(f"不支援的表格: {table}")
    with get_conn() as conn:
        cur = conn.execute(
            f"SELECT * FROM {table} WHERE code = ? ORDER BY date DESC LIMIT ?",
            (code, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def lookup_stock_name(code: str) -> str | None:
    """從最近一次收集到的股價資料查詢股票名稱，供編輯觀察名單時自動帶入。"""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT name FROM stock_price WHERE code = ? ORDER BY date DESC LIMIT 1",
            (code,),
        )
        row = cur.fetchone()
        return row["name"] if row else None


def lookup_stock_code_by_name(name: str) -> str | None:
    """從最近一次收集到的股價資料，用名稱反查股票代號。

    用來校正 AI 分析結果：AI 有時會記錯代號和名稱的對應（例如把2454聯發科講成2357），
    但新聞文字通常是用公司名稱而非代號，名稱相對可信，所以用名稱回頭查官方代號來源做校正。
    """
    if not name:
        return None
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT code FROM stock_price WHERE name = ? ORDER BY date DESC LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        if row:
            return row["code"]
        cur = conn.execute(
            "SELECT code FROM stock_price WHERE name LIKE ? ORDER BY date DESC LIMIT 1",
            (f"%{name}%",),
        )
        row = cur.fetchone()
        return row["code"] if row else None


def save_ai_picks(date: str, picks: list[dict]):
    """picks: [{rank, code, name, reason}, ...]，同一天重新分析會先清掉舊資料再存新的"""
    with get_conn() as conn:
        conn.execute("DELETE FROM ai_picks WHERE date = ?", (date,))
        conn.executemany(
            "INSERT INTO ai_picks (date, rank, code, name, reason) VALUES (:date, :rank, :code, :name, :reason)",
            [{**p, "date": date} for p in picks],
        )


def query_ai_picks(date: str):
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM ai_picks WHERE date = ? ORDER BY rank", (date,)
        )
        return [dict(r) for r in cur.fetchall()]


def save_ai_analysis_summary(date: str, provider: str, summary: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO ai_analysis_summary (date, provider, summary, created_at)
               VALUES (?, ?, ?, ?)""",
            (date, provider, summary, datetime.now().isoformat(timespec="seconds")),
        )


def query_ai_analysis_summary(date: str) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM ai_analysis_summary WHERE date = ?", (date,)
        )
        row = cur.fetchone()
        return dict(row) if row else None
