"""padel-enrich: detail-обогащение топ-кандидатов недели.

Листинг даёт обрезанное описание и ≤8 фото. Detail-страницы дают полное
описание, все фото и часто явную высоту потолков — это заметно повышает
точность судейства. Тянем щадяще: только топ-N новых кандидатов, только
не обогащённых (enriched_at IS NULL), с задержками. Ошибки по объявлению
пропускаем — enrich не должен ронять отчёт.
"""

import json
import sys
import traceback

from . import db
from .adapters import kufar, nca_auctions, realt
from .adapters.base import AdapterStop, fetch
from .config import load_config
from .normalize import Listing

PARSERS = {"realt": realt.parse_detail, "kufar": kufar.parse_detail,
           "nca-auction": nca_auctions.parse_detail}


def _listing_from_row(r) -> Listing:
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
        lat=r["lat"], lon=r["lon"], metro=r["metro"] or "",
        images=json.loads(r["images"] or "[]"),
        attrs=json.loads(r["attrs"] or "{}"),
    )


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=None,
                    help="сколько кандидатов обогащать (по умолчанию из config)")
    args = ap.parse_args()

    cfg = load_config()
    con = db.connect(cfg["db_path"])
    top_n = args.top or cfg["report"].get("enrich_top_n", 20)
    delay = cfg["report"].get("enrich_delay_s", 4)

    rows = con.execute("""
        SELECT l.* FROM listings l JOIN scores s ON s.listing_id = l.id
        WHERE s.rule_pass = 1 AND l.status = 'active' AND l.enriched_at IS NULL
          AND l.source IN ('realt', 'kufar', 'nca-auction')
          AND l.first_seen_at >= datetime('now', '-7 days')
          AND l.id NOT IN (SELECT listing_id FROM reported WHERE kind='new')
        ORDER BY s.score DESC LIMIT ?""", (top_n,)).fetchall()

    enriched = errors = 0
    for r in rows:
        parser = PARSERS.get(r["source"])
        if not parser:
            continue
        try:
            html = fetch(r["url"], cfg["raw_dir"],
                         f"detail_{r['source']}_{r['source_id']}", delay)
            fields = parser(html, r["url"])
        except AdapterStop as e:
            print(f"[enrich] STOP {r['url']}: {e}", file=sys.stderr)
            errors += 1
            continue
        except Exception as e:
            print(f"[enrich] {type(e).__name__} {r['url']}: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            errors += 1
            continue

        sets, vals = [], []
        for k, v in fields.items():
            sets.append(f"{k}=?")
            vals.append(json.dumps(v, ensure_ascii=False) if k == "images" else v)
        sets.append("enriched_at=?")
        vals.append(db.now_iso())
        con.execute(f"UPDATE listings SET {','.join(sets)} WHERE id=?",
                    vals + [r["id"]])
        # пересчёт правил/pre-score по обогащённым данным
        fresh = con.execute("SELECT * FROM listings WHERE id=?", (r["id"],)).fetchone()
        from .rules import apply_rules, heuristic_score
        lst = _listing_from_row(fresh)
        ok, reason, flags = apply_rules(lst, cfg["profile"])
        con.execute(
            "UPDATE scores SET rule_pass=?, rule_reject_reason=?, rule_flags=?, "
            "score=?, scored_at=? WHERE listing_id=?",
            (int(ok), reason, json.dumps(flags, ensure_ascii=False),
             heuristic_score(lst, flags, cfg["profile"]) if ok else None,
             db.now_iso(), r["id"]))
        con.commit()
        enriched += 1

    print(json.dumps({"enriched": enriched, "errors": errors,
                      "candidates_seen": len(rows)}, ensure_ascii=False))
    return 0
