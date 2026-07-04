"""Еженедельный дайджест в Telegram: top-N новых, изменения цен, исчезнувшие,
vision-анализ фото top-N, футер здоровья. Отправляется всегда, даже пустой.

Запуск: .venv/bin/python -m padel_monitor.weekly
"""

import json
import sys

from . import db
from .config import load_config
from .scoring import vision_analyze
from .telegram import esc, send

CHECK = {True: "✓", False: "✗", None: "?"}


def attr_line(attrs: dict, floor) -> str:
    first = None if floor is None else floor == 1
    return (f"{CHECK[first]} 1 этаж  "
            f"{CHECK[bool(attrs.get('separate_entrance')) or None]} отд. вход  "
            f"{CHECK[bool(attrs.get('parking')) or None]} парковка")


def fmt_listing(r, vision_note: str = "") -> str:
    attrs = json.loads(r["attrs"] or "{}")
    flags = json.loads(r["rule_flags"] or "[]")
    price = (f"{r['price_byn']:.0f} BYN/мес" if r["price_byn"]
             else f"{r['price_usd']:.0f} USD/мес" if r["price_usd"] else "цена не указана")
    h = (f"выс. {r['ceiling_height_m']:g} м" if r["ceiling_height_m"]
         else "высота не указана")
    area = f"{r['area_m2']:.0f} м²" if r["area_m2"] else "площадь ?"
    lines = [
        f"<b>[{r['score'] or '—'}/100]</b> {esc(r['property_type'])}, {area}, {h}",
        f"{esc(r['address'] or r['town'])} | {price}"
        + (f" ({r['price_per_m2']:g}/м²)" if r["price_per_m2"] else ""),
        attr_line(attrs, r["floor"]) + (f"  Ⓜ {esc(r['metro'])}" if r["metro"] else ""),
    ]
    if "two_courts" in flags:
        lines.append("⭐ влезают 2 корта (450+ м²)")
    if r["llm_notes"]:
        n = json.loads(r["llm_notes"])
        if n.get("why"):
            lines.append(f"Почему: {esc(n['why'])}")
        if n.get("risks"):
            lines.append(f"Риски: {esc(n['risks'])}")
    if vision_note:
        lines.append(f"📷 {esc(vision_note)}")
    lines.append(f'{esc(r["source"])} | {esc(r["url"])}')
    return "\n".join(lines)


def main() -> int:
    cfg = load_config()
    con = db.connect(cfg["db_path"])
    top_n = cfg["profile"]["top_n"]

    new_rows = con.execute("""
        SELECT l.*, s.score, s.rule_flags, s.llm_verdict, s.llm_notes
        FROM listings l JOIN scores s ON s.listing_id = l.id
        WHERE s.rule_pass = 1 AND l.status = 'active'
          AND l.first_seen_at >= datetime('now', '-7 days')
          AND l.id NOT IN (SELECT listing_id FROM reported WHERE kind='new')
        ORDER BY s.score DESC, l.first_seen_at DESC LIMIT ?""",
        (top_n,)).fetchall()

    price_changes = con.execute("""
        SELECT l.title, l.url, l.source, e.old_value, e.new_value
        FROM events e JOIN listings l ON l.id = e.listing_id
        JOIN scores s ON s.listing_id = l.id AND s.rule_pass = 1
        WHERE e.kind = 'price_change' AND e.ts >= datetime('now', '-7 days')
        LIMIT 10""").fetchall()

    gone = con.execute("""
        SELECT l.title, l.url FROM events e JOIN listings l ON l.id = e.listing_id
        WHERE e.kind = 'gone' AND e.ts >= datetime('now', '-7 days')
          AND e.listing_id IN (SELECT listing_id FROM reported)
        LIMIT 10""").fetchall()

    runs = con.execute("""
        SELECT source, COUNT(*) n, SUM(ok) ok_n, MAX(finished_at) last
        FROM runs WHERE started_at >= datetime('now', '-7 days')
        GROUP BY source""").fetchall()

    # vision по фото top-N (если есть API-ключ)
    vision_notes = {}
    if cfg["anthropic_api_key"]:
        for r in new_rows[:cfg["scoring"]["vision_max_listings"]]:
            imgs = json.loads(r["images"] or "[]")
            res = vision_analyze(cfg["anthropic_api_key"],
                                 cfg["scoring"]["vision_model"], imgs,
                                 cfg["scoring"]["vision_max_images"])
            if res:
                note = res.get("note", "")
                if res.get("height_estimate_m"):
                    note = f"высота ~{res['height_estimate_m']} м; " + note
                if res.get("columns") == "есть":
                    note = "⚠ видны колонны; " + note
                vision_notes[r["id"]] = note
                con.execute("UPDATE scores SET vision_notes=? WHERE listing_id=?",
                            (json.dumps(res, ensure_ascii=False), r["id"]))

    parts = ["<b>🎾 Падел-монитор: недельный отчёт</b>", ""]
    if new_rows:
        parts.append(f"<b>Новые за неделю (top-{len(new_rows)}):</b>")
        for r in new_rows:
            parts += ["", fmt_listing(r, vision_notes.get(r["id"], ""))]
    else:
        parts.append("Новых подходящих вариантов за неделю нет.")

    if price_changes:
        parts += ["", "<b>Изменения цены:</b>"]
        for r in price_changes:
            parts.append(f"• {esc(r['title'][:80])}: {r['old_value']} → "
                         f"{r['new_value']} | {esc(r['url'])}")
    if gone:
        parts += ["", "<b>Исчезли из выдачи:</b>"]
        parts += [f"• {esc(r['title'][:80])} | {esc(r['url'])}" for r in gone]

    parts += ["", "<i>Система:</i>"]
    if runs:
        for r in runs:
            parts.append(f"<i>{r['source']}: {r['ok_n']}/{r['n']} успешных прогонов, "
                         f"последний {r['last'][:16]}</i>")
    else:
        parts.append("<i>⚠ за неделю не было ни одного прогона сбора!</i>")
    if not cfg["anthropic_api_key"]:
        parts.append("<i>LLM/vision выключены (нет ANTHROPIC_API_KEY) — "
                     "score эвристический</i>")

    send(cfg["telegram"]["token"], cfg["telegram"]["chat_id"], "\n".join(parts))
    ts = db.now_iso()
    for r in new_rows:
        con.execute("INSERT INTO reported (listing_id, report_ts, kind) VALUES (?,?,'new')",
                    (r["id"], ts))
    con.commit()
    print(f"report sent: {len(new_rows)} new, {len(price_changes)} price changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
