"""padel-inbox: приём команд из Telegram (pull через getUpdates).

Постоянно живущий процесс не нужен — команды забираются на каждом прогоне
(в padel-collect) и/или отдельным частым cron. Пишешь боту в Telegram —
вариант исключается/помечается детерминированно в БД (user_actions), а не
только через судью.

Команды (регистр и точная форма не важны):
  отпало 175            скрыть вариант из отчётов (также: скрыть/нет/убери/удали, /hide 175)
  верни 175             вернуть скрытый (restore/вернуть, /restore 175)
  наблюдать 175         в блок «На контроле» (watch/следить, /watch 175)
  финалист 175          пометить финалистом (/finalist 175)
  звонил 175: текст     записать итог звонка (позвонил/called)
  175: текст            заметка к варианту (её увидит судья)
  /top                  топ-5 доступных сейчас
  /watchlist            что на контроле
  /why 175              почему такой вердикт
  /help                 список команд
"""

import json
import re
import sys

from . import db
from .config import load_config
from .telegram import esc, get_updates, send

HELP = (
    "<b>🎾 Падел-монитор — команды</b>\n"
    "<code>отпало 175</code> — скрыть вариант из отчётов\n"
    "<code>верни 175</code> — вернуть скрытый\n"
    "<code>наблюдать 175</code> — в блок «На контроле»\n"
    "<code>финалист 175</code> — пометить финалистом\n"
    "<code>звонил 175: высота 7м, торг</code> — записать звонок\n"
    "<code>175: заметка</code> — заметка (увидит судья)\n"
    "<code>/top</code> — топ-5 доступных сейчас\n"
    "<code>/watchlist</code> — что на контроле\n"
    "<code>/why 175</code> — почему такой вердикт\n"
    "<code>/help</code> — этот список\n"
    "id вариантов бери из отчёта (в каждой карточке «id N»)."
)

# (regex, action) — первое совпадение выигрывает
RULES = [
    (r"^\s*(?:отпал\w*|скрыть|скрой|нет|убери|удали|hide|/hide)\D{0,4}(\d+)", "veto"),
    (r"^\s*(?:верни\w*|вернуть|restore|/restore)\D{0,4}(\d+)", "restore"),
    (r"^\s*(?:наблюд\w*|следить|watch|/watch)\D{0,4}(\d+)", "watch"),
    (r"^\s*(?:финалист|finalist|/finalist)\D{0,4}(\d+)", "finalist"),
    (r"^\s*(?:звонил|позвонил|called)\D{0,4}(\d+)\s*:?\s*(.*)$", "called"),
    (r"^\s*(?:смотрю|смотрел|visited)\D{0,4}(\d+)\s*:?\s*(.*)$", "visited"),
    (r"^\s*(\d+)\s*:\s*(.+)$", "note"),
]
ACTION_MSG = {"veto": "🚫 скрыл {id} — не покажу в отчётах",
              "restore": "↩️ вернул {id}",
              "watch": "👀 {id} в наблюдении",
              "finalist": "🏆 {id} — финалист",
              "called": "📞 записал звонок по {id}",
              "visited": "🏠 отметил осмотр {id}",
              "note": "📝 заметка к {id} сохранена"}


def _listing(con, lid: int):
    return con.execute(
        "SELECT l.*, s.score, s.final_score, s.judge_notes FROM listings l "
        "LEFT JOIN scores s ON s.listing_id=l.id WHERE l.id=?", (lid,)).fetchone()


def _brief(r) -> str:
    area = f"{r['area_m2']:.0f} м²" if r["area_m2"] else "площадь ?"
    h = f"выс. {r['ceiling_height_m']:g} м" if r["ceiling_height_m"] else "выс. ?"
    price = (f"{r['price_byn']:.0f} BYN" if r["price_byn"]
             else f"{r['price_usd']:.0f} USD" if r["price_usd"] else "цена ?")
    return f"{esc(r['property_type'])}, {area}, {h}, {price} · {esc(r['address'] or r['town'])}"


def _cmd_top(con) -> str:
    veto = db.vetoed_ids(con)
    rows = con.execute("""
        SELECT l.*, s.score FROM listings l JOIN scores s ON s.listing_id=l.id
        WHERE s.rule_pass=1 AND l.status='active' AND l.source!='nca-auction'
        ORDER BY s.score DESC LIMIT 12""").fetchall()
    rows = [r for r in rows if r["id"] not in veto][:5]
    if not rows:
        return "Сейчас нет доступных вариантов."
    out = ["<b>Топ-5 доступных сейчас:</b>"]
    for r in rows:
        out.append(f"<b>[{r['score']}] id {r['id']}</b> — {_brief(r)}\n{esc(r['url'])}")
    return "\n".join(out)


def _cmd_watchlist(con) -> str:
    acts = db.latest_actions(con)
    ids = [lid for lid, a in acts.items()
           if a["action"] in ("watch", "finalist", "called", "visited")]
    if not ids:
        return "Список наблюдения пуст. Добавь: <code>наблюдать 175</code>"
    out = ["<b>👀 На контроле:</b>"]
    for lid in ids:
        r = _listing(con, lid)
        if not r or r["status"] != "active":
            continue
        a = acts[lid]
        note = f" — {esc(a['note'])}" if a.get("note") else ""
        out.append(f"<b>{a['action']} id {lid}</b>{note}\n{_brief(r)}\n{esc(r['url'])}")
    return "\n".join(out)


def _cmd_why(con, lid: int) -> str:
    r = _listing(con, lid)
    if not r:
        return f"Вариант {lid} не найден."
    if r["judge_notes"]:
        j = json.loads(r["judge_notes"])
        parts = [f"<b>[{r['final_score'] or r['score']}] id {lid}</b> — {_brief(r)}"]
        for k, label in (("verdict", "Вердикт"), ("why", "Почему"),
                         ("risks", "Риски"), ("fitout", "Ремонт"),
                         ("price_note", "Цена"), ("vs_previous", "Против прошлых")):
            if j.get(k):
                parts.append(f"<i>{label}:</i> {esc(j[k])}")
        return "\n".join(parts)
    return (f"<b>[{r['score']}] id {lid}</b> — {_brief(r)}\nСудья ещё не оценивал "
            f"детально (появится в ближайшем отчёте).")


def _apply(con, text: str) -> str | None:
    low = text.strip()
    if low.lower() in ("/start", "/help", "помощь", "help"):
        return HELP
    if low.lower().startswith("/top"):
        return _cmd_top(con)
    if low.lower().startswith("/watchlist"):
        return _cmd_watchlist(con)
    m = re.match(r"^/why\D{0,4}(\d+)", low, re.I)
    if m:
        return _cmd_why(con, int(m.group(1)))
    for rx, action in RULES:
        m = re.match(rx, low, re.I)
        if not m:
            continue
        lid = int(m.group(1))
        if not _listing(con, lid):
            return f"Вариант {lid} не найден — проверь id из отчёта."
        note = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else None
        db.set_action(con, lid, action, note)
        return ACTION_MSG[action].format(id=lid)
    return None  # не команда — молча игнорируем (обычный текст/пересланное)


def process(con, cfg) -> dict:
    """Забрать и применить команды. Возвращает сводку (без печати)."""
    token, chat = cfg["telegram"]["token"], cfg["telegram"]["chat_id"]
    if not token:
        return {"skipped": "no token"}
    offset = int(db.get_state(con, "tg_offset", 0))
    updates = get_updates(token, offset)
    applied = 0
    for u in updates:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        if (msg.get("chat") or {}).get("id") != chat:
            continue  # игнорируем чужие чаты
        text = msg.get("text") or ""
        if not text:
            continue
        reply = _apply(con, text)
        if reply:
            send(token, chat, reply)
            applied += 1
    db.set_state(con, "tg_offset", offset)
    con.commit()
    return {"updates": len(updates), "applied": applied, "offset": offset}


def main() -> int:
    cfg = load_config()
    if not cfg["telegram"]["token"]:
        print("TELEGRAM_BOT_TOKEN не задан", file=sys.stderr)
        return 1
    con = db.connect(cfg["db_path"])
    print(json.dumps(process(con, cfg), ensure_ascii=False))
    return 0
