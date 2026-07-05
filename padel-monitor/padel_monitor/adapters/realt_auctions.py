"""realt.by/auctions: госаукционы аренды коммерческой недвижимости.

ВАЖНО про источник (разведка 2026-07-05):
- Каноническая площадка госаукционов — au.nca.by — ГЕО-ЗАБЛОКИРОВАНА (403 не с
  белорусского IP), как megapolis. Её адаптер имеет смысл писать только с BY-IP.
- realt.by/auctions ДОСТИЖИМА, но это на ~95% архив завершённых аукционов
  (2015–2024), лоты — свободный текст «извещений» без структурированных данных.
  Поэтому здесь: берём только АКТИВНЫЕ лоты (не «завершён») по АРЕНДЕ в МИНСКЕ,
  и только для них тянем detail-страницу; площадь/цену извлекаем консервативно.
  Жёсткий падел-фильтр (площадь ≥180, дистанция) отсеет мелочь автоматически.

Источник выключен по умолчанию (тонкий сигнал). Детали — pi/site-specs/auctions.md.
"""

import re

from selectolax.parser import HTMLParser

from ..normalize import Listing, extract_height_m, extract_text_flags
from .base import fetch

LOT_ID_RE = re.compile(r"/auctions/(\d+)-")
AREA_RE = re.compile(r"(\d[\d\s]{0,7}(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м2|м²)", re.I)
PRICE_RE = re.compile(
    r"нач\w+\s+цен\w+[^0-9]{0,40}?(\d[\d\s]{2,12}(?:[.,]\d+)?)", re.I)
DEPOSIT_RE = re.compile(r"задат\w+[^0-9]{0,40}?(\d[\d\s]{2,12}(?:[.,]\d+)?)", re.I)
DATE_RE = re.compile(r"(\d{2}\.\d{2}\.20\d{2})")
LOCATION_RE = re.compile(r"Местонахождение:\s*([^<]{0,120})")


def _num(s: str) -> float | None:
    s = s.replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _max_area(text: str) -> float | None:
    vals = [v for v in (_num(m.group(1)) for m in AREA_RE.finditer(text))
            if v and 30 <= v <= 100000]
    return max(vals) if vals else None


def crawl(cfg: dict, raw_dir: str) -> list[Listing]:
    out = []
    urls = cfg.get("urls") or [
        "https://realt.by/auctions/arenda-commercheskoi-nedvigimosti/"]
    max_lots = cfg.get("max_lots", 10)
    for url in urls:
        html = fetch(url, raw_dir, "realt_auctions_list", cfg.get("delay_s", 3))
        tree = HTMLParser(html)
        picked = 0
        for it in tree.css(".auction-item"):
            if picked >= max_lots:
                break
            a = it.css_first(".title a")
            if not a:
                continue
            href = a.attributes.get("href") or ""
            m = LOT_ID_RE.search(href)
            if not m:
                continue
            card = it.text(separator=" ", strip=True)
            low = card.lower()
            # только активные (не завершён) лоты по аренде в Минске (не области)
            if "завершен" in low or "аренд" not in low:
                continue
            loc = LOCATION_RE.search(it.html or "")
            loc_txt = (loc.group(1) if loc else "")
            if "минск" not in loc_txt.lower() or "област" in loc_txt.lower():
                continue

            picked += 1
            lot_id = m.group(1)
            detail = fetch(href, raw_dir, f"realt_auction_{lot_id}",
                           cfg.get("delay_s", 3))
            dtree = HTMLParser(detail)
            body = (dtree.body.text(separator=" ", strip=True) if dtree.body else "")
            # режем cookie-баннер: берём текст после слова «извещение»/«аукцион»
            idx = body.lower().find("аукцион")
            text = body[idx:idx + 8000] if idx > 0 else body[:8000]

            price = PRICE_RE.search(text)
            deposit = DEPOSIT_RE.search(text)
            future = [d for d in DATE_RE.findall(text) if d >= "01.07.2026"]
            out.append(Listing(
                source="realt-auction",
                source_id=lot_id,
                url=href,
                title=(a.text(strip=True) or "Госаукцион аренды")[:300],
                description=text[:4000],
                price_byn=_num(price.group(1)) if price else None,
                area_m2=_max_area(text),
                address=loc_txt.strip(),
                town="Минск",
                region="Минск",
                property_type="аукцион-аренда",
                ceiling_height_m=extract_height_m(text),
                attrs={**extract_text_flags(text), "auction": True,
                       "platform": "realt.by/auctions",
                       "deposit_byn": _num(deposit.group(1)) if deposit else None,
                       "auction_date": future[0] if future else None},
            ))
    return out
