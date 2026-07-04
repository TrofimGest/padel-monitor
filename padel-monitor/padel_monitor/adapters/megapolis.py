"""megapolis-real.by: HTTP + DOM parser.

ВНИМАНИЕ: адаптер написан по данным разведки 2026-07-03 (карточки с data-go-url,
~30 на страницу, сортировка sortBy=createdon&sortDir=DESC) и НЕ проверен вживую:
сайт не отвечает не с белорусского IP. Перед включением (enabled: true в config)
запустить с VPS/BY-IP и сверить селекторы по data/raw/*/megapolis_*.html.
"""

import re

from selectolax.parser import HTMLParser

from ..normalize import Listing, extract_height_m, extract_text_flags
from .base import fetch

AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:м2|м²|кв\.?\s*м)", re.I)
PRICE_RE = re.compile(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(BYN|руб|USD|\$|€)", re.I)


def crawl(cfg: dict, raw_dir: str) -> list[Listing]:
    out, seen = [], set()
    for base_url in cfg["urls"]:
        url = base_url.rstrip("/") + "/?sortBy=createdon&sortDir=DESC"
        tag = "megapolis_" + base_url.rstrip("/").split("/")[-2]
        html = fetch(url, raw_dir, tag, cfg.get("delay_s", 3))
        tree = HTMLParser(html)
        for card in tree.css("[data-go-url]"):
            href = card.attributes.get("data-go-url") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            full_url = href if href.startswith("http") else "https://megapolis-real.by" + href
            text = card.text(separator=" ", strip=True)
            m_area = AREA_RE.search(text)
            m_price = PRICE_RE.search(text)
            price = None
            if m_price:
                price = float(m_price.group(1).replace(" ", "").replace(",", "."))
            lst = Listing(
                source="megapolis",
                source_id=href.rstrip("/").split("/")[-1],
                url=full_url,
                title=text[:200],
                description=text[:2000],
                price_byn=price if m_price and m_price.group(2).lower() in ("byn", "руб") else None,
                price_usd=price if m_price and m_price.group(2) in ("USD", "$") else None,
                area_m2=float(m_area.group(1).replace(",", ".")) if m_area else None,
                town="Минск" if "минск" in text.lower() else "",
                property_type="megapolis",
                ceiling_height_m=extract_height_m(text),
                attrs=extract_text_flags(text),
            )
            out.append(lst)
    return out
