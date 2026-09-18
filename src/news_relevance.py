"""新聞與個股的關聯判斷：摘要前先用程式過濾，沒提到任何上市櫃公司的新聞不送 AI 摘要（省 Codex 額度）。

鉅亨網台股分類一天約 125 則，其中大半是總經、保險、生活消費新聞。用本地股價資料裡的公司名稱與代號
比對標題與內文，找出每則提到哪些公司；比對純粹字串，不花 AI 額度。
"""

import re

from src.storage import db

# 名稱只有一個字的不比對；下面這些公司簡稱同時是常用詞（「全台」「大量」「世界」「創意」…），
# 用 2026-09 鉅亨網新聞實測誤判最多的挑出來，只認「名稱(代號)」或單獨出現代號的寫法
_MIN_NAME_LENGTH = 2
_AMBIGUOUS_NAMES = {
    "全台", "中華", "大量", "全新", "世界", "國產", "新興", "時報", "大成", "統一", "卓越", "大甲", "數字",
    "資通", "創意", "安心", "聯合", "互動", "台南", "冠軍", "大同", "新產", "光明", "中興", "永大", "三星",
    "大華", "台灣", "國際", "中國", "亞洲", "台北", "高雄", "精英", "華新", "東南", "遠東", "長興", "正道",
    # 2026-09-18 實測：常用詞或會出現在其他詞中間（「以及成長」→及成、「整合機」→合機）
    "巨大", "全國", "幸福", "新建", "精確", "進階", "地球", "中天", "信實", "及成", "合機", "中工", "華夏",
    "高技", "為升", "力士", "合一", "中電", "信義", "東洋", "京城", "根基", "霹靂", "國建", "星通", "鼎元",
}
# 看起來像年份的代號（1990～2035，例如「(2025)」）只在前面緊接著公司名稱時才算
_YEAR_LIKE = range(1990, 2036)
_NAME_BEFORE_CODE_CHARS = 8
# 代號只認新聞常見的寫法：「(2330)」「（2330）」「(2330-TW)」「2330.TW」；單獨的四位數多半是年份或金額
# （2025～2030 剛好是千興、大成鋼、彰源等公司的代號，不能直接比對）
_CODE_PATTERN = re.compile(r"[(（]\s*(\d{4}[A-Z]?)\*?\s*(?:[-.]TWO?)?\s*[)）]|(?<![\d.])(\d{4}[A-Z]?)[-.]TWO?(?![A-Za-z])")


def build_company_index() -> dict[str, str]:
    """{代號: 名稱}：最近一次收集到的上市櫃個股（排除 ETF、權證）"""
    return db.query_stock_names()


_SUFFIX = re.compile(r"(-KY|-創|-DR|\*)$")


def _name_patterns(index: dict[str, str]) -> list[tuple[str, str]]:
    """[(代號, 要比對的名稱)]，由長到短。名稱帶「-KY」「-創」「*」的另外比對去掉後綴的寫法（標題常省略）"""
    patterns = []
    for code, name in index.items():
        for candidate in dict.fromkeys([name, _SUFFIX.sub("", name or "")]):
            if candidate and len(candidate) >= _MIN_NAME_LENGTH and candidate not in _AMBIGUOUS_NAMES:
                patterns.append((code, candidate))
    return sorted(patterns, key=lambda item: -len(item[1]))


def mentioned_companies(text: str, index: dict[str, str]) -> list[str]:
    """text 裡提到的公司代號（依第一次出現的位置排序、不重複）。
    - 代號要是真的存在的個股代號才算
    - 名稱由長到短比對，比對到的文字就遮掉：「聯發科」不會再被當成「聯發」、「南亞科」不會變成「南亞」
    - 太短或和常用詞重疊的名稱不比對（見 _AMBIGUOUS_NAMES）"""
    if not text or not index:
        return []
    positions: dict[str, int] = {}
    for match in _CODE_PATTERN.finditer(text):
        code = match.group(1) or match.group(2)
        if code not in index:
            continue
        if code[:4].isdigit() and int(code[:4]) in _YEAR_LIKE:
            before = text[max(0, match.start() - _NAME_BEFORE_CODE_CHARS):match.start()]
            if index[code] not in before:
                continue
        positions.setdefault(code, match.start())
    masked = text
    for code, name in _name_patterns(index):
        found = masked.find(name)
        if found < 0:
            continue
        positions.setdefault(code, found)
        masked = masked.replace(name, " " * len(name))
    return sorted(positions, key=positions.get)


def relevance(article: dict, index: dict[str, str]) -> tuple[int, int, list[str]]:
    """(標題提到的公司數, 全文提到的公司數, 代號清單)：用來排序，標題就點名公司的最相關"""
    title_codes = mentioned_companies(article.get("title") or "", index)
    body = " ".join(filter(None, [article.get("summary"), article.get("content")]))
    codes = list(dict.fromkeys(title_codes + mentioned_companies(body, index)))
    return len(title_codes), len(codes), codes


def select_stock_news(rows: list[dict], index: dict[str, str], limit: int) -> list[dict]:
    """只保留有提到公司的新聞，標題點名公司的優先、提到越多公司越前面，同分維持原本（新到舊）順序。
    沒有公司資料可比對時（例如還沒收集過股價）不過濾，直接取前 limit 則"""
    if not index:
        return rows[:limit]
    scored = []
    for order, row in enumerate(rows):
        title_count, total, _ = relevance(row, index)
        if total:
            scored.append((-min(title_count, 1), -total, order, row))
    scored.sort(key=lambda item: item[:3])
    return [row for *_, row in scored[:limit]]


MAX_RELATED_CODES = 5


def related_codes(title: str, excerpt: str | None, index: dict[str, str]) -> str | None:
    """新聞的「關聯代號」：標題點名的公司，加上 AI 逐篇摘要點名的公司（摘要通常寫成「環宇-KY(4991)」）。
    不看全文：盤勢新聞的內文會列出一大串公司，全部算關聯反而失去意義。多檔用逗號分隔，最多 5 檔"""
    codes = mentioned_companies(title or "", index) + mentioned_companies(excerpt or "", index)
    codes = list(dict.fromkeys(codes))[:MAX_RELATED_CODES]
    return ",".join(codes) or None


def merge_related(existing: str | None, extra: str | None) -> str | None:
    codes = [c for c in (existing or "").split(",") + (extra or "").split(",") if c]
    return ",".join(list(dict.fromkeys(codes))[:MAX_RELATED_CODES]) or None


def fill_missing_related_codes() -> int:
    """把還沒有關聯代號的新聞補上（每日收集時呼叫，只補空的、不覆蓋既有值）。回傳補了幾則"""
    index = build_company_index()
    if not index:
        return 0
    filled = 0
    for row in db.query_news_without_related_code():
        codes = related_codes(row["title"], row["excerpt"], index)
        if codes:
            db.update_news_related_code(row["id"], codes)
            filled += 1
    return filled
