"""padel-map: HTML-карта кандидатов недели (Leaflet + OSM).

Слои: кандидаты (цвет по final_score, иначе pre_score), watchlist,
конкуренты, метро, круги near/ok от центра. Самодостаточный HTML-файл
(Leaflet с CDN, тайлы OSM подгружаются при открытии). Данные берёт из тех же
контрактов, что и отчёт: --candidates (обязателен), --verdicts (опц.).
"""

import argparse
import html
import json

from .config import load_config
from .geo import _competitors, _metro

WATCH_STATUSES = {"watch", "called", "visited", "finalist"}


def _color(final_score, pre_score, status) -> str:
    if status in WATCH_STATUSES:
        return "#8e44ad"          # фиолетовый — на контроле
    s = final_score if final_score is not None else pre_score
    if s is None:
        return "#95a5a6"
    if s >= 75:
        return "#27ae60"          # зелёный
    if s >= 60:
        return "#f39c12"          # жёлтый
    return "#95a5a6"              # серый


def build_html(candidates: list, verdicts: dict, profile: dict) -> str:
    points = []
    for c in candidates:
        if c.get("lat") is None or c.get("lon") is None:
            continue
        v = verdicts.get(str(c["id"])) or verdicts.get(c["id"]) or {}
        fs = v.get("final_score")
        status = v.get("status")
        price = (f"{c['price_byn']:.0f} BYN/мес" if c.get("price_byn")
                 else f"{c['price_usd']:.0f} USD/мес" if c.get("price_usd") else "цена ?")
        area = f"{c['area_m2']:.0f} м²" if c.get("area_m2") else "площадь ?"
        title = html.escape((c.get("title") or "")[:80])
        popup = (f"<b>[{fs if fs is not None else c.get('pre_score','—')}]</b> {area}"
                 f"{', выс. %g м' % c['ceiling_height_m'] if c.get('ceiling_height_m') else ''}"
                 f"<br>{price}<br>{html.escape(c.get('address') or '')}"
                 f"<br><a href='{html.escape(c.get('url') or '')}' target='_blank'>объявление</a>")
        points.append({"lat": c["lat"], "lon": c["lon"],
                       "color": _color(fs, c.get("pre_score"), status),
                       "label": title, "popup": popup})

    data = {
        "center": [profile["center_lat"], profile["center_lon"]],
        "near_km": profile["near_distance_km"], "ok_km": profile["ok_distance_km"],
        "points": points,
        "competitors": [{"lat": c["lat"], "lon": c["lon"],
                         "name": html.escape(c.get("name", ""))} for c in _competitors()],
        "metro": [{"lat": la, "lon": lo, "name": html.escape(n)}
                  for n, la, lo in _metro()],
    }
    blob = json.dumps(data, ensure_ascii=False)

    return """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Падел-монитор: карта кандидатов</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}.legend{background:#fff;padding:8px 10px;
font:13px sans-serif;line-height:1.5;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3)}
.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;
vertical-align:middle}</style></head><body><div id="map"></div>
<script>
const D = __DATA__;
const map = L.map('map').setView(D.center, 11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'© OpenStreetMap'}).addTo(map);
L.circle(D.center, {radius:D.near_km*1000, color:'#27ae60', fill:false, dashArray:'4'}).addTo(map);
L.circle(D.center, {radius:D.ok_km*1000, color:'#f39c12', fill:false, dashArray:'4'}).addTo(map);
D.metro.forEach(m => L.circleMarker([m.lat,m.lon],
  {radius:3, color:'#2980b9', fillOpacity:.8}).bindTooltip('Ⓜ '+m.name).addTo(map));
D.competitors.forEach(c => L.marker([c.lat,c.lon],
  {icon:L.divIcon({className:'',html:'<div style="font-size:20px">🎾</div>'})})
  .bindPopup('<b>Конкурент:</b> '+c.name).addTo(map));
D.points.forEach(p => L.circleMarker([p.lat,p.lon],
  {radius:9, color:'#333', weight:1, fillColor:p.color, fillOpacity:.9})
  .bindPopup(p.popup).bindTooltip(p.label).addTo(map));
const lg = L.control({position:'bottomright'});
lg.onAdd = () => { const d = L.DomUtil.create('div','legend');
  d.innerHTML = '<b>Кандидаты</b><br>'+
  '<span class="dot" style="background:#27ae60"></span>сильный (75+)<br>'+
  '<span class="dot" style="background:#f39c12"></span>средний (60-74)<br>'+
  '<span class="dot" style="background:#95a5a6"></span>слабый<br>'+
  '<span class="dot" style="background:#8e44ad"></span>на контроле<br>'+
  '🎾 конкурент · Ⓜ метро'; return d; };
lg.addTo(map);
</script></body></html>""".replace("__DATA__", blob)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", required=True, help="JSON от padel-candidates")
    ap.add_argument("--verdicts", help="JSON вердиктов (для цвета/статуса)")
    ap.add_argument("--out", required=True, help="куда сохранить HTML")
    args = ap.parse_args()

    cfg = load_config()
    with open(args.candidates, encoding="utf-8") as f:
        cand_data = json.load(f)
    candidates = cand_data.get("candidates", [])
    # добавим watchlist-точки (у них статус) поверх кандидатов недели
    candidates += cand_data.get("watchlist", [])

    verdicts: dict = {}
    if args.verdicts:
        with open(args.verdicts, encoding="utf-8") as f:
            for v in json.load(f).get("verdicts", []):
                verdicts[str(v["id"])] = v

    html_out = build_html(candidates, verdicts, cfg["profile"])
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(json.dumps({"map": args.out, "points": html_out.count("circleMarker") and
                      len([c for c in candidates if c.get("lat")])}, ensure_ascii=False))
    return 0
