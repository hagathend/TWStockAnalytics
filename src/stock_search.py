"""個股搜尋：輸入代號或名稱都可以，找不到完全相同的就找最接近的。

比對順序（越前面越優先）：
1. 代號完全相同
2. 名稱完全相同（忽略大小寫、空白、全半形、「台／臺」）
3. 名稱開頭相同 → 4. 名稱包含輸入的字 → 5. 代號開頭相同
   同一級裡成交值大的優先（輸入「聯」多半是找聯電、聯發科，不是冷門股），成交值相同時名稱短的優先
6. 都沒有時用字串相似度找錯字（例如「台積店」→ 台積電）
"""

import difflib
import unicodedata
from datetime import date as _date, timedelta

from src.storage import db

MAX_CANDIDATES = 8
_FUZZY_CUTOFF = 0.5
_LOOKBACK_DAYS = 30


def normalize(text: str) -> str:
    """全形轉半形、去空白、轉小寫，「臺」統一成「台」"""
    text = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(text.split()).lower().replace("臺", "台")


def search(query: str, names: dict[str, str], popularity: dict[str, float] | None = None) -> dict:
    """回傳 {"code": 最佳結果或 None, "exact": 是否完全相同, "candidates": [(代號, 名稱), ...]（不含最佳結果）}"""
    q = normalize(query)
    if not q:
        return {"code": None, "exact": False, "candidates": []}
    if q.upper() in names or q in names:
        code = q.upper() if q.upper() in names else q
        return {"code": code, "exact": True, "candidates": []}
    normalized = {code: normalize(name) for code, name in names.items()}
    exact = [c for c, n in normalized.items() if n == q]
    if exact:
        return {"code": exact[0], "exact": True, "candidates": []}

    popularity = popularity or {}

    def ordered(codes):
        return sorted(codes, key=lambda c: (-popularity.get(c, 0), len(normalized[c]), c))

    ranked = (ordered(c for c, n in normalized.items() if n.startswith(q))
              + ordered(c for c, n in normalized.items() if q in n and not n.startswith(q))
              + ordered(c for c in names if c.lower().startswith(q)))
    ranked = list(dict.fromkeys(ranked))
    if not ranked:
        by_name = {n: c for c, n in normalized.items()}
        ranked = [by_name[n] for n in difflib.get_close_matches(q, list(by_name), n=MAX_CANDIDATES + 1,
                                                                 cutoff=_FUZZY_CUTOFF)]
    if not ranked:
        return {"code": None, "exact": False, "candidates": []}
    return {"code": ranked[0], "exact": False,
            "candidates": [(c, names[c]) for c in ranked[1:MAX_CANDIDATES + 1]]}


def load_names(today: _date | None = None) -> tuple[dict[str, str], dict[str, float]]:
    """(代號→名稱, 代號→最新成交值)"""
    today = today or _date.today()
    rows = db.query_security_list((today - timedelta(days=_LOOKBACK_DAYS)).isoformat())
    return {r["code"]: r["name"] for r in rows}, {r["code"]: float(r["turnover"]) for r in rows}
