import unittest
from unittest.mock import patch

from _db_fixture import TempDBTestCase
from src import collect_all
from src.storage import db


def _last_log():
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT step, status, detail FROM collect_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return tuple(row)


class CollectRecentGapsTests(TempDBTestCase):
    def test_nothing_to_fill_is_success(self):
        stats = {"filled": 0, "skipped": 10, "non_trading": 0, "failed": [], "requests": 0}
        with patch.object(collect_all.backfill, "fill_recent_gaps", return_value=stats):
            result = collect_all.collect_recent_gaps()
        self.assertEqual(result, {"filled": 0, "failed": 0})
        self.assertEqual(_last_log()[1:], ("success", "近期無缺漏"))

    def test_partial_failure_logged_as_failed(self):
        stats = {"filled": 2, "skipped": 0, "non_trading": 0, "failed": ["2026-09-01"], "requests": 7}
        with patch.object(collect_all.backfill, "fill_recent_gaps", return_value=stats):
            result = collect_all.collect_recent_gaps()
        self.assertEqual(result, {"filled": 2, "failed": 1})
        self.assertEqual(_last_log()[1], "failed")
        self.assertIn("補齊 2 天", _last_log()[2])

    def test_exception_does_not_propagate(self):
        with patch.object(collect_all.backfill, "fill_recent_gaps", side_effect=RuntimeError("boom")):
            result = collect_all.collect_recent_gaps()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(_last_log()[1:], ("failed", "boom"))


if __name__ == "__main__":
    unittest.main()
