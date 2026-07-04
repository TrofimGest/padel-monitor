"""LLM-скоринг текста и vision-анализ фото через Anthropic API.

Оба слоя опциональны: без ANTHROPIC_API_KEY система работает на
эвристическом скоринге (rules.heuristic_score), отчёт это помечает.
LLM не переопределяет жёсткие правила — только уточняет score/пояснение.
"""

import json

import httpx

API_URL = "https://api.anthropic.com/v1/messages"

SCORE_PROMPT = """Ты оцениваешь объявление аренды помещения под ПАДЕЛ-КЛУБ в Минске (1-2 корта).
Корт 20x10 м (с конструкцией ~11x21 м на корт), высота потолка минимум 6 м без препятствий,
над кортом не должно быть колонн. Под ремонт — допустимо.

Объявление:
{listing}

Ответь строго JSON-объектом:
{{"score": 0-100, "verdict": "подходит|сомнительно|не подходит",
"why": "1-2 предложения почему", "risks": "главные риски/что не указано",
"ask": "что спросить у арендодателя"}}"""

VISION_PROMPT = """По фотографиям помещения оцени пригодность под падел-корт (20x10 м, высота 6+ м).
Ответь строго JSON: {"height_estimate_m": число или null, "columns": "нет|есть|не видно",
"open_span": "да|нет|не видно", "condition": "краткое состояние",
"note": "1-2 предложения: что видно на фото, критично для падела"}"""


def _call(api_key: str, model: str, content, max_tokens=500) -> dict | None:
    r = httpx.post(API_URL, timeout=120, headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }, json={"model": model, "max_tokens": max_tokens,
             "messages": [{"role": "user", "content": content}]})
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json()["content"])
    start, end = text.find("{"), text.rfind("}")
    if start == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def llm_score(api_key: str, model: str, row: dict) -> dict | None:
    listing = json.dumps(
        {k: row[k] for k in ("title", "description", "area_m2", "ceiling_height_m",
                             "price_byn", "price_usd", "price_per_m2", "address",
                             "property_type", "floor", "floors", "attrs")},
        ensure_ascii=False)
    try:
        return _call(api_key, model, SCORE_PROMPT.format(listing=listing))
    except httpx.HTTPError:
        return None


def vision_analyze(api_key: str, model: str, image_urls: list[str],
                   max_images: int = 4) -> dict | None:
    content: list[dict] = [
        {"type": "image", "source": {"type": "url", "url": u}}
        for u in image_urls[:max_images]]
    if not content:
        return None
    content.append({"type": "text", "text": VISION_PROMPT})
    try:
        return _call(api_key, model, content)
    except httpx.HTTPError:
        return None
