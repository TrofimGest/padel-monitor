import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class AdapterStop(Exception):
    """Стоп-сигнал: 403/429/капча/пустая выдача — адаптер останавливается."""


def fetch(url: str, raw_dir: str, tag: str, delay_s: float = 3.0) -> str:
    time.sleep(delay_s)
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    if r.status_code in (403, 429):
        raise AdapterStop(f"HTTP {r.status_code} on {url}")
    r.raise_for_status()
    html = r.text
    if re.search(r"captcha|turnstile|cf-challenge", html[:20000], re.I):
        raise AdapterStop(f"captcha marker on {url}")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = Path(raw_dir) / day
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{tag}.html").write_text(html, encoding="utf-8")
    return html


def next_data(html: str, url: str) -> dict:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise AdapterStop(f"__NEXT_DATA__ not found on {url}")
    return json.loads(m.group(1))
