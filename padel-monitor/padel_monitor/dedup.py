"""Межсайтовый дедуп: одно помещение на realt и kufar не должно занимать
два слота топа и дважды алертить.

Кандидаты в дубли — пары активных объявлений РАЗНЫХ источников с близкими
координатами (<150 м) и совпадающей площадью (±5%), либо — при отсутствии
координат — с одинаковым нормализованным адресом (улица+дом). Группы пишутся
в dup_groups; представитель группы выбирается в padel-candidates.
"""

import re

from .geo import _haversine


def _norm_addr(addr: str) -> str:
    a = (addr or "").lower()
    a = re.sub(r"\b(минск|минская обл\w*|область|район|ул\.?|улица|пер\.?|переулок|"
               r"пр-т|проспект|д\.?|дом)\b", " ", a)
    a = re.sub(r"[^\w\s]", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def _same(a, b) -> bool:
    if a["source"] == b["source"]:
        return False
    aa, ab = a["area_m2"], b["area_m2"]
    area_ok = aa and ab and abs(aa - ab) <= 0.05 * max(aa, ab)
    if a["lat"] and b["lat"]:
        if _haversine(a["lat"], a["lon"], b["lat"], b["lon"]) <= 0.15:
            return bool(area_ok)
        return False
    na, nb = _norm_addr(a["address"]), _norm_addr(b["address"])
    return bool(na and na == nb and area_ok)


def rebuild(con) -> int:
    """Пересобирает dup_groups по активным объявлениям. Возвращает число групп."""
    rows = [dict(r) for r in con.execute(
        "SELECT id, source, area_m2, lat, lon, address FROM listings "
        "WHERE status='active'")]
    con.execute("DELETE FROM dup_groups")
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # союзы только между разными источниками при совпадении
    by_source: dict[str, list] = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)
    srcs = list(by_source)
    for i in range(len(srcs)):
        for j in range(i + 1, len(srcs)):
            for a in by_source[srcs[i]]:
                for b in by_source[srcs[j]]:
                    if _same(a, b):
                        parent[find(a["id"])] = find(b["id"])

    groups = 0
    seen_roots = set()
    for r in rows:
        root = find(r["id"])
        members = [x["id"] for x in rows if find(x["id"]) == root]
        if len(members) > 1:
            con.execute("INSERT OR REPLACE INTO dup_groups (listing_id, group_id) "
                        "VALUES (?,?)", (r["id"], root))
            if root not in seen_roots:
                seen_roots.add(root)
                groups += 1
    return groups
