"""AI 供應商連線測試 + 文字生成呼叫。

連線測試用各家「列出模型」端點驗證 API Key 是否有效，不呼叫會計費的生成端點；
文字生成則是真正呼叫會計費的對話端點，供新聞分析等功能使用。

模型 ID 選用各家較便宜/快速的版本（畢竟會在每次收集資料後自動觸發），
如果之後要換更強的模型，改這裡的常數即可。
"""

import requests

PROVIDER_LABELS = {
    "claude": "Claude (Anthropic)",
    "gpt": "GPT (OpenAI)",
    "gemini": "Gemini (Google)",
}

_GENERATION_MODELS = {
    "claude": "claude-3-5-haiku-20241022",
    "gpt": "gpt-4o-mini",
    # 用 "-latest" 別名而非特定日期快照：實測 gemini-2.5-flash 這個快照對「新帳號」
    # 回傳 404「no longer available to new users」，即使 models.list() 有列出來也一樣叫不動；
    # gemini-flash-latest 這個別名永遠指向目前可用的最新 flash 模型，比較不會受個別快照下架影響
    "gemini": "gemini-flash-latest",
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


def _generate_claude(api_key: str, prompt: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=_GENERATION_MODELS["claude"],
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def _generate_gpt(api_key: str, prompt: str, max_tokens: int) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=_GENERATION_MODELS["gpt"],
        max_completion_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content or ""


def _generate_gemini(api_key: str, prompt: str, max_tokens: int) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=_GENERATION_MODELS["gemini"], contents=prompt
    )
    return resp.text or ""


_GENERATORS = {
    "claude": _generate_claude,
    "gpt": _generate_gpt,
    "gemini": _generate_gemini,
}


def generate_text(provider: str, api_key: str, prompt: str, max_tokens: int = 3000) -> tuple[bool, str]:
    """呼叫真正的生成端點（會計費）。回傳 (是否成功, 文字內容或錯誤訊息)"""
    if not api_key:
        return False, "尚未設定 API Key，請先到「AI 設定」頁輸入並儲存"
    generator = _GENERATORS.get(provider)
    if not generator:
        return False, f"未知的供應商: {provider}"
    try:
        text = generator(api_key, prompt, max_tokens)
        if not text.strip():
            return False, "AI 回傳了空白內容"
        return True, text
    except Exception as exc:  # noqa: BLE001 - 需要把任何底層SDK例外轉成使用者看得懂的訊息
        return False, f"AI 呼叫失敗: {exc}"


# --- Ollama（本機、免費，不需要 API Key）---
# 實測 qwen2.5:7b 在這個新聞分析任務上速度快、JSON schema 遵循度最高、繁體中文推理也清楚，
# 比同機安裝的 36B MoE 模型快十倍、比角色扮演微調版本可靠得多，故設為預設模型。

_OLLAMA_TIMEOUT = 180


def list_ollama_models(host: str) -> tuple[bool, list[str] | str]:
    """回傳 (是否成功, 模型名稱清單或錯誤訊息)"""
    try:
        resp = requests.get(f"{host}/api/tags", timeout=10)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return True, models
    except Exception as exc:  # noqa: BLE001 - 需要把連線例外轉成使用者看得懂的訊息
        return False, f"無法連到 Ollama ({host})：{exc}"


def generate_ollama_json(host: str, model: str, prompt: str, schema: dict) -> tuple[bool, str]:
    """用 Ollama 的 structured output（傳入 JSON schema 強制格式）呼叫本機模型。
    回傳 (是否成功, JSON文字或錯誤訊息)"""
    try:
        resp = requests.post(
            f"{host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "think": False,
            },
            timeout=_OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        if not text.strip():
            return False, "Ollama 回傳了空白內容（模型可能不支援 structured output，或思考時間耗盡）"
        return True, text
    except Exception as exc:  # noqa: BLE001 - 需要把任何底層例外轉成使用者看得懂的訊息
        return False, f"Ollama 呼叫失敗: {exc}"


def generate_ollama_text(host: str, model: str, prompt: str) -> tuple[bool, str]:
    """呼叫本機模型產生一般文字（不強制JSON格式），用於逐篇新聞摘要這種單純文字輸出的任務。
    回傳 (是否成功, 文字內容或錯誤訊息)"""
    try:
        resp = requests.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "think": False},
            timeout=_OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()
        if not text:
            return False, "Ollama 回傳了空白內容"
        return True, text
    except Exception as exc:  # noqa: BLE001 - 需要把任何底層例外轉成使用者看得懂的訊息
        return False, f"Ollama 呼叫失敗: {exc}"
