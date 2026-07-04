"""Ежедневный прогон: сбор → SQLite → dedup → правила → скоринг → healthcheck.

Запуск: .venv/bin/python -m padel_monitor.crawl
"""

import json
import sys
import traceback

import httpx

from . import db
from .adapters import kufar, megapolis, realt
from .adapters.base import AdapterStop
from .config import load_config
from .normalize import Listing
from .rules import apply_rules, heuristic_score
from .scoring import llm_score

ADAPTERS = {"realt": realt, "kufar": kufar, "megapolis": megapolis}


def score_listing(con, cfg: dict, lid: int, lst: Listing, row: dict):
    ok, reason, flags = apply_rules(lst, cfg["profile"])
    score, verdict, notes = None, "", ""
    if ok:
        score = heuristic_score(lst, flags, cfg["profile"])
        if cfg["anthropic_api_key"]:
            res = llm_score(cfg["anthropic_api_key"], cfg["scoring"]["llm_model"], row)
            if res:
                # LLM уточняет, но не может поднять отказ правил
                score = int((score + int(res.get("score", score))) / 2)
                verdict = res.get("verdict", "")
                notes = json.dumps(res, ensure_ascii=False)
    con.execute(
        "INSERT INTO scores (listing_id, rule_pass, rule_reject_reason, rule_flags, "
        "score, llm_verdict, llm_notes, scored_at) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(listing_id) DO UPDATE SET rule_pass=excluded.rule_pass, "
        "rule_reject_reason=excluded.rule_reject_reason, rule_flags=excluded.rule_flags, "
        "score=excluded.score, llm_verdict=excluded.llm_verdict, "
        "llm_notes=excluded.llm_notes, scored_at=excluded.scored_at",
        (lid, int(ok), reason, json.dumps(flags, ensure_ascii=False),
         score, verdict, notes, db.now_iso()))


def main() -> int:
    cfg = load_config()
    con = db.connect(cfg["db_path"])
    any_ok = False
    for name, mod in ADAPTERS.items():
        src_cfg = cfg["sources"].get(name) or {}
        if not src_cfg.get("enabled"):
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
                    score_listing(con, cfg, lid, lst, lst.to_row())
            db.mark_gone(con, name)
            db.log_run(con, name, started, True, found, new, changed)
            any_ok = True
            print(f"[{name}] ok: found={found} new={new} changed={changed}")
        except AdapterStop as e:
            db.log_run(con, name, started, False, found, new, changed,
                       f"STOP: {e}")
            print(f"[{name}] STOP: {e}", file=sys.stderr)
        except Exception as e:
            db.log_run(con, name, started, False, found, new, changed,
                       f"{type(e).__name__}: {e}")
            print(f"[{name}] error: {e}\n{traceback.format_exc()}", file=sys.stderr)
        con.commit()
    if any_ok and cfg["healthchecks_url"]:
        try:
            httpx.get(cfg["healthchecks_url"], timeout=15)
        except httpx.HTTPError:
            pass
    return 0 if any_ok else 1


if __name__ == "__main__":
    sys.exit(main())
