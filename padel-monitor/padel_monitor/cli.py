"""CLI-контракты проекта: детерминированные команды с bounded JSON вводом/выводом.

LLM-скоринг, vision и судья здесь НЕ живут — это работа Pi-агента
(.pi/skills/padel-weekly-report). Python отвечает за сбор, нормализацию,
жёсткие правила, хранение и доставку в Telegram.

Команды (запускать через uv run):
  padel-collect        сбор -> SQLite -> дедуп -> алерты; JSON-сводка в stdout
  padel-enrich         detail-обогащение топ-кандидатов (полное описание/фото/высота)
  padel-candidates     кандидаты недели + контекст для судьи (JSON в stdout)
  padel-save-verdicts  сохранить вердикты судьи (--file verdicts.json)
  padel-telegram       отправить в Telegram (--file .html | --text ... | --document путь)
  padel-map            HTML-карта кандидатов (--candidates ... --out ...)
  padel-rescore        пересчёт правил/эвристики по всей базе
"""

import argparse
import json
import sys
import traceback

import httpx

from . import db, dedup
from .adapters import kufar, megapolis, realt
from .adapters.base import AdapterStop
from .config import load_config
from .geo import nearest_competitor, nearest_metro, yandex_map_url
from .normalize import Listing
from .rules import apply_rules, distance_km, heuristic_score

ADAPTERS = {"realt": realt, "kufar": kufar, "megapolis": megapolis}


def _score_listing(con, cfg: dict, lid: int, lst: Listing):
    ok, reason, flags = apply_rules(lst, cfg["profile"])
    score = heuristic_score(lst, flags, cfg["profile"]) if ok else None
    con.execute(
        "INSERT INTO scores (listing_id, rule_pass, rule_reject_reason, rule_flags, "
        "score, scored_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(listing_id) DO UPDATE SET rule_pass=excluded.rule_pass, "
        "rule_reject_reason=excluded.rule_reject_reason, rule_flags=excluded.rule_flags, "
        "score=excluded.score, scored_at=excluded.scored_at",
        (lid, int(ok), reason, json.dumps(flags, ensure_ascii=False),
         score, db.now_iso()))


def _alert_card(r) -> str:
    from .telegram import esc
    price = (f"{r['price_byn']:.0f} BYN/мес" if r["price_byn"]
             else f"{r['price_usd']:.0f} USD/мес" if r["price_usd"] else "цена ?")
    h = f"выс. {r['ceiling_height_m']:g} м" if r["ceiling_height_m"] else "высота ?"
    area = f"{r['area_m2']:.0f} м²" if r["area_m2"] else "площадь ?"
    d = distance_km(r["lat"], r["lon"], {"center_lat": 53.9023, "center_lon": 27.5619})
    dist = f"{d:g} км от центра" if d is not None else ""
    mp = yandex_map_url(r["lat"], r["lon"], r["address"] or "")
    lines = [f"<b>🔥 Новый кандидат-эталон [{r['score']}/100]</b>",
             f"{esc(r['property_type'])}, {area}, {h}, "
             f"{'отапл.' if r['heated'] else 'отопление ?'}",
             f"📍 {esc(r['address'] or r['town'])} · {dist}",
             f"💰 {price}", esc(r["url"])]
    if mp:
        lines.append(f"🗺 {mp}")
    return "\n".join(lines)


def _run_alerts(con, cfg: dict):
    """Мгновенные алерты без LLM: новые эталоны (1.1) и снижение цены (1.2)."""
    token = cfg["telegram"]["token"]
    if not token:
        return {"skipped": "no telegram token"}
    from .telegram import esc, send
    chat = cfg["telegram"]["chat_id"]
    prof, rep = cfg["profile"], cfg["report"]
    sent = {"padel": 0, "price_drop": 0}

    # 1.1 новые кандидаты-эталоны
    budget = rep.get("alert_max_per_day", 3) - db.alerts_today(con, "padel")
    if budget > 0:
        rows = con.execute("""
            SELECT l.*, s.score, s.rule_flags FROM listings l
            JOIN scores s ON s.listing_id = l.id
            WHERE s.rule_pass = 1 AND l.status='active'
              AND s.score >= ?
              AND l.first_seen_at >= datetime('now', '-1 day')
            ORDER BY s.score DESC""", (prof.get("alert_min_score", 80),)).fetchall()
        for r in rows:
            if budget <= 0:
                break
            flags = json.loads(r["rule_flags"] or "[]")
            if "unheated" in flags or "far" in flags:
                continue
            if db.already_alerted(con, r["id"], "padel"):
                continue
            send(token, chat, _alert_card(r))
            db.record_alert(con, r["id"], "padel")
            sent["padel"] += 1
            budget -= 1

    # 1.2 снижение цены по вариантам из топа/наблюдения
    pct = rep.get("alert_price_drop_pct", 7) / 100
    events = con.execute("""
        SELECT e.id, e.listing_id, e.old_value, e.new_value, l.title, l.url,
               l.price_byn
        FROM events e JOIN listings l ON l.id = e.listing_id
        WHERE e.kind='price_change' AND e.ts >= datetime('now', '-1 day')
          AND (e.listing_id IN (SELECT listing_id FROM reported)
               OR e.listing_id IN (SELECT listing_id FROM alerts))""").fetchall()
    for e in events:
        try:
            old, new = float(e["old_value"]), float(e["new_value"])
        except (TypeError, ValueError):
            continue
        if not old or new >= old or (old - new) / old < pct:
            continue
        if db.already_alerted(con, e["listing_id"], "price_drop", ref=str(e["id"])):
            continue
        drop = round((old - new) / old * 100)
        send(token, chat,
             f"<b>📉 Подешевел вариант из наблюдения (−{drop}%)</b>\n"
             f"{esc(e['title'][:80])}\n{old:.0f} → {new:.0f} BYN/мес\n{esc(e['url'])}")
        db.record_alert(con, e["listing_id"], "price_drop", ref=str(e["id"]))
        sent["price_drop"] += 1
    con.commit()
    return sent


def collect_main() -> int:
    cfg = load_config()
    con = db.connect(cfg["db_path"])
    summary, any_ok = {}, False
    for name, mod in ADAPTERS.items():
        src_cfg = cfg["sources"].get(name) or {}
        if not src_cfg.get("enabled"):
            summary[name] = {"ok": None, "skipped": True}
            continue
        started = db.now_iso()
        found = new = changed = 0
        try:
            listings = mod.crawl(src_cfg, cfg["raw_dir"])
            found = len(listings)
            for lst in listings:
                lid, state = db.upsert_listing(con, lst.to_row())
                if state == "new":
                    new += 1
                if state in ("new", "changed"):
                    changed += state == "changed"
                    _score_listing(con, cfg, lid, lst)
            db.mark_gone(con, name)
            db.log_run(con, name, started, True, found, new, changed)
            summary[name] = {"ok": True, "found": found, "new": new, "changed": changed}
            any_ok = True
        except AdapterStop as e:
            db.log_run(con, name, started, False, found, new, changed, f"STOP: {e}")
            summary[name] = {"ok": False, "error": f"STOP: {e}"}
        except Exception as e:
            db.log_run(con, name, started, False, found, new, changed,
                       f"{type(e).__name__}: {e}")
            summary[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            print(traceback.format_exc(), file=sys.stderr)
        con.commit()
    dup_groups = dedup.rebuild(con)
    con.commit()
    alerts = _run_alerts(con, cfg)
    if any_ok and cfg["healthchecks_url"]:
        try:
            httpx.get(cfg["healthchecks_url"], timeout=15)
        except httpx.HTTPError:
            pass
    print(json.dumps({"ok": any_ok, "sources": summary,
                      "dup_groups": dup_groups, "alerts": alerts},
                     ensure_ascii=False, indent=1))
    return 0 if any_ok else 1


def _row_brief(r, cfg=None, max_desc: int = 1500, max_images: int = 4) -> dict:
    d = {
        "id": r["id"], "source": r["source"], "url": r["url"],
        "title": r["title"], "description": (r["description"] or "")[:max_desc],
        "area_m2": r["area_m2"], "area_min_m2": r["area_min_m2"],
        "ceiling_height_m": r["ceiling_height_m"],
        "heated": None if r["heated"] is None else bool(r["heated"]),
        "price_byn": r["price_byn"], "price_usd": r["price_usd"],
        "price_per_m2": r["price_per_m2"],
        "address": r["address"], "town": r["town"], "district": r["district"],
        "metro": r["metro"], "lat": r["lat"], "lon": r["lon"],
        "property_type": r["property_type"], "floor": r["floor"],
        "enriched": bool(r["enriched_at"]),
        "images": json.loads(r["images"] or "[]")[:max_images],
        "attrs": json.loads(r["attrs"] or "{}"),
    }
    if cfg:
        d["distance_km"] = distance_km(r["lat"], r["lon"], cfg["profile"])
    d["nearest_metro"] = nearest_metro(r["lat"], r["lon"])
    d["nearest_competitor"] = nearest_competitor(r["lat"], r["lon"])
    d["map_url"] = yandex_map_url(r["lat"], r["lon"], r["address"] or "")
    return d


def candidates_main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20,
                    help="максимум кандидатов (bounded contract)")
    args = ap.parse_args()

    cfg = load_config()
    con = db.connect(cfg["db_path"])
    max_img = cfg["report"].get("vision_max_images_enriched", 8)

    # карта дублей: listing_id -> group_id (для склейки realt+kufar)
    dup = {r["listing_id"]: r["group_id"]
           for r in con.execute("SELECT listing_id, group_id FROM dup_groups")}

    rows = con.execute("""
        SELECT l.*, s.score, s.rule_flags FROM listings l
        JOIN scores s ON s.listing_id = l.id
        WHERE s.rule_pass = 1 AND l.status = 'active'
          AND l.first_seen_at >= datetime('now', '-7 days')
          AND l.id NOT IN (SELECT listing_id FROM reported WHERE kind='new')
        ORDER BY s.score DESC, l.first_seen_at DESC""").fetchall()

    candidates, shown_groups = [], {}
    for r in rows:
        gid = dup.get(r["id"])
        if gid is not None and gid in shown_groups:
            shown_groups[gid]["also_on"].append(r["url"])   # дубль -> к представителю
            continue
        imgs = max_img if r["enriched_at"] else 4
        c = dict(_row_brief(r, cfg=cfg, max_images=imgs), pre_score=r["score"],
                 flags=json.loads(r["rule_flags"] or "[]"), also_on=[])
        if gid is not None:
            shown_groups[gid] = c
        candidates.append(c)
        if len(candidates) >= args.limit:
            break

    # рыночный контекст для оценки цены: BYN/м² по активным прошедшим фильтр
    ppm2 = sorted(v[0] for v in con.execute("""
        SELECT l.price_per_m2 FROM listings l JOIN scores s ON s.listing_id = l.id
        WHERE s.rule_pass = 1 AND l.status = 'active'
          AND l.price_per_m2 BETWEEN 2 AND 200"""))
    market = {"note": "BYN за м² в месяц, по активным объявлениям, прошедшим фильтр"}
    if ppm2:
        market.update(
            count=len(ppm2),
            median_price_per_m2_byn=ppm2[len(ppm2) // 2],
            p25=ppm2[len(ppm2) // 4], p75=ppm2[3 * len(ppm2) // 4])

    prev = con.execute("""
        SELECT l.*, s.final_score, s.judge_notes FROM listings l
        JOIN scores s ON s.listing_id = l.id
        JOIN reported rep ON rep.listing_id = l.id
        WHERE l.status='active' AND s.final_score IS NOT NULL
        GROUP BY l.id ORDER BY s.final_score DESC LIMIT ?""",
        (cfg["report"]["prev_leaders"],)).fetchall()
    previous = [dict(_row_brief(p, cfg=cfg, max_desc=400, max_images=0),
                     final_score=p["final_score"],
                     judge_why=(json.loads(p["judge_notes"]) or {}).get("why", "")
                     if p["judge_notes"] else "") for p in prev]

    # watchlist: варианты со статусом наблюдения из последних вердиктов судьи
    WATCH = {"watch", "called", "visited", "finalist"}
    watchlist = []
    for r in con.execute("""
        SELECT l.*, s.final_score, s.judge_notes FROM listings l
        JOIN scores s ON s.listing_id = l.id
        WHERE l.status='active' AND s.judge_notes IS NOT NULL""").fetchall():
        try:
            note = json.loads(r["judge_notes"])
        except (json.JSONDecodeError, TypeError):
            continue
        if note.get("status") in WATCH:
            recent = [dict(e) for e in con.execute("""
                SELECT kind, ts, old_value, new_value FROM events
                WHERE listing_id=? AND ts >= datetime('now','-7 days')""", (r["id"],))]
            watchlist.append(dict(_row_brief(r, cfg=cfg, max_desc=200, max_images=0),
                                  final_score=r["final_score"],
                                  status=note.get("status"), note=note.get("why", ""),
                                  recent_events=recent))

    price_changes = [dict(r) for r in con.execute("""
        SELECT l.title, l.url, e.old_value, e.new_value
        FROM events e JOIN listings l ON l.id = e.listing_id
        JOIN scores s ON s.listing_id = l.id AND s.rule_pass = 1
        WHERE e.kind = 'price_change' AND e.ts >= datetime('now', '-7 days')
        LIMIT 10""")]
    gone = [dict(r) for r in con.execute("""
        SELECT l.title, l.url FROM events e JOIN listings l ON l.id = e.listing_id
        WHERE e.kind = 'gone' AND e.ts >= datetime('now', '-7 days')
          AND e.listing_id IN (SELECT listing_id FROM reported) LIMIT 10""")]
    runs = [dict(r) for r in con.execute("""
        SELECT source, COUNT(*) n, SUM(ok) ok_n, MAX(finished_at) last
        FROM runs WHERE started_at >= datetime('now', '-7 days') GROUP BY source""")]

    print(json.dumps({
        "profile": cfg["profile"],
        "economics": cfg.get("economics", {}),
        "market": market,
        "candidates": candidates,
        "watchlist": watchlist,
        "previous_leaders": previous,
        "price_changes": price_changes,
        "gone": gone,
        "runs": runs,
    }, ensure_ascii=False, indent=1))
    return 0


def save_verdicts_main() -> int:
    """Вход (bounded): {"verdicts":[{"id",final_score,verdict,why,risks,
    vs_previous,photo_note?}], "week_summary": str, "mark_reported": bool}"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    args = ap.parse_args()
    with open(args.file, encoding="utf-8") as f:
        data = json.load(f)

    cfg = load_config()
    con = db.connect(cfg["db_path"])
    ts = db.now_iso()
    saved = 0
    for v in data.get("verdicts", []):
        if not isinstance(v.get("id"), int) or not isinstance(v.get("final_score"), int):
            print(f"skip invalid verdict: {v}", file=sys.stderr)
            continue
        con.execute("UPDATE scores SET final_score=?, judge_notes=? WHERE listing_id=?",
                    (max(0, min(100, v["final_score"])),
                     json.dumps(v, ensure_ascii=False), v["id"]))
        if data.get("mark_reported", True):
            con.execute("INSERT INTO reported (listing_id, report_ts, kind) "
                        "VALUES (?,?,'new')", (v["id"], ts))
        saved += 1
    con.commit()
    print(json.dumps({"saved": saved}))
    return 0


def telegram_main() -> int:
    from .telegram import send, send_document
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", help="файл с HTML-текстом отчёта")
    g.add_argument("--text", help="текст сообщения")
    g.add_argument("--document", help="отправить файл (карта/отчёт) как документ")
    ap.add_argument("--caption", default="", help="подпись к документу")
    args = ap.parse_args()
    cfg = load_config()
    if not cfg["telegram"]["token"]:
        print("TELEGRAM_BOT_TOKEN не задан (.env)", file=sys.stderr)
        return 1
    token, chat = cfg["telegram"]["token"], cfg["telegram"]["chat_id"]
    if args.document:
        send_document(token, chat, args.document, args.caption)
        print(json.dumps({"sent_document": args.document}))
        return 0
    text = args.text
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    send(token, chat, text)
    print(json.dumps({"sent": True, "chars": len(text)}))
    return 0


def enrich_main() -> int:
    from .enrich import main
    return main()


def map_main() -> int:
    from .mapgen import main
    return main()


def rescore_main() -> int:
    cfg = load_config()
    con = db.connect(cfg["db_path"])
    rows = con.execute("SELECT * FROM listings").fetchall()
    passed = 0
    for r in rows:
        lst = Listing(
            source=r["source"], source_id=r["source_id"], url=r["url"] or "",
            title=r["title"] or "", description=r["description"] or "",
            price_byn=r["price_byn"], price_usd=r["price_usd"],
            price_per_m2=r["price_per_m2"], area_m2=r["area_m2"],
            address=r["address"] or "", town=r["town"] or "",
            district=r["district"] or "", region=r["region"] or "",
            property_type=r["property_type"] or "", floor=r["floor"],
            floors=r["floors"], ceiling_height_m=r["ceiling_height_m"],
            area_min_m2=r["area_min_m2"],
            heated=None if r["heated"] is None else bool(r["heated"]),
            lat=r["lat"], lon=r["lon"],
            metro=r["metro"] or "",
            images=json.loads(r["images"] or "[]"),
            attrs=json.loads(r["attrs"] or "{}"),
        )
        ok, reason, flags = apply_rules(lst, cfg["profile"])
        passed += ok
        con.execute(
            "INSERT INTO scores (listing_id, rule_pass, rule_reject_reason, rule_flags, "
            "score, scored_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(listing_id) DO UPDATE SET rule_pass=excluded.rule_pass, "
            "rule_reject_reason=excluded.rule_reject_reason, "
            "rule_flags=excluded.rule_flags, score=excluded.score, "
            "scored_at=excluded.scored_at",
            (r["id"], int(ok), reason, json.dumps(flags, ensure_ascii=False),
             heuristic_score(lst, flags, cfg["profile"]) if ok else None,
             db.now_iso()))
    con.commit()
    print(json.dumps({"rescored": len(rows), "pass": passed}))
    return 0
