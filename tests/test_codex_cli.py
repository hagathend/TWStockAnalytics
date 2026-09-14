import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from src.codex_cli import generate_codex_text, _strict_schema
from src.ai_analysis import analyze_with_codex_deep


class CodexTests(unittest.TestCase):
    @patch("src.codex_cli._executable", return_value="codex.exe")
    @patch("src.codex_cli.subprocess.run")
    def test_output_file_and_stdin(self, run, executable):
        def fake(args, **kwargs):
            self.assertEqual(args[-1], "-")
            self.assertIn("新聞中文", kwargs["input"])
            self.assertIn("read-only", args)
            Path(args[args.index("-o") + 1]).write_text("分析完成", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "event log", "")
        run.side_effect = fake
        self.assertEqual(generate_codex_text("新聞中文"), (True, "分析完成"))

    @patch("src.codex_cli._executable", return_value=None)
    def test_missing_executable(self, executable):
        self.assertFalse(generate_codex_text("test")[0])

    @patch("src.codex_cli._executable", return_value="codex.exe")
    @patch("src.codex_cli.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 1))
    def test_timeout(self, run, executable):
        ok, message = generate_codex_text("test")
        self.assertFalse(ok)
        self.assertIn("逾時", message)

    @patch("src.codex_cli._executable", return_value="codex.exe")
    @patch("src.codex_cli.subprocess.run")
    def test_empty_output_is_failure(self, run, executable):
        run.return_value = subprocess.CompletedProcess([], 0, "not an answer", "")
        self.assertFalse(generate_codex_text("test")[0])

    def test_nested_schema(self):
        original = {"type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": {"name": {"type": "string"}}}}}}
        result = _strict_schema(original)
        self.assertFalse(result["additionalProperties"])
        self.assertFalse(result["properties"]["items"]["items"]["additionalProperties"])
        self.assertNotIn("additionalProperties", original)

    @patch("src.ai_analysis._save_result")
    @patch("src.ai_analysis._gather_and_summarize", side_effect=RuntimeError("額度不足"))
    def test_failed_news_preserves_previous_result(self, gather, save):
        self.assertFalse(analyze_with_codex_deep("2026-09-13")["ok"])
        save.assert_not_called()

    @patch("src.ai_analysis._save_result", return_value={"ok": True})
    @patch("src.ai_analysis._select_top_picks", return_value=(None, "摘要", []))
    @patch("src.ai_analysis._gather_and_summarize", return_value=(None, ["摘要"], [{"excerpt": "摘要"}]))
    def test_news_saves_codex_provider(self, gather, select, save):
        result = analyze_with_codex_deep("2026-09-13")
        save.assert_called_once_with("2026-09-13", "codex-cli", "摘要", [])
        self.assertEqual(result["article_excerpts"], [{"excerpt": "摘要"}])


if __name__ == "__main__":
    unittest.main()
