"""Жёсткие правила падел-профиля + эвристический скоринг.

Правила отсеивают до LLM. Отсутствие высоты потолка НЕ отсеивает —
помечается height_unknown и уточняется по фото (vision).
"""

import re

from .normalize import Listing


def apply_rules(lst: Listing, profile: dict) -> tuple[bool, str, list[str]]:
    """Возвращает (прошло, причина отказа, флаги)."""
    flags: list[str] = []
    text = f"{lst.title} {lst.description}".lower()
    place = f"{lst.town} {lst.district} {lst.region} {lst.address}".lower()

    if not any(r in place for r in profile["regions"]):
        return False, f"регион: {lst.town or lst.address or '?'}", flags

    if lst.area_m2 is not None and lst.area_m2 < profile["min_area_m2"]:
        return False, f"площадь {lst.area_m2:.0f} м² < {profile['min_area_m2']}", flags
    if lst.area_m2 is None:
        flags.append("area_unknown")

    h = lst.ceiling_height_m
    if h is not None and h < profile["min_height_m"]:
        return False, f"высота {h} м < {profile['min_height_m']}", flags
    if h is None:
        flags.append("height_unknown")
    elif h < profile["good_height_m"]:
        flags.append("height_borderline")

    for kw in profile["exclude_keywords"]:
        if re.search(rf"\b{kw}", text):
            return False, f"исключение: «{kw}»", flags

    if lst.floor is not None and lst.floor < 1:
        return False, "подвал/цоколь (этаж < 1)", flags
    if lst.floor is not None and lst.floor > 1:
        flags.append("upper_floor")

    if lst.area_m2 and lst.area_m2 >= profile["two_courts_area_m2"]:
        flags.append("two_courts")
    return True, "", flags


GOOD_TYPES = ("склад", "производ", "промышлен", "услуг", "свободн", "спорт")
BAD_TYPES = ("офис",)


def heuristic_score(lst: Listing, flags: list[str], profile: dict) -> int:
    s = 50
    h = lst.ceiling_height_m
    if h is not None:
        if h >= profile["great_height_m"]:
            s += 25
        elif h >= profile["good_height_m"]:
            s += 15
        else:
            s -= 10
    if "two_courts" in flags:
        s += 10
    if lst.floor == 1:
        s += 8
    if "upper_floor" in flags:
        s -= 10
    pt = lst.property_type.lower()
    if any(t in pt for t in GOOD_TYPES):
        s += 8
    if any(t in pt for t in BAD_TYPES):
        s -= 12
    a = lst.attrs
    s += 5 * bool(a.get("parking"))
    s += 5 * bool(a.get("separate_entrance"))
    s += 8 * bool(a.get("no_columns"))
    s += 4 * bool(a.get("sport_hint"))
    s += 3 * bool(a.get("hangar_hint"))
    s += 3 * bool(lst.metro)
    if a.get("columns") and not a.get("no_columns"):
        s -= 5  # колонны упомянуты — надо смотреть шаг
    return max(0, min(100, s))
