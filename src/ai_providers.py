"""AI 供應商連線測試。使用各家「列出模型」端點驗證 API Key 是否有效，
不呼叫會計費的生成端點。"""

PROVIDER_LABELS = {
    "claude": "Claude (Anthropic)",
    "gpt": "GPT (OpenAI)",
    "gemini": "Gemini (Google)",
}


def _test_claude(api_key: str) -> tuple[bool, str]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    models = client.models.list()
    names = [m.id for m in models.data[:3]]
    return True, f"連線成功，可用模型範例: {', '.join(names)}"


def _test_gpt(api_key: str) -> tuple[bool, str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    models = client.models.list()
    names = [m.id for m in list(models)[:3]]
    return True, f"連線成功，可用模型範例: {', '.join(names)}"


def _test_gemini(api_key: str) -> tuple[bool, str]:
    from google import genai

    client = genai.Client(api_key=api_key)
    models = list(client.models.list())
    names = [m.name for m in models[:3]]
    return True, f"連線成功，可用模型範例: {', '.join(names)}"


_TESTERS = {"claude": _test_claude, "gpt": _test_gpt, "gemini": _test_gemini}


def test_connection(provider: str, api_key: str) -> tuple[bool, str]:
    if not api_key:
        return False, "尚未輸入 API Key"
    tester = _TESTERS.get(provider)
    if not tester:
        return False, f"未知的供應商: {provider}"
    try:
        return tester(api_key)
    except Exception as exc:  # noqa: BLE001 - 連線測試需要把任何底層SDK例外轉成使用者看得懂的訊息
        return False, f"連線失敗: {exc}"
