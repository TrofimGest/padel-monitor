"""au.nca.by — госаукционы аренды (Единый реестр имущества, Нацкадастр).

Каноническая площадка госаукционов аренды/продажи госимущества. Сдаётся часто
СИЛЬНО дешевле рынка — для падел-клуба это шанс на большой зал за полцены
(в выдаче попадаются «Универсальный спортивный зал», «зрительный зал» и т.п.).

СЕТЬ: сайт отдаёт данные ТОЛЬКО на белорусский IP (иначе 403). На машине за
VPN нужен split-tunnel — host-маршрут к IP au.nca.by мимо туннеля, через
физический BY-шлюз. Разведка и настройка — pi/site-specs/auctions.md.

Устройство (разведка 2026-07-05): jQuery/Spring, POST-форма `/mainSearch`
(→ redirect `/search`). Фильтры: howToUseAction=1 «Сдача в аренду»,
type=5 «Помещение», squareMin (работает серверно!), pageSize (до 500 —
все лоты одним запросом). Регион серверно НЕ фильтруется → Минск отбираем по
адресу. Карточка выдачи несёт тип, площадь, адрес, а у лотов с назначенным
аукционом — дату и «Цена лота: N BYN». Высота потолков в выдаче почти не
встречается → height_unknown, уточняется по фото на detail через padel-enrich.
"""

import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

from ..normalize import Listing, extract_height_m, extract_text_flags
from .base import UA, AdapterStop

BASE = "https://au.nca.by"
TOKEN_RE = {"sfid": re.compile(r'name="as_sfid" value="([^"]*)"'),
            "fid": re.compile(r'name="as_fid" value="([^"]*)"')}
ITEM_RE = re.compile(r"/item/(\d+)")
AREA_RE = re.compile(r"Площадь:\s*([\d.]+)")
ADDR_RE = re.compile(r"Адрес:\s*(.+?)(?:\s*(?:ПРЕДЛАГ|Цена лота|$))")
PRICE_RE = re.compile(r"Цена лота:\s*([\d\s.]+?)\s*BYN")
DATE_RE = re.compile(r"(\d{2}\.\d{2}\.20\d{2})")


def _num(s: str) -> float | None:
    try:
        return float(s.replace(" ", "").replace("\xa0", ""))
    except (ValueError, AttributeError):
        return None


def _is_minsk(addr: str) -> bool:
    low = addr.lower()
    return bool(re.search(r"г\.?\s*минск", low)) and "обл" not in low and " р-н" not in low


def _parse_card(card) -> dict | None:
    a = card.css_first('a[href^="/item/"]')
    if not a:
        return None
    m = ITEM_RE.search(a.attributes.get("href", ""))
    if not m:
        return None
    txt = re.sub(r"\s+", " ", card.text(separator=" ", strip=True))
    addr = ADDR_RE.search(txt)
    area = AREA_RE.search(txt)
    price = PRICE_RE.search(txt)
    date = DATE_RE.search(txt)
    # тип объекта — текст до «Площадь:», без ведущих дат-бейджей
    typ = re.split(r"Площадь:|Адрес:", txt)[0]
    typ = re.sub(r"\d{2}\.\d{2}\.20\d{2}", "", typ).strip()[:120]
    return {
        "id": m.group(1),
        "area": _num(area.group(1)) if area else None,
        "addr": addr.group(1).strip() if addr else "",
        "price": _num(price.group(1)) if price else None,
        "date": date.group(1) if date else None,
        "type": typ,
        "text": txt,
    }


def _save_raw(html: str, raw_dir: str, tag: str):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = Path(raw_dir) / day
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{tag}.html").write_text(html, encoding="utf-8")


def crawl(cfg: dict, raw_dir: str) -> list[Listing]:
    square_min = cfg.get("square_min", 180)
    page_size = cfg.get("page_size", 500)
    delay = cfg.get("delay_s", 4)
    headers = {"User-Agent": UA}

    with httpx.Client(headers=headers, timeout=60, follow_redirects=True) as client:
        try:
            home = client.get(BASE + "/")
        except httpx.HTTPError as e:
            raise AdapterStop(f"нет доступа к au.nca.by (нужен BY-IP/split-tunnel): {e}")
        if home.status_code == 403:
            raise AdapterStop("403 au.nca.by — трафик идёт не с BY-IP (проверь split-tunnel)")
        home.raise_for_status()
        sfid = TOKEN_RE["sfid"].search(home.text)
        fid = TOKEN_RE["fid"].search(home.text)
        if not sfid or not fid:
            raise AdapterStop("не найдены токены as_sfid/as_fid на главной")

        time.sleep(delay)
        data = {
            "pageNum": "0", "pageSize": str(page_size), "sortBy": "NONE",
            "forSale": "false", "basePriceLot": "false", "toggle": "false",
            "searchItem.howToUseAction": "1",   # Сдача в аренду
            "searchItem.type": "5",             # Помещение, машино-место
            "searchItem.name": "",
            "squareMin": str(square_min),
            "as_sfid": sfid.group(1), "as_fid": fid.group(1),
        }
        r = client.post(BASE + "/mainSearch", data=data)
        if r.status_code in (403, 429):
            raise AdapterStop(f"HTTP {r.status_code} на /mainSearch")
        r.raise_for_status()

    html = r.text
    _save_raw(html, raw_dir, "nca_auctions")
    tree = HTMLParser(html)
    cards = [c for c in tree.css(".card") if c.css_first('a[href^="/item/"]')]
    if not cards:
        raise AdapterStop("нет карточек в выдаче au.nca.by (сменилась вёрстка?)")

    # разобрать минские карточки
    parsed = []
    seen = set()
    for card in cards:
        d = _parse_card(card)
        if not d or d["id"] in seen or not _is_minsk(d["addr"]):
            continue
        seen.add(d["id"])
        parsed.append(d)

    # intra-building дедуп: у мультиюнитовых зданий карточка показывает площадь
    # ВСЕГО здания (Минск-Арена, Дворец Республики -> десятки под-лотов с одной
    # площадью). Схлопываем группы (площадь + улица) в один представитель,
    # предпочитая спорт/зал-назначение — именно оно интересно под падел.
    SPORT_RE = re.compile(r"спорт|зал|физкульт|арен|манеж|игров", re.I)

    def _street(addr: str) -> str:
        m = re.search(r"г\.?\s*Минск,\s*([^,]+?)[,\d]", addr)
        return (m.group(1) if m else addr).strip().lower()

    groups: dict[tuple, list] = {}
    for d in parsed:
        groups.setdefault((round(d["area"] or 0, 1), _street(d["addr"])), []).append(d)
    kept = []
    for g in groups.values():
        if len(g) == 1:
            kept.append(g[0])
        else:  # представитель: сперва спорт/зал, потом с назначенной датой
            g.sort(key=lambda d: (bool(SPORT_RE.search(d["type"])), bool(d["date"])),
                   reverse=True)
            kept.append(g[0])

    out = []
    for d in kept:
        out.append(Listing(
            source="nca-auction",
            source_id=d["id"],
            url=f"{BASE}/item/{d['id']}",
            title=d["type"] or "Госаукцион аренды",
            description=d["text"][:4000],
            price_byn=d["price"],          # стартовая цена аукциона, не готовая аренда
            area_m2=d["area"],
            address=d["addr"],
            town="Минск", region="Минск",
            property_type=d["type"][:60] or "госаукцион-аренда",
            ceiling_height_m=extract_height_m(d["text"]),
            attrs={**extract_text_flags(d["text"]), "auction": True,
                   "platform": "au.nca.by", "howtouse": "аренда",
                   "auction_date": d["date"],
                   "status": "торги назначены" if d["date"] else "предлагается"},
        ))
    return out


def parse_detail(html: str, url: str) -> dict:
    """Detail /item/{id}: фото, полное назначение/описание, иногда высота."""
    out: dict = {}
    imgs = re.findall(r'["\'](/img/(?:ergi|au)/[^"\']+?\.(?:jpg|jpeg|png))["\']',
                      html, re.I)
    if imgs:
        out["images"] = [BASE + u for u in dict.fromkeys(imgs)][:12]
    tree = HTMLParser(html)
    body = tree.body.text(separator=" ", strip=True) if tree.body else ""
    if body:
        out["description"] = re.sub(r"\s+", " ", body)[:6000]
        h = extract_height_m(body)
        if h:
            out["ceiling_height_m"] = h
    return out
