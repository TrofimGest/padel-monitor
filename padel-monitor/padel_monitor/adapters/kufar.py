"""re.kufar.by: осторожный SSR — только первая страница категорийных URL
без query-параметров (robots запрещает многие query/cursor паттерны).
Дефолтная выдача отсортирована по list_time — новое видно на первой странице.
Телефоны не собираем, deep pagination не делаем.
"""

from ..normalize import (Listing, extract_area_min, extract_heated,
                         extract_height_m, extract_text_flags)
from .base import fetch, next_data

IMG_BASE = "https://rms.kufar.by/v1/gallery/"


def _params(ad: dict) -> dict:
    return {p.get("p"): p for p in ad.get("ad_parameters", [])}


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_detail(html: str, url: str) -> dict:
    """Detail-страница kufar: полный body, все фото, высота/отопление из текста.
    Возвращает поля для обновления listing (только непустые)."""
    from .base import next_data
    init = ((next_data(html, url)["props"]["initialState"].get("adView") or {})
            .get("data") or {}).get("initial") or {}
    out: dict = {}
    body = init.get("body")
    if body:
        out["description"] = body[:6000]
    imgs = [IMG_BASE + i["path"] for i in (init.get("images") or [])[:12]
            if i.get("path")]
    if imgs:
        out["images"] = imgs
    p = _params(init)
    improvements = p.get("commercial_improvements", {}).get("vl") or []
    if body:
        h = extract_height_m(body)
        if h:
            out["ceiling_height_m"] = h
    if "Отопление" in improvements:
        out["heated"] = True
    elif body:
        hd = extract_heated(body)
        if hd is not None:
            out["heated"] = hd
    return out


def crawl(cfg: dict, raw_dir: str) -> list[Listing]:
    out, seen = [], set()
    for url in cfg["urls"]:
        tag = "kufar_" + url.rstrip("/").split("/")[-1]
        html = fetch(url, raw_dir, tag, cfg.get("delay_s", 3))
        state = next_data(html, url)["props"]["initialState"]["listing"]
        for ad in (state.get("ads") or []):
            ad_id = str(ad.get("ad_id"))
            if not ad_id or ad_id in seen:
                continue
            seen.add(ad_id)
            p = _params(ad)
            text = f"{ad.get('subject') or ''}\n{ad.get('body_short') or ''}"
            floors = p.get("re_number_floors", {}).get("v")
            price_byn = _num(ad.get("price_byn"))
            price_usd = _num(ad.get("price_usd"))
            area = _num(p.get("size", {}).get("v"))
            ppm2 = _num(p.get("square_meter", {}).get("v"))
            improvements = p.get("commercial_improvements", {}).get("vl") or []
            lst = Listing(
                source="kufar",
                source_id=ad_id,
                url=ad.get("ad_link") or f"https://re.kufar.by/vi/{ad_id}",
                title=(ad.get("subject") or "")[:300],
                description=(ad.get("body_short") or "")[:4000],
                price_byn=price_byn / 100 if price_byn else None,   # цены в копейках
                price_usd=price_usd / 100 if price_usd else None,
                price_per_m2=ppm2,
                area_m2=area,
                address=str(p.get("address", {}).get("v") or ""),
                town=str(p.get("region", {}).get("vl") or ""),
                district=str(p.get("area", {}).get("vl") or ""),
                region="Минск",
                property_type=str(p.get("property_type", {}).get("vl") or ""),
                floor=None,
                floors=int(floors[0]) if isinstance(floors, list) and floors else None,
                ceiling_height_m=extract_height_m(text),
                area_min_m2=extract_area_min(text),
                heated=(True if "Отопление" in improvements
                        else extract_heated(text)),
                lat=(p.get("coordinates", {}).get("v") or [None, None])[1],
                lon=(p.get("coordinates", {}).get("v") or [None, None])[0],
                metro=", ".join(p.get("metro", {}).get("vl") or []),
                published_at=(ad.get("list_time") or "")[:19],
                images=[IMG_BASE + i["path"] for i in (ad.get("images") or [])[:8]
                        if i.get("path")],
                attrs={**extract_text_flags(text),
                       "improvements": improvements,
                       "parking": "Парковка" in improvements
                                  or extract_text_flags(text)["parking"]},
            )
            out.append(lst)
    return out
