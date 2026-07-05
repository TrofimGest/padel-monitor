"""realt.by: HTTP + __NEXT_DATA__ (pageProps.objects).

Сортировка по новизне: ?sortType=createdAt (проверено 2026-07-04).
robots.txt формально не приветствует произвольные query — держим нагрузку
минимальной: 1-2 страницы на категорию, 1 раз в день.
"""

import re

from ..normalize import (Listing, extract_area_min, extract_heated,
                         extract_height_m, extract_text_flags)
from .base import fetch, next_data

CURRENCIES = {933: "BYN", 840: "USD", 978: "EUR"}

DETAIL_HREF_RE = re.compile(r'href="/(rent-[a-z-]+)/object/(\d+)/')
# слаг detail-страницы != слагу каталога (production -> rent-proizvodstvo и т.п.)
DETAIL_SLUGS = {"warehouses": "rent-warehouses", "storages": "rent-pomeschenie",
                "production": "rent-proizvodstvo", "services": "rent-services",
                "shops": "rent-shops"}

# objectType/category → человекочитаемый тип (наблюдаемые значения дополнять)
CATEGORY_SLUGS = {
    "warehouses": "склад", "storages": "склад-хранение", "production": "производство",
    "services": "услуги", "shops": "торговое", "offices": "офис", "business": "бизнес",
}


def _price_fields(o: dict) -> tuple[float | None, float | None, float | None]:
    cur = CURRENCIES.get(o.get("priceCurrency"), "BYN")
    price = o.get("price") or o.get("priceMax") or o.get("priceMin") or None
    ppm2 = o.get("pricePerM2") or o.get("pricePerM2Max") or None
    area = o.get("areaMax") or o.get("areaMin")
    if price is None and ppm2 and area:
        price = round(ppm2 * area, 2)
    byn = usd = None
    if cur == "BYN":
        byn = price
    elif cur == "USD":
        usd = price
    return byn, usd, ppm2


def crawl(cfg: dict, raw_dir: str) -> list[Listing]:
    out = []
    for cat in cfg["categories"]:
        for page in range(1, cfg.get("pages", 2) + 1):
            url = f"https://realt.by/rent/{cat}/?sortType=createdAt"
            if page > 1:
                url += f"&page={page}"
            html = fetch(url, raw_dir, f"realt_{cat}_p{page}", cfg.get("delay_s", 3))
            objs = next_data(html, url)["props"]["pageProps"].get("objects") or []
            # фактические ссылки карточек из HTML: code -> slug
            hrefs = {code: slug for slug, code in DETAIL_HREF_RE.findall(html)}
            for o in objs:
                text = f"{o.get('title') or ''}\n{o.get('headline') or ''}\n{o.get('description') or ''}"
                byn, usd, ppm2 = _price_fields(o)
                lst = Listing(
                    source="realt",
                    source_id=str(o["code"]),
                    url="https://realt.by/{}/object/{}/".format(
                        hrefs.get(str(o["code"]),
                                  DETAIL_SLUGS.get(cat, f"rent-{cat}")),
                        o["code"]),
                    title=(o.get("headline") or o.get("title") or "")[:300],
                    description=(o.get("description") or "")[:4000],
                    price_byn=byn, price_usd=usd, price_per_m2=ppm2,
                    area_m2=o.get("areaMax") or o.get("areaMin"),
                    address=o.get("address") or "",
                    town=o.get("townName") or "",
                    district=o.get("stateDistrictName") or "",
                    region=o.get("stateRegionName") or "",
                    property_type=CATEGORY_SLUGS.get(cat, cat),
                    floor=o.get("storey"), floors=o.get("storeys"),
                    ceiling_height_m=extract_height_m(text),
                    area_min_m2=(o.get("areaMin")
                                 if o.get("areaMin") and o.get("areaMax")
                                 and o["areaMin"] < o["areaMax"]
                                 else extract_area_min(text)),
                    heated=(True if o.get("heating") else extract_heated(text)),
                    metro=o.get("metroStationName") or "",
                    published_at=(o.get("createdAt") or "")[:19],
                    updated_at=(o.get("updatedAt") or "")[:19],
                    images=(o.get("images") or [])[:8],
                    attrs=extract_text_flags(text),
                )
                out.append(lst)
    return out
