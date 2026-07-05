"""Геосправочники: ближайшее метро и ближайший конкурент.

Данные лежат в репозитории и правятся руками:
  pi/geo/minsk-metro.yaml   — станции метро (сгенерировано из OSM)
  pi/competitors.md         — падел-клубы (YAML-блок внутри markdown)
"""

import math
import re
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(a)), 2)


@lru_cache(maxsize=1)
def _metro() -> list[tuple[str, float, float]]:
    path = ROOT / "pi" / "geo" / "minsk-metro.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [(name, c[0], c[1]) for name, c in (data.get("stations") or {}).items()]


@lru_cache(maxsize=1)
def _competitors() -> list[dict]:
    path = ROOT / "pi" / "competitors.md"
    if not path.exists():
        return []
    m = re.search(r"```yaml\s*(.*?)```", path.read_text(encoding="utf-8"), re.S)
    if not m:
        return []
    data = yaml.safe_load(m.group(1)) or {}
    return [c for c in (data.get("competitors") or [])
            if c.get("lat") is not None and c.get("lon") is not None]


def nearest_metro(lat, lon) -> dict | None:
    """{'name', 'km'} ближайшей станции метро или None."""
    if lat is None or lon is None or not _metro():
        return None
    name, best = min(((n, _haversine(lat, lon, sl, sn)) for n, sl, sn in _metro()),
                     key=lambda x: x[1])
    return {"name": name, "km": best}


def nearest_competitor(lat, lon) -> dict | None:
    """{'name', 'km'} ближайшего падел-клуба или None."""
    if lat is None or lon is None or not _competitors():
        return None
    c, best = min(((c, _haversine(lat, lon, c["lat"], c["lon"])) for c in _competitors()),
                  key=lambda x: x[1])
    return {"name": c["name"], "km": best}


def yandex_map_url(lat, lon, address: str = "") -> str:
    """Ссылка на Яндекс.Карты: по координатам (формат pt=lon,lat) или адресу."""
    if lat is not None and lon is not None:
        return f"https://yandex.by/maps/?pt={lon},{lat}&z=16&l=map"
    if address:
        from urllib.parse import quote
        return f"https://yandex.by/maps/?text={quote(address + ', Минск')}"
    return ""
