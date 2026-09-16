import base64
import unittest
from unittest.mock import patch

from _db_fixture import TempDBTestCase, price_row
from src import alerts, notify
from src.storage import db


def _price(date, code, close, change, name="測試"):
    row = price_row(date, code=code, name=name, close=close)
    row["change"] = change
    return row


class AlertCheckTests(TempDBTestCase):
    def setUp(self):
        super().setUp()
        db.save_stock_price([
            _price("2026-09-15", "2330", 100.0, 0.0, "台積電"),
            _price("2026-09-16", "2330", 110.0, 10.0, "台積電"),   # +10%
            _price("2026-09-16", "2317", 45.0, -5.0, "鴻海"),      # -10%
            _price("2026-09-15", "6488", 500.0, 50.0, "環球晶"),   # 沒有 9/16 的價格
        ])
        self._notify = patch.object(alerts.notify, "show_toast", return_value=(True, "ok"))
        self.toast = self._notify.start()

    def tearDown(self):
        self._notify.stop()
        super().tearDown()

    def test_price_and_change_rules(self):
        db.add_alert_rule("price_above", "2330", threshold=105)
        db.add_alert_rule("price_below", "2330", threshold=90)       # 不觸發
        db.add_alert_rule("change_below", "2317", threshold=8)
        db.add_alert_rule("change_above", "6488", threshold=5)       # 價格日期落後，不能用舊漲幅觸發
        outcome = alerts.check_alerts()
        messages = [e["message"] for e in outcome["new_events"]]
        self.assertEqual(len(messages), 2, messages)
        self.assertIn("已高於 105.00", messages[0])
        self.assertIn("今日下跌 -10.00%", messages[1])
        self.toast.assert_called_once()
        self.assertIn("2 則提醒", self.toast.call_args[0][0])

    def test_same_day_not_triggered_twice(self):
        db.add_alert_rule("price_above", "2330", threshold=105)
        self.assertEqual(len(alerts.check_alerts()["new_events"]), 1)
        again = alerts.check_alerts()
        self.assertEqual(again["new_events"], [])
        self.assertEqual(self.toast.call_count, 1)
        self.assertEqual(len(db.query_alert_events()), 1)

    def test_disabled_rule_ignored(self):
        rule_id = db.add_alert_rule("price_above", "2330", threshold=105)
        db.set_alert_rule_enabled(rule_id, False)
        self.assertEqual(alerts.check_alerts()["message"], "沒有啟用中的提醒規則")

    def test_holding_loss_for_all_holdings(self):
        db.add_holding("2317", "鴻海", 1000, 60.0, "2026-09-01")   # 45 / 60 → -25%
        db.add_holding("2330", "台積電", 1000, 100.0, "2026-09-01")  # +10%
        db.add_alert_rule("holding_loss", threshold=8)
        db.add_alert_rule("holding_gain", "2330", threshold=5)
        messages = [e["message"] for e in alerts.check_alerts()["new_events"]]
        self.assertEqual(len(messages), 2)
        self.assertTrue(any("鴻海" in m and "-25.00%" in m for m in messages))
        self.assertTrue(any("台積電" in m and "獲利已超過 5%" in m for m in messages))

    def test_watchlist_signal_rule_filters_signal(self):
        watch = [{"code": "2330", "name": "台積電", "date": "2026-09-16", "close": 110, "change_pct": 10,
                  "new": ["breakout_20d", "gap_up"], "continuing": []}]
        db.add_alert_rule("watchlist_signal", signal_key="gap_up")
        with patch.object(alerts.signals, "watchlist_alerts", return_value=watch), \
                patch.object(alerts.signals, "load_signal_history"):
            events = alerts.check_alerts()["new_events"]
        self.assertEqual(len(events), 1)
        self.assertIn("跳空上漲缺口", events[0]["message"])
        self.assertNotIn("突破20日新高", events[0]["message"])

    def test_describe_rule(self):
        self.assertEqual(alerts.describe_rule({"kind": "holding_loss", "code": None, "threshold": 8.0}),
                         "所有持股：持股虧損超過 8%")
        self.assertIn("任何訊號", alerts.describe_rule({"kind": "watchlist_signal", "signal_key": None}))


class NotifyTests(unittest.TestCase):
    def test_xml_escaping_and_line_limit(self):
        xml = notify.build_toast_xml("A & B", ["<1>", "第二則", "第三則", "第四則"])
        self.assertIn("A &amp; B", xml)
        self.assertIn("&lt;1&gt;", xml)
        self.assertIn("…等共 4 則", xml)
        self.assertNotIn("第三則", xml)

    def test_script_is_passed_encoded(self):
        with patch.object(notify.subprocess, "run") as run:
            run.return_value.returncode = 0
            notify.show_toast("標題 'quote'", ["內容"])
        args = run.call_args[0][0]
        script = base64.b64decode(args[args.index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertIn("標題 ''quote''", script)  # PowerShell 單引號跳脫


if __name__ == "__main__":
    unittest.main()
