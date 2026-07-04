"""Пересчёт правил и эвристики по всем объявлениям в базе.

Нужен после изменения падел-профиля или логики rules.py — ежедневный crawl
пересчитывает только новые/изменившиеся объявления.

Запуск: .venv/bin/python -m padel_monitor.rescore
"""

import json
import sys

from . import db
from .config import load_config
from .normalize import Listing
from .rules import apply_rules, heuristic_score


def row_to_listing(r) -> Listing:
    return Listing(
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
        metro=r["metro"] or "",
        images=json.loads(r["images"] or "[]"),
        attrs=json.loads(r["attrs"] or "{}"),
    )


def main() -> int:
    cfg = load_config()
    con = db.connect(cfg["db_path"])
    rows = con.execute("SELECT * FROM listings").fetchall()
    passed = 0
    for r in rows:
        lst = row_to_listing(r)
        ok, reason, flags = apply_rules(lst, cfg["profile"])
        score = heuristic_score(lst, flags, cfg["profile"]) if ok else None
        passed += ok
        con.execute(
            "INSERT INTO scores (listing_id, rule_pass, rule_reject_reason, rule_flags, "
            "score, scored_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(listing_id) DO UPDATE SET rule_pass=excluded.rule_pass, "
            "rule_reject_reason=excluded.rule_reject_reason, "
            "rule_flags=excluded.rule_flags, score=excluded.score, "
            "scored_at=excluded.scored_at",
            (r["id"], int(ok), reason, json.dumps(flags, ensure_ascii=False),
             score, db.now_iso()))
    con.commit()
    print(f"rescored {len(rows)}: {passed} pass rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
