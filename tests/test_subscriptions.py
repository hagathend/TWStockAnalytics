import unittest
from datetime import date

from src import subscriptions

FIELDS = ["序號", "抽籤日期", "證券名稱", "證券代號", "發行市場", "申購開始日", "申購結束日", "承銷股數", "實際承銷股數",
          "承銷價(元)", "實際承銷價(元)", "撥券日期(上市、上櫃日期)", "主辦券商", "申購股數", "總承銷金額(元)", "總合格件",
          "中籤率(%)", "取消公開抽籤 "]


def _row(code, draw, start, end, price, actual, rate="0", cancelled=""):
    return ["1", draw, f"股{code}", code, "上市增資", start, end, "1,000,000", "1,000,000", price, actual, "115/10/01",
            "凱基", "1,000", "0", "0", rate, cancelled]


PAYLOAD = {"stat": "OK", "fields": FIELDS, "data": [
    _row("1111", "115/09/30", "115/09/22", "115/09/24", "24", "未訂出"),          # 即將開始，實際價未訂出
    _row("2222", "115/09/21", "115/09/15", "115/09/17", "138", "138"),           # 已截止、待抽籤
    _row("3333", "115/09/23", "115/09/18", "115/09/21", "50", "50"),             # 申購中
    _row("4444", "115/09/16", "115/09/10", "115/09/14", "110", "110", "0.33"),   # 已抽籤
    _row("5555", "115/09/10", "115/09/04", "115/09/08", "30", "30", "1.2"),      # 已抽籤，較早
    _row("6666", "115/08/01", "115/07/28", "115/07/30", "30", "30", "1.2"),      # 太久以前
    _row("7777", "115/09/30", "115/09/22", "115/09/24", "30", "30", "", "取消"),  # 取消抽籤
]}


class SubscriptionTest(unittest.TestCase):
    def test_parse(self):
        rows = {r["code"]: r for r in subscriptions.parse(PAYLOAD)}
        self.assertNotIn("7777", rows)
        self.assertEqual(rows["1111"]["price"], 24.0)          # 實際承銷價未訂出，用公告價
        self.assertEqual(rows["1111"]["draw_date"], "2026-09-30")
        self.assertIsNone(rows["1111"]["win_rate"])
        self.assertEqual(rows["4444"]["win_rate"], 0.33)
        self.assertEqual(subscriptions.parse({"stat": "查無資料"}), [])

    def test_schedule(self):
        table = subscriptions.schedule(subscriptions.parse(PAYLOAD), date(2026, 9, 19), {"2222": 150.0})
        self.assertEqual(list(table["code"]), ["3333", "1111", "2222", "4444", "5555"])
        self.assertEqual(list(table["status"]), ["申購中", "即將開始", "待抽籤", "已抽籤", "已抽籤"])
        row = table.set_index("code").loc["2222"]
        self.assertAlmostEqual(row["spread_pct"], 12 / 138 * 100)
        self.assertAlmostEqual(row["spread_per_lot"], 12 * 1000)

    def test_empty(self):
        self.assertTrue(subscriptions.schedule([], date(2026, 9, 19), {}).empty)


if __name__ == "__main__":
    unittest.main()
