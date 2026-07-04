"""Еженедельный дайджест: кандидаты → vision-скрининг фото → судья (Opus)
→ отчёт в Telegram со сравнением с прошлыми лидерами. Отправляется всегда.

Запуск: .venv/bin/python -m padel_monitor.weekly
"""

import json
import sys

from . import db
from .config import load_config
from .scoring import judge, vision_screen
from .telegram import esc, send

CHECK = {True: "✓", False: "✗", None: "?"}


def attr_line(attrs: dict, floor) -> str:
    first = None if floor is None else floor == 1
    return (f"{CHECK[first]} 1 этаж  "
            f"{CHECK[bool(attrs.get('separate_entrance')) or None]} отд. вход  "
            f"{CHECK[bool(attrs.get('parking')) or None]} парковка")


def listing_brief(r) -> dict:
    return {k: r[k] for k in
            ("title", "description", "area_m2", "area_min_m2", "ceiling_height_m",
             "heated", "price_byn", "price_usd", "price_per_m2", "address",
             "property_type", "floor", "metro")}


def fmt_listing(r, vision: dict | None, verdict: dict | None) -> str:
    attrs = json.loads(r["attrs"] or "{}")
    score = verdict["final_score"] if verdict else (r["final_score"] or r["score"])
    price = (f"{r['price_byn']:.0f} BYN/мес" if r["price_byn"]
             else f"{r['price_usd']:.0f} USD/мес" if r["price_usd"] else "цена не указана")
    if r["ceiling_height_m"]:
        h = f"выс. {r['ceiling_height_m']:g} м"
    elif vision and vision.get("height_estimate_m"):
        h = f"выс. ~{vision['height_estimate_m']:g} м (по фото)"
    else:
        h = "высота ?"
    area = f"{r['area_m2']:.0f} м²" if r["area_m2"] else "площадь ?"
    if r["area_min_m2"] and r["area_m2"] and r["area_min_m2"] < r["area_m2"]:
        area += f" (от {r['area_min_m2']:.0f})"
    heat = {1: "отапл.", 0: "⚠ без отопления"}.get(r["heated"], "отопление ?")

    lines = [
        f"<b>[{score or '—'}/100]</b> {esc(r['property_type'])}, {area}, {h}, {heat}",
        f"{esc(r['address'] or r['town'])} | {price}"
        + (f" ({r['price_per_m2']:g}/м²)" if r["price_per_m2"] else ""),
        attr_line(attrs, r["floor"]) + (f"  Ⓜ {esc(r['metro'])}" if r["metro"] else ""),
    ]
    if verdict:
        lines.append(f"<b>{esc(verdict['verdict'])}</b> — {esc(verdict['why'])}")
        if verdict.get("risks"):
            lines.append(f"Риски: {esc(verdict['risks'])}")
        if verdict.get("vs_previous"):
            lines.append(f"⚖ {esc(verdict['vs_previous'])}")
    elif r["llm_notes"]:
        n = json.loads(r["llm_notes"])
        if n.get("why"):
            lines.append(f"Почему: {esc(n['why'])}")
        if n.get("risks"):
            lines.append(f"Риски: {esc(n['risks'])}")
    if vision:
        note = vision.get("note", "")
        if vision.get("columns") == "есть":
            note = "⚠ на фото видны колонны. " + note
        lines.append(f"📷 {esc(note)}")
    lines.append(f'{esc(r["source"])} | {esc(r["url"])}')
    return "\n".join(lines)


def run_vision(con, cfg, rows) -> dict[int, dict]:
    """Скрининг фото. Кеш: scores.vision_notes переиспользуется."""
    out = {}
    for r in rows[:cfg["scoring"]["vision_max_listings"]]:
        if r["vision_notes"]:
            out[r["id"]] = json.loads(r["vision_notes"])
            continue
        imgs = json.loads(r["images"] or "[]")
        res = vision_screen(cfg["anthropic_api_key"], cfg["scoring"]["vision_model"],
                            imgs, cfg["scoring"]["vision_max_images"])
        if res:
            out[r["id"]] = res
            con.execute("UPDATE scores SET vision_notes=? WHERE listing_id=?",
                        (json.dumps(res, ensure_ascii=False), r["id"]))
            con.commit()
    return out


def run_judge(con, cfg, rows, vision_notes) -> tuple[dict[int, dict], str]:
    """Финальное ранжирование Opus-судьёй + сравнение с прошлыми лидерами."""
    top = rows[:cfg["scoring"]["judge_max_candidates"]]
    candidates = []
    for r in top:
        cand = {"id": r["id"], "listing": listing_brief(r)}
        if r["llm_notes"]:
            cand["text_review"] = json.loads(r["llm_notes"])
        if r["id"] in vision_notes:
            cand["photos"] = vision_notes[r["id"]]
        candidates.append(cand)

    prev = con.execute("""
        SELECT l.*, s.final_score, s.judge_notes FROM listings l
        JOIN scores s ON s.listing_id = l.id
        JOIN reported rep ON rep.listing_id = l.id
        WHERE l.status='active' AND s.final_score IS NOT NULL
        GROUP BY l.id ORDER BY s.final_score DESC LIMIT ?""",
        (cfg["scoring"]["prev_leaders"],)).fetchall()
    previous = [{"listing": listing_brief(p), "final_score": p["final_score"],
                 "judge_why": (json.loads(p["judge_notes"]) or {}).get("why", "")
                 if p["judge_notes"] else ""} for p in prev]

    res = judge(cfg["anthropic_api_key"], cfg["scoring"]["judge_model"],
                candidates, previous)
    if not res:
        return {}, ""
    verdicts = {}
    for v in res.get("verdicts", []):
        verdicts[v["id"]] = v
        con.execute("UPDATE scores SET final_score=?, judge_notes=? WHERE listing_id=?",
                    (v["final_score"], json.dumps(v, ensure_ascii=False), v["id"]))
    con.commit()
    return verdicts, res.get("week_summary", "")


def main() -> int:
    cfg = load_config()
    con = db.connect(cfg["db_path"])
    top_n = cfg["profile"]["top_n"]
    llm_on = bool(cfg["anthropic_api_key"])

    new_rows = con.execute("""
        SELECT l.*, s.score, s.final_score, s.rule_flags, s.llm_notes, s.vision_notes
        FROM listings l JOIN scores s ON s.listing_id = l.id
        WHERE s.rule_pass = 1 AND l.status = 'active'
          AND l.first_seen_at >= datetime('now', '-7 days')
          AND l.id NOT IN (SELECT listing_id FROM reported WHERE kind='new')
        ORDER BY s.score DESC, l.first_seen_at DESC""").fetchall()

    vision_notes: dict[int, dict] = {}
    verdicts: dict[int, dict] = {}
    week_summary = ""
    if llm_on and new_rows:
        vision_notes = run_vision(con, cfg, new_rows)
        verdicts, week_summary = run_judge(con, cfg, new_rows, vision_notes)

    # порядок отчёта: по финальному score судьи, затем по эвристике
    def sort_key(r):
        v = verdicts.get(r["id"])
        return -(v["final_score"] if v else (r["score"] or 0))
    shown = sorted(new_rows, key=sort_key)[:top_n]

    price_changes = con.execute("""
        SELECT l.title, l.url, e.old_value, e.new_value
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

    parts = ["<b>🎾 Падел-монитор: недельный отчёт</b>"]
    if week_summary:
        parts += ["", f"<i>{esc(week_summary)}</i>"]
    if shown:
        parts += ["", f"<b>Кандидаты недели (top-{len(shown)}):</b>"]
        for r in shown:
            parts += ["", fmt_listing(r, vision_notes.get(r["id"]),
                                      verdicts.get(r["id"]))]
    else:
        parts += ["", "Новых подходящих вариантов за неделю нет."]

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
    if not llm_on:
        parts.append("<i>⚠ LLM/vision выключены (нет ANTHROPIC_API_KEY) — "
                     "оценка эвристическая, фото не проанализированы</i>")

    send(cfg["telegram"]["token"], cfg["telegram"]["chat_id"], "\n".join(parts))
    ts = db.now_iso()
    for r in shown:
        con.execute("INSERT INTO reported (listing_id, report_ts, kind) VALUES (?,?,'new')",
                    (r["id"], ts))
    con.commit()
    print(f"report sent: {len(shown)} shown, judge={'on' if verdicts else 'off'}, "
          f"vision={len(vision_notes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
