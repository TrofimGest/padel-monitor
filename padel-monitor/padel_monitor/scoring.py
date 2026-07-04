"""LLM-слой: двухступенчатый, оптимальный по цене.

1. text_score  — Haiku 4.5, массовый скоринг новых объявлений (ежедневно).
2. vision_screen — Haiku 4.5, скрининг фото кандидатов недели: высота,
   колонны, пролёт. Результат кешируется в scores.vision_notes.
3. judge — Opus 4.8, один вызов в неделю: сравнивает финалистов между собой
   и с прошлыми лидерами, ставит финальный score 0-100.

Без ANTHROPIC_API_KEY весь слой выключен — работает эвристика из rules.py.
LLM не переопределяет жёсткие правила: судья видит только прошедших фильтр.
"""

import json

import anthropic

PADEL_CONTEXT = """Ты эксперт по подбору помещений под ПАДЕЛ-КЛУБ в Минске (1-2 корта).
Требования: корт 20x10 м (с конструкцией ~11x21 м на корт, ~231 м²), высота
потолка минимум 6 м без препятствий (лучше 8+), над кортом НЕ должно быть колонн,
помещение должно отапливаться (клуб круглогодичный). Под ремонт — допустимо.
Гигантские помещения (2000+ м²) целиком не подходят, если нельзя арендовать часть.
Желательно: 1 этаж, отдельный вход, парковка, близость метро/МКАД."""

TEXT_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "verdict": {"type": "string", "enum": ["подходит", "сомнительно", "не подходит"]},
        "why": {"type": "string"},
        "risks": {"type": "string"},
        "ask": {"type": "string"},
    },
    "required": ["score", "verdict", "why", "risks", "ask"],
    "additionalProperties": False,
}

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "height_estimate_m": {"type": ["number", "null"]},
        "columns": {"type": "string", "enum": ["нет", "есть", "не видно"]},
        "open_span": {"type": "string", "enum": ["да", "нет", "не видно"]},
        "heated_hint": {"type": "string", "enum": ["похоже отапливаемое", "похоже холодное", "не видно"]},
        "condition": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["height_estimate_m", "columns", "open_span", "heated_hint",
                 "condition", "note"],
    "additionalProperties": False,
}

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "final_score": {"type": "integer"},
                    "verdict": {"type": "string",
                                "enum": ["смотреть срочно", "стоит посмотреть",
                                         "сомнительно", "не подходит"]},
                    "why": {"type": "string"},
                    "risks": {"type": "string"},
                    "vs_previous": {"type": "string"},
                },
                "required": ["id", "final_score", "verdict", "why", "risks",
                             "vs_previous"],
                "additionalProperties": False,
            },
        },
        "week_summary": {"type": "string"},
    },
    "required": ["verdicts", "week_summary"],
    "additionalProperties": False,
}


def _client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def _json_output(schema: dict) -> dict:
    return {"format": {"type": "json_schema", "schema": schema}}


def _parse(response) -> dict | None:
    if response.stop_reason == "refusal":
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _listing_brief(row: dict) -> dict:
    keys = ("title", "description", "area_m2", "area_min_m2", "ceiling_height_m",
            "heated", "price_byn", "price_usd", "price_per_m2", "address",
            "property_type", "floor", "floors", "metro", "attrs")
    return {k: row.get(k) for k in keys}


def text_score(api_key: str, model: str, row: dict) -> dict | None:
    """Haiku: быстрая оценка одного объявления по тексту."""
    try:
        resp = _client(api_key).messages.create(
            model=model, max_tokens=1024,
            system=PADEL_CONTEXT,
            output_config=_json_output(TEXT_SCORE_SCHEMA),
            messages=[{"role": "user", "content":
                       "Оцени пригодность объявления (score 0-100). Данные:\n"
                       + json.dumps(_listing_brief(row), ensure_ascii=False)}],
        )
        return _parse(resp)
    except anthropic.APIError:
        return None


def vision_screen(api_key: str, model: str, image_urls: list[str],
                  max_images: int = 4) -> dict | None:
    """Haiku: что видно на фото — высота, колонны, пролёт, отопление."""
    content: list[dict] = [
        {"type": "image", "source": {"type": "url", "url": u}}
        for u in image_urls[:max_images]]
    if not content:
        return None
    content.append({"type": "text", "text":
                    "Оцени помещение на фото по падел-критериям. Оценки по фото — "
                    "гипотеза: если не видно, так и отвечай."})
    try:
        resp = _client(api_key).messages.create(
            model=model, max_tokens=1024,
            system=PADEL_CONTEXT,
            output_config=_json_output(VISION_SCHEMA),
            messages=[{"role": "user", "content": content}],
        )
        return _parse(resp)
    except anthropic.APIError:
        return None


def judge(api_key: str, model: str, candidates: list[dict],
          previous_leaders: list[dict]) -> dict | None:
    """Opus: финальное ранжирование недели и сравнение с прошлыми лидерами.

    candidates: [{id, listing: {...}, text_review: {...}, photos: {...}}]
    previous_leaders: [{listing: {...}, final_score, judge_why}]
    """
    payload = {
        "кандидаты_этой_недели": candidates,
        "лучшие_варианты_прошлых_недель": previous_leaders or
            "пока нет — это первый осмысленный отчёт",
    }
    prompt = (
        "Ниже кандидаты этой недели (прошли жёсткий фильтр; есть текстовая оценка "
        "и анализ фото) и лучшие варианты прошлых недель для сравнения.\n"
        "Для каждого кандидата дай final_score 0-100 и вердикт. Будь строг: "
        "score 80+ только если высота и отсутствие колонн подтверждены и площадь "
        "адекватна 1-2 кортам. Неотапливаемое или высота <6 м — максимум 50. "
        "В vs_previous одной фразой сравни с прошлыми лидерами (лучше/хуже и чем); "
        "если прошлых нет — насколько хорош вариант в абсолюте.\n"
        "В week_summary 2-3 предложения: общий итог недели и что смотреть в первую "
        "очередь.\n\n" + json.dumps(payload, ensure_ascii=False)
    )
    try:
        resp = _client(api_key).messages.create(
            model=model, max_tokens=8192,
            thinking={"type": "adaptive"},
            system=PADEL_CONTEXT,
            output_config=_json_output(JUDGE_SCHEMA),
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse(resp)
    except anthropic.APIError:
        return None
