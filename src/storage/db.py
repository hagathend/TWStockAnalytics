import sqlite3
from contextlib import contextmanager
from datetime import date as _date, datetime, timedelta

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
    excerpt TEXT,
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

CREATE TABLE IF NOT EXISTS stock_analysis (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    analysis TEXT,
    created_at TEXT,
    PRIMARY KEY (date, code)
);

CREATE TABLE IF NOT EXISTS market_analysis (
    date TEXT PRIMARY KEY,
    analysis TEXT,
    created_at TEXT
);

-- 補收集歷史時記錄「這天確認過有沒有開盤」，非交易日只需要問一次 TWSE，之後直接跳過
CREATE TABLE IF NOT EXISTS trading_calendar (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    is_trading INTEGER NOT NULL,
    checked_at TEXT,
    PRIMARY KEY (date, market)
);

-- 本益比／殖利率／淨值比：虧損公司本益比為 NULL（不是 0）
CREATE TABLE IF NOT EXISTS valuation (
    date TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    pe_ratio REAL,
    dividend_yield REAL,
    pb_ratio REAL,
    PRIMARY KEY (date, market, code)
);

-- 月營收（千元）：來源只提供最新公布月份，每天收一次以 year_month 覆寫，歷史靠累積
CREATE TABLE IF NOT EXISTS month_revenue (
    year_month TEXT NOT NULL,
    market TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    industry TEXT,
    revenue INTEGER,
    revenue_last_month INTEGER,
    revenue_last_year INTEGER,
    mom_pct REAL,
    yoy_pct REAL,
    cum_revenue INTEGER,
    cum_revenue_last_year INTEGER,
    cum_yoy_pct REAL,
    PRIMARY KEY (year_month, market, code)
);

-- 交易紀錄（取代 holdings）：持倉與已實現損益都由這張表以平均成本法推算。股數以「股」計，金額單位元
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    shares INTEGER NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0,
    reason TEXT,
    created_at TEXT
);

-- 賣出交易的 AI 覆盤
CREATE TABLE IF NOT EXISTS trade_reviews (
    trade_id INTEGER PRIMARY KEY,
    review TEXT NOT NULL,
    created_at TEXT
);

-- 一次性資料轉換的完成標記（例如 holdings → trades），避免使用者刪光交易後又被重新匯入
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 集保戶股權分散表（每週）：level 1–15 為持股分級、17 為合計；來源只有最新一週，歷史靠累積
CREATE TABLE IF NOT EXISTS shareholding (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    level INTEGER NOT NULL,
    holders INTEGER,
    shares INTEGER,
    pct REAL,
    PRIMARY KEY (date, code, level)
);

-- 條件提醒：規則與觸發紀錄。同一規則、同一檔、同一資料日期只記一次（避免重複通知）
CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    code TEXT,
    name TEXT,
    threshold REAL,
    signal_key TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    message TEXT,
    created_at TEXT,
    UNIQUE (rule_id, code, date)
);

-- AI 預測追蹤：從個股分析的「預測摘要」解析出來，結果在需要時用股價即時計算（不存結果，股價補齊後會自動更新）
CREATE TABLE IF NOT EXISTS predictions (
    date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    direction TEXT NOT NULL,
    support REAL,
    resistance REAL,
    confidence TEXT,
    created_at TEXT,
    PRIMARY KEY (date, code)
);

-- 我的持股：每一筆買進一列（分批買進就多列），股數以「股」為單位（1 張 = 1000 股，零股也能記）。
-- 賣出時直接修改股數或刪除該筆。屬於個人財務資料，資料庫檔案不進版控。
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    shares INTEGER NOT NULL,
    cost_price REAL NOT NULL,
    buy_date TEXT,
    note TEXT,
    created_at TEXT
);
"""


# 「個股」代號：普通股 4 碼、特別股 4 碼加英文字、臺灣存託憑證 91 開頭 6 碼。
# T86 與上櫃法人資料會混進上萬筆權證／牛熊證（03～08、7 開頭）、ETN（02 開頭）與 ETF（00 開頭）。
# 權證的自營商避險股數極大，直接加總會讓「全市場法人買賣超」嚴重失真（曾經 +3.2 億股被算成 -9.3 億股），
# ETF 的造市申贖也一樣，所以大盤加總只算個股。
STOCK_CODE_SQL = (
    "(code NOT GLOB '00*' AND (code GLOB '[0-9][0-9][0-9][0-9]' OR code GLOB '[0-9][0-9][0-9][0-9][A-Z]' "
    "OR code GLOB '91[0-9][0-9][0-9][0-9]'))"
)


def is_stock_code(code: str) -> bool:
    code = code or ""
    if code.startswith("00"):  # ETF（0050、00631L…）
        return False
    if len(code) == 4 and code.isdigit():
        return True
    if len(code) == 5 and code[:4].isdigit() and code[4].isalpha() and code[4].isupper():
        return True
    return len(code) == 6 and code.isdigit() and code.startswith("91")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate_holdings_to_trades(conn):
    """舊版「我的持股」每筆買進存在 holdings；改用 trades 後轉成買進交易（只做一次，手續費當 0）"""
    if conn.execute("SELECT 1 FROM app_meta WHERE key = 'holdings_migrated'").fetchone():
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO trades (date, code, name, side, shares, price, fee, tax, reason, created_at)
           SELECT COALESCE(buy_date, substr(created_at, 1, 10), ?), code, name, 'buy', shares, cost_price, 0, 0, note, ?
           FROM holdings ORDER BY id""",
        (now[:10], now),
    )
    conn.execute("INSERT INTO app_meta (key, value) VALUES ('holdings_migrated', ?)", (now,))


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for column, col_type in [("content", "TEXT"), ("excerpt", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE news ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass  # 欄位已存在（舊資料庫升級用，新建的資料庫已經在 SCHEMA 裡就有這欄）
        # 修復舊版解析錯誤存下的上櫃自營商欄位（當時存成外資的數字）。
        # 官方合計欄位是對的，且「合計 = 外資 + 投信 + 自營商」，所以自營商可由另外三欄推回；
        # 資料正確時條件不成立、不會更新任何列。
        _migrate_holdings_to_trades(conn)
        conn.execute(
            """UPDATE institutional SET dealer_net = total_net - foreign_net - COALESCE(trust_net, 0)
               WHERE market = 'TPEx' AND total_net IS NOT NULL AND foreign_net IS NOT NULL
                 AND dealer_net IS NOT total_net - foreign_net - COALESCE(trust_net, 0)"""
        )


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


def save_news_excerpt(news_id: int, excerpt: str):
    """存入 AI 深度分析時逐篇產生的重點摘要，供之後在 UI 顯示 / 報表使用"""
    with get_conn() as conn:
        conn.execute("UPDATE news SET excerpt = ? WHERE id = ?", (excerpt, news_id))


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


def query_institutional_for_code(date: str, code: str) -> dict | None:
    """單一股票當天的法人買賣超。代號必須完全相同——query_institutional 是模糊搜尋，
    查 2330 會連 062330、082330 這些權證一起回來。"""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM institutional WHERE date = ? AND code = ?", (date, code)).fetchone()
        return dict(row) if row else None


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


def query_news_excerpts(date: str):
    """查詢已經做過深度分析、有存逐篇摘要(excerpt)的新聞，供AI分析頁顯示/未來報表使用"""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT * FROM news WHERE date = ? AND excerpt IS NOT NULL
               ORDER BY published_at DESC""",
            (date,),
        )
        return [dict(r) for r in cur.fetchall()]


def query_available_dates():
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT date FROM stock_price
            UNION SELECT date FROM news
            UNION SELECT date FROM ai_picks
            UNION SELECT date FROM ai_analysis_summary
            UNION SELECT date FROM stock_analysis
            UNION SELECT date FROM market_analysis
            ORDER BY date DESC LIMIT 30"""
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


def save_stock_analysis(date: str, code: str, name: str, analysis: str):
    """存入使用者從網頁版AI複製貼回來的個股籌碼/未來展望分析"""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO stock_analysis (date, code, name, analysis, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (date, code, name, analysis, datetime.now().isoformat(timespec="seconds")),
        )


def query_stock_analysis(date: str, code: str | None = None):
    with get_conn() as conn:
        if code:
            cur = conn.execute(
                "SELECT * FROM stock_analysis WHERE date = ? AND code = ?", (date, code)
            )
        else:
            cur = conn.execute("SELECT * FROM stock_analysis WHERE date = ?", (date,))
        return [dict(r) for r in cur.fetchall()]


def query_news_by_keyword(keyword: str, days: int = 7, limit: int = 10):
    """搜尋最近N天內標題/關聯代號/摘要符合關鍵字的新聞，供個股分析湊相關新聞用
    （不像 query_news 限定單一日期，這裡是跨最近幾天搜尋）"""
    since = (_date.today() - timedelta(days=days)).isoformat()
    like = f"%{keyword}%"
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT * FROM news WHERE date >= ?
               AND (title LIKE ? OR related_code LIKE ? OR excerpt LIKE ?)
               ORDER BY published_at DESC LIMIT ?""",
            (since, like, like, like, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def query_market_institutional_summary(date: str) -> dict:
    """上市櫃「個股」三大法人買賣超加總（排除權證、ETN、ETF，見 STOCK_CODE_SQL），供大盤籌碼分析用"""
    with get_conn() as conn:
        cur = conn.execute(
            f"""SELECT SUM(foreign_net) AS foreign_total, SUM(trust_net) AS trust_total,
                      SUM(dealer_net) AS dealer_total, SUM(total_net) AS total_net
               FROM institutional WHERE date = ? AND {STOCK_CODE_SQL}""",
            (date,),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def query_market_breadth(date: str, market: str = "TWSE") -> dict:
    """當日漲跌家數統計。預設只看 TWSE（上市，用 ALLBUT0999 排除權證的乾淨資料），
    因為 TPEx 的股價表混雜大量債券ETF，會讓漲跌家數統計失真。"""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT
                   SUM(CASE WHEN change > 0 THEN 1 ELSE 0 END) AS up,
                   SUM(CASE WHEN change < 0 THEN 1 ELSE 0 END) AS down,
                   SUM(CASE WHEN change = 0 THEN 1 ELSE 0 END) AS flat
               FROM stock_price WHERE date = ? AND market = ?""",
            (date, market),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def save_market_analysis(date: str, analysis: str):
    """存入使用者從網頁版AI複製貼回來的大盤整體籌碼分析"""
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO market_analysis (date, analysis, created_at)
               VALUES (?, ?, ?)""",
            (date, analysis, datetime.now().isoformat(timespec="seconds")),
        )


def query_market_analysis(date: str) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM market_analysis WHERE date = ?", (date,))
        row = cur.fetchone()
        return dict(row) if row else None


# ---------- 歷史補收集 / 交易日曆 ----------


def query_dates_with_data(table: str, market: str = "TWSE") -> set[str]:
    """回傳指定表格在該市場已經有資料的日期集合（補收集時用來跳過已完成的日期）"""
    if table not in ("stock_price", "institutional", "margin"):
        raise ValueError(f"不支援的表格: {table}")
    with get_conn() as conn:
        cur = conn.execute(f"SELECT DISTINCT date FROM {table} WHERE market = ?", (market,))
        return {r["date"] for r in cur.fetchall()}


def query_non_trading_dates(market: str = "TWSE") -> set[str]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT date FROM trading_calendar WHERE market = ? AND is_trading = 0", (market,)
        )
        return {r["date"] for r in cur.fetchall()}


def mark_trading_day(date: str, is_trading: bool, market: str = "TWSE"):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO trading_calendar (date, market, is_trading, checked_at)
               VALUES (?, ?, ?, ?)""",
            (date, market, int(is_trading), datetime.now().isoformat(timespec="seconds")),
        )


def query_trading_dates(market: str = "TWSE", since: str | None = None) -> list[str]:
    """本地資料庫裡有股價資料的交易日（由舊到新），以股價表為準"""
    with get_conn() as conn:
        if since:
            cur = conn.execute(
                "SELECT DISTINCT date FROM stock_price WHERE market = ? AND date >= ? ORDER BY date",
                (market, since),
            )
        else:
            cur = conn.execute(
                "SELECT DISTINCT date FROM stock_price WHERE market = ? ORDER BY date", (market,)
            )
        return [r["date"] for r in cur.fetchall()]


def query_market_history(market: str = "TWSE", since: str | None = None,
                         codes: list[str] | None = None) -> list[dict]:
    """把股價、三大法人、融資融券依 (日期, 代號) 合併成一張寬表，供籌碼指標/選股/回測計算用。

    用 LEFT JOIN 以股價表為主：沒有法人或融資資料的股票（例如不能信用交易的 ETF）欄位會是 NULL，
    由計算端決定怎麼處理，這裡不偷偷補 0。另外帶出 inst_collected / margin_collected：
    「這一天整個市場有沒有收集到法人／融資資料」，用來區分「這檔當天真的是 0」與「那天根本沒收集」。
    """
    params: list = [market]
    where = "p.market = ?"
    if since:
        where += " AND p.date >= ?"
        params.append(since)
    if codes:
        where += f" AND p.code IN ({','.join('?' * len(codes))})"
        params.extend(codes)

    sql = f"""
        SELECT p.date, p.code, p.name, p.open, p.high, p.low, p.close, p.change,
               p.volume, p.turnover,
               i.foreign_net, i.trust_net, i.dealer_net, i.total_net,
               m.margin_balance, m.short_balance,
               CASE WHEN ic.date IS NULL THEN 0 ELSE 1 END AS inst_collected,
               CASE WHEN mc.date IS NULL THEN 0 ELSE 1 END AS margin_collected
        FROM stock_price p
        LEFT JOIN institutional i
               ON i.date = p.date AND i.market = p.market AND i.code = p.code
        LEFT JOIN margin m
               ON m.date = p.date AND m.market = p.market AND m.code = p.code
        LEFT JOIN (SELECT DISTINCT date FROM institutional WHERE market = ?) ic ON ic.date = p.date
        LEFT JOIN (SELECT DISTINCT date FROM margin WHERE market = ?) mc ON mc.date = p.date
        WHERE {where}
        ORDER BY p.code, p.date
    """
    with get_conn() as conn:
        cur = conn.execute(sql, [market, market, *params])
        return [dict(r) for r in cur.fetchall()]


def save_valuation(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO valuation (date, market, code, name, pe_ratio, dividend_yield, pb_ratio)
               VALUES (:date, :market, :code, :name, :pe_ratio, :dividend_yield, :pb_ratio)""",
            rows,
        )


def save_month_revenue(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO month_revenue
               (year_month, market, code, name, industry, revenue, revenue_last_month, revenue_last_year,
                mom_pct, yoy_pct, cum_revenue, cum_revenue_last_year, cum_yoy_pct)
               VALUES (:year_month, :market, :code, :name, :industry, :revenue, :revenue_last_month,
                       :revenue_last_year, :mom_pct, :yoy_pct, :cum_revenue, :cum_revenue_last_year, :cum_yoy_pct)""",
            rows,
        )


def query_latest_valuation(as_of: str | None = None) -> list[dict]:
    """每個市場各自取「最新一天（不晚於 as_of）」的本益比資料；兩市場日期可能不同步，不強制對齊"""
    as_of = as_of or "9999-12-31"
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT v.* FROM valuation v
               JOIN (SELECT market, MAX(date) AS date FROM valuation WHERE date <= ? GROUP BY market) latest
                 ON v.market = latest.market AND v.date = latest.date""",
            (as_of,),
        )
        return [dict(r) for r in cur.fetchall()]


def query_latest_month_revenue() -> list[dict]:
    """每檔股票最新一個月的營收（各公司公布進度不同，所以是逐檔取最新月份）"""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT r.* FROM month_revenue r
               JOIN (SELECT market, code, MAX(year_month) AS ym FROM month_revenue GROUP BY market, code) latest
                 ON r.market = latest.market AND r.code = latest.code AND r.year_month = latest.ym"""
        )
        return [dict(r) for r in cur.fetchall()]


def query_code_fundamentals(code: str, revenue_months: int = 12) -> dict:
    """單一股票最新的本益比資料與近幾個月營收（由新到舊）"""
    with get_conn() as conn:
        valuation = conn.execute(
            "SELECT * FROM valuation WHERE code = ? ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        revenue = conn.execute(
            "SELECT * FROM month_revenue WHERE code = ? ORDER BY year_month DESC LIMIT ?",
            (code, revenue_months),
        ).fetchall()
    return {"valuation": dict(valuation) if valuation else None, "revenue": [dict(r) for r in revenue]}


def add_holding(code: str, name: str, shares: int, cost_price: float, buy_date: str | None = None,
                note: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO holdings (code, name, shares, cost_price, buy_date, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, name, shares, cost_price, buy_date, note, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def update_holding(holding_id: int, shares: int, cost_price: float, buy_date: str | None, note: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE holdings SET shares = ?, cost_price = ?, buy_date = ?, note = ? WHERE id = ?",
            (shares, cost_price, buy_date, note, holding_id),
        )


def delete_holding(holding_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


def query_holdings(code: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if code:
            cur = conn.execute("SELECT * FROM holdings WHERE code = ? ORDER BY buy_date, id", (code,))
        else:
            cur = conn.execute("SELECT * FROM holdings ORDER BY code, buy_date, id")
        return [dict(r) for r in cur.fetchall()]


def query_latest_close(code: str, as_of: str | None = None) -> dict | None:
    """最近一個交易日（不晚於 as_of）的收盤價，上市上櫃都查"""
    as_of = as_of or "9999-12-31"
    with get_conn() as conn:
        row = conn.execute(
            """SELECT date, market, name, close, change FROM stock_price
               WHERE code = ? AND date <= ? AND close IS NOT NULL ORDER BY date DESC LIMIT 1""",
            (code, as_of),
        ).fetchone()
        return dict(row) if row else None


def save_prediction(date: str, code: str, name: str, prediction: dict):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO predictions (date, code, name, direction, support, resistance, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, code, name, prediction["direction"], prediction.get("support"), prediction.get("resistance"),
             prediction.get("confidence"), datetime.now().isoformat(timespec="seconds")),
        )


def delete_prediction(date: str, code: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM predictions WHERE date = ? AND code = ?", (date, code))


def query_predictions(code: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if code:
            cur = conn.execute("SELECT * FROM predictions WHERE code = ? ORDER BY date DESC", (code,))
        else:
            cur = conn.execute("SELECT * FROM predictions ORDER BY date DESC, code")
        return [dict(r) for r in cur.fetchall()]


def query_price_range(code: str, start: str, end: str | None = None) -> list[dict]:
    """某檔股票 start（含）到 end（含，None 表示到最新）的日線"""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT date, open, high, low, close FROM stock_price WHERE code = ? AND date >= ? AND date <= ? ORDER BY date",
            (code, start, end or "9999-12-31"),
        )
        return [dict(r) for r in cur.fetchall()]


def query_market_average_return(start_date: str, end_date: str) -> float | None:
    """上市個股從 start_date 收盤到 end_date 收盤的平均報酬（%），當作「同期大盤」基準"""
    with get_conn() as conn:
        row = conn.execute(
            f"""SELECT AVG(e.close / b.close - 1) * 100 AS avg_return, COUNT(*) AS n
                FROM stock_price b JOIN stock_price e ON e.code = b.code AND e.market = b.market
                WHERE b.date = ? AND e.date = ? AND b.market = 'TWSE' AND b.close > 0 AND e.close IS NOT NULL
                  AND {STOCK_CODE_SQL.replace("code", "b.code")}""",
            (start_date, end_date),
        ).fetchone()
        return row["avg_return"] if row and row["n"] else None


def query_industry_map() -> dict[str, str]:
    """代號 → 產業別（取每檔最新一個月營收資料上的產業別）"""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT r.code, r.industry FROM month_revenue r
               JOIN (SELECT code, MAX(year_month) AS ym FROM month_revenue GROUP BY code) latest
                 ON r.code = latest.code AND r.year_month = latest.ym
               WHERE r.industry IS NOT NULL AND r.industry != ''"""
        )
        return {r["code"]: r["industry"] for r in cur.fetchall()}


def add_alert_rule(kind: str, code: str | None = None, name: str | None = None, threshold: float | None = None,
                   signal_key: str | None = None, note: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO alert_rules (kind, code, name, threshold, signal_key, enabled, note, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (kind, code or None, name, threshold, signal_key or None, note, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def set_alert_rule_enabled(rule_id: int, enabled: bool):
    with get_conn() as conn:
        conn.execute("UPDATE alert_rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id))


def delete_alert_rule(rule_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))


def query_alert_rules() -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM alert_rules ORDER BY id").fetchall()]


def save_alert_event(rule_id: int, event: dict) -> bool:
    """新觸發才寫入並回傳 True；同一規則同一檔同一天已經記過就回傳 False"""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO alert_events (rule_id, date, code, name, message, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rule_id, event["date"], event["code"], event.get("name"), event["message"],
             datetime.now().isoformat(timespec="seconds")),
        )
        return cur.rowcount == 1


def query_alert_events(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM alert_events ORDER BY date DESC, id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]


def save_shareholding(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO shareholding (date, code, level, holders, shares, pct)
               VALUES (:date, :code, :level, :holders, :shares, :pct)""",
            rows,
        )


# 集保分級 → 指標：千張以上＝第 15 級；400 張以上＝12–15 級；50 張以下散戶＝1–8 級；總人數＝第 17 級
_SHAREHOLDING_SUMMARY_SQL = """
    SELECT date, code,
           SUM(CASE WHEN level = 15 THEN pct END) AS big1000_pct,
           SUM(CASE WHEN level BETWEEN 12 AND 15 THEN pct END) AS big400_pct,
           SUM(CASE WHEN level BETWEEN 1 AND 8 THEN pct END) AS retail_pct,
           SUM(CASE WHEN level = 15 THEN holders END) AS big1000_holders,
           SUM(CASE WHEN level = 17 THEN holders END) AS total_holders
    FROM shareholding
"""


def query_shareholding_history(code: str, limit: int = 52) -> list[dict]:
    """單一股票每週的股權分散指標（由舊到新）"""
    with get_conn() as conn:
        cur = conn.execute(
            _SHAREHOLDING_SUMMARY_SQL + " WHERE code = ? GROUP BY date, code ORDER BY date DESC LIMIT ?",
            (code, limit),
        )
        return list(reversed([dict(r) for r in cur.fetchall()]))


def query_shareholding_dates() -> list[str]:
    with get_conn() as conn:
        return [r["date"] for r in conn.execute("SELECT DISTINCT date FROM shareholding ORDER BY date").fetchall()]


def query_shareholding_on(date: str) -> list[dict]:
    """某一週全部個股的股權分散指標"""
    with get_conn() as conn:
        cur = conn.execute(_SHAREHOLDING_SUMMARY_SQL + " WHERE date = ? GROUP BY date, code", (date,))
        return [dict(r) for r in cur.fetchall()]


def add_trade(date: str, code: str, name: str, side: str, shares: int, price: float, fee: float = 0,
              tax: float = 0, reason: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO trades (date, code, name, side, shares, price, fee, tax, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (date, code, name, side, shares, price, fee, tax, reason, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def update_trade(trade_id: int, **fields):
    allowed = {"date", "side", "shares", "price", "fee", "tax", "reason"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    with get_conn() as conn:
        conn.execute(f"UPDATE trades SET {', '.join(f'{k} = ?' for k in updates)} WHERE id = ?",
                     (*updates.values(), trade_id))


def delete_trade(trade_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
        conn.execute("DELETE FROM trade_reviews WHERE trade_id = ?", (trade_id,))


def query_trades(code: str | None = None) -> list[dict]:
    """交易紀錄，依日期與輸入順序由舊到新（平均成本法必須照時間順序計算）"""
    with get_conn() as conn:
        if code:
            cur = conn.execute("SELECT * FROM trades WHERE code = ? ORDER BY date, id", (code,))
        else:
            cur = conn.execute("SELECT * FROM trades ORDER BY date, id")
        return [dict(r) for r in cur.fetchall()]


def save_trade_review(trade_id: int, review: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO trade_reviews (trade_id, review, created_at) VALUES (?, ?, ?)",
                     (trade_id, review, datetime.now().isoformat(timespec="seconds")))


def query_trade_reviews() -> dict[int, dict]:
    with get_conn() as conn:
        return {r["trade_id"]: dict(r) for r in conn.execute("SELECT * FROM trade_reviews").fetchall()}
