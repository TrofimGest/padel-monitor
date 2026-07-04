"""Жёсткие правила падел-профиля + эвристический pre-score.

Правила отсеивают до LLM. Эвристика теперь только ранжирует кандидатов
для vision/судьи, финальный score ставит LLM-судья (scoring.judge).

Уроки первого отчёта: гигантские неотапливаемые склады получали 100/100.
Исправлено: полоса «оптимальной» площади вместо бонуса за размер, штраф за
отсутствие отопления, потолок score при неизвестной высоте (до проверки фото).
"""

import re

from .normalize import Listing


def effective_area(lst: Listing) -> float | None:
    """Минимальный сдаваемый кусок: для «от 500 м² из 16000» решает 500."""
    candidates = [a for a in (lst.area_min_m2, lst.area_m2) if a]
    return min(candidates) if candidates else None


def apply_rules(lst: Listing, profile: dict) -> tuple[bool, str, list[str]]:
    """Возвращает (прошло, причина отказа, флаги)."""
    flags: list[str] = []
    text = f"{lst.title} {lst.description}".lower()
    place = f"{lst.town} {lst.district} {lst.region} {lst.address}".lower()

    if not any(r in place for r in profile["regions"]):
        return False, f"регион: {lst.town or lst.address or '?'}", flags

    area = effective_area(lst)
    if area is not None and lst.area_m2 and area < lst.area_m2:
        flags.append("divisible")  # можно арендовать часть
    if area is not None and lst.area_m2 and lst.area_m2 < profile["min_area_m2"]:
        # общая площадь мала — «от X» тут не спасает
        area = lst.area_m2
    if lst.area_m2 is not None and lst.area_m2 < profile["min_area_m2"]:
        return False, f"площадь {lst.area_m2:.0f} м² < {profile['min_area_m2']}", flags
    if area is None:
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

    if lst.heated is False:
        flags.append("unheated")
    elif lst.heated is None:
        flags.append("heating_unknown")

    if lst.area_m2 and lst.area_m2 > profile.get("huge_area_m2", 2000) \
            and "divisible" not in flags:
        flags.append("oversized")

    if area and profile["two_courts_area_m2"] <= area <= profile.get("area_ideal_max_m2", 1200):
        flags.append("two_courts")
    return True, "", flags


GOOD_TYPES = ("склад", "производ", "промышлен", "услуг", "свободн", "спорт")
BAD_TYPES = ("офис",)


def heuristic_score(lst: Listing, flags: list[str], profile: dict) -> int:
    """Pre-score для ранжирования кандидатов. Финальную оценку даёт судья."""
    s = 40
    h = lst.ceiling_height_m
    if h is not None:
        if h >= profile["great_height_m"]:
            s += 22
        elif h >= profile["good_height_m"]:
            s += 14
        else:
            s -= 10

    area = effective_area(lst)
    if area is not None:
        ideal_min = profile.get("area_ideal_min_m2", 230)
        ideal_max = profile.get("area_ideal_max_m2", 1200)
        if ideal_min <= area <= ideal_max:
            s += 14
        elif area < ideal_min:
            s += 4          # 180-230: один корт впритык
        elif area <= profile.get("huge_area_m2", 2000):
            s += 2
        else:
            s -= 18         # гигантский объект целиком — не под 1-2 корта
    ideal_max = profile.get("area_ideal_max_m2", 1200)
    if "divisible" in flags and area is not None and area <= ideal_max:
        s += 6
    if "two_courts" in flags:
        s += 6

    if "unheated" in flags:
        s -= 22             # падел = круглогодичный клуб, отопление критично
    elif lst.heated:
        s += 8

    if lst.floor == 1:
        s += 6
    if "upper_floor" in flags:
        s -= 10
    pt = lst.property_type.lower()
    if any(t in pt for t in GOOD_TYPES):
        s += 6
    if any(t in pt for t in BAD_TYPES):
        s -= 12
    a = lst.attrs
    s += 4 * bool(a.get("parking"))
    s += 4 * bool(a.get("separate_entrance"))
    s += 7 * bool(a.get("no_columns"))
    s += 4 * bool(a.get("sport_hint"))
    s += 3 * bool(lst.metro)
    if a.get("columns") and not a.get("no_columns"):
        s -= 5

    s = max(0, min(100, s))
    # ключевые падел-параметры не подтверждены — score не может быть высоким
    if "height_unknown" in flags:
        s = min(s, 65)
    if "unheated" in flags:
        s = min(s, 55)
    if area is not None and area > ideal_max:
        s = min(s, 72)  # минимальный сдаваемый кусок больше, чем нужно 1-2 кортам
    return s
