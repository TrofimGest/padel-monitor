"""Нормализованное объявление и извлечение падел-критичных признаков из текста."""

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str = ""
    description: str = ""
    price_byn: float | None = None   # BYN/мес
    price_usd: float | None = None
    price_per_m2: float | None = None
    area_m2: float | None = None
    address: str = ""
    town: str = ""
    district: str = ""
    region: str = ""
    property_type: str = ""
    floor: int | None = None
    floors: int | None = None
    ceiling_height_m: float | None = None
    metro: str = ""
    published_at: str = ""
    updated_at: str = ""
    images: list[str] = field(default_factory=list)
    attrs: dict = field(default_factory=dict)  # парковка, отд. вход и пр.

    def content_hash(self) -> str:
        key = json.dumps(
            [self.price_byn, self.price_usd, self.price_per_m2, self.area_m2,
             self.title, self.description[:500]],
            ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def to_row(self) -> dict:
        d = asdict(self)
        d["images"] = json.dumps(self.images, ensure_ascii=False)
        d["attrs"] = json.dumps(self.attrs, ensure_ascii=False)
        d["content_hash"] = self.content_hash()
        return d


HEIGHT_RE = re.compile(
    r"(?:высот\w*|потол\w*)\D{0,25}?(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:м\b|метр)",
    re.IGNORECASE)
HEIGHT_RE2 = re.compile(
    r"(\d{1,2}(?:[.,]\d{1,2})?)\s*(?:м\b|метр\w*)\s*(?:—|-|:)?\s*(?:высот|потол)",
    re.IGNORECASE)


def extract_height_m(text: str) -> float | None:
    for rx in (HEIGHT_RE, HEIGHT_RE2):
        m = rx.search(text)
        if m:
            v = float(m.group(1).replace(",", "."))
            if 2.0 <= v <= 30.0:
                return v
    return None


TEXT_FLAGS = {
    "parking": r"парковк|стоянк|паркинг",
    "separate_entrance": r"отдельн\w+ вход",
    "no_columns": r"без колонн|бесколонн",
    "columns": r"\bколонн",
    "ramp": r"\bрамп|пандус",
    "gate": r"ворот",
    "heating": r"отоплен|отаплива",
    "sport_hint": r"спорт|фитнес|зал\b|трениров|падел|теннис",
    "hangar_hint": r"ангар|цех\b|склад",
}


def extract_text_flags(text: str) -> dict:
    low = text.lower()
    return {k: bool(re.search(rx, low)) for k, rx in TEXT_FLAGS.items()}
