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
            conn.execute(
                """INSERT OR IGNORE INTO news
                   (date, source, title, url, summary, related_code, published_at, collected_at)
                   VALUES (:date, :source, :title, :url, :summary, :related_code, :published_at, :collected_at)""",
                row,
            )


def log_step(step: str, status: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO collect_log (run_at, step, status, detail) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), step, status, detail),
        )


def query_stock_price(date: str, code: str | None = None):
    with get_conn() as conn:
        if code:
            cur = conn.execute(
                "SELECT * FROM stock_price WHERE date = ? AND code = ?", (date, code)
            )
        else:
            cur = conn.execute("SELECT * FROM stock_price WHERE date = ?", (date,))
        return [dict(r) for r in cur.fetchall()]


def query_institutional(date: str, code: str | None = None):
    with get_conn() as conn:
        if code:
            cur = conn.execute(
                "SELECT * FROM institutional WHERE date = ? AND code = ?", (date, code)
            )
        else:
            cur = conn.execute("SELECT * FROM institutional WHERE date = ?", (date,))
        return [dict(r) for r in cur.fetchall()]


def query_margin(date: str, code: str | None = None):
    with get_conn() as conn:
        if code:
            cur = conn.execute(
                "SELECT * FROM margin WHERE date = ? AND code = ?", (date, code)
            )
        else:
            cur = conn.execute("SELECT * FROM margin WHERE date = ?", (date,))
        return [dict(r) for r in cur.fetchall()]


def query_news(date: str, related_code: str | None = None):
    with get_conn() as conn:
        if related_code:
            cur = conn.execute(
                "SELECT * FROM news WHERE date = ? AND related_code = ? ORDER BY published_at DESC",
                (date, related_code),
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
