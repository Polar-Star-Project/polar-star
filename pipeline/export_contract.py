"""Polar Star's data contract for Ariadne's Clew (master plan phase 6).

Usage:  python pipeline/export_contract.py
Writes data/contract/ (published with the rest of the repository):
  entities.jsonl  organizations Polar Star records money paid to, keyed by their federal Unique Entity ID (uei:...)
  claims.jsonl    who was paid by which agency program, in which window, how much (USAspending, T1)
  sources.jsonl   where each claim comes from
Only payees with a UEI are exported: the hub links projects by strong IDs, never by name. Private people are never in the
input files (other_agencies.py leaves them out), so they cannot reach the export.
"""
import csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"
OUT = ROOT / "data" / "contract"
USASPENDING = {"source_id": "usaspending:other_money", "url": "https://www.usaspending.gov/search", "publisher": "USAspending.gov (U.S. Treasury)",
               "license": "US public domain"}


def rows(name):
    p = REF / name
    return list(csv.DictReader(open(p, encoding="utf-8"), delimiter="|")) if p.exists() else []


def build(ref=None, out=None):
    global REF, OUT
    REF, OUT = Path(ref or REF), Path(out or OUT)
    meta = json.loads((REF / "other_money_meta.json").read_text(encoding="utf-8")) if (REF / "other_money_meta.json").exists() else {}
    window = {"from": meta.get("from"), "to": meta.get("to"), "read": meta.get("read")}
    ents, claims, no_uei = {}, [], 0
    paid = [(r["agency"], r["program"], r) for r in rows("other_money_payees.csv")] + [("ICE", "contracts", r) for r in rows("ice_payees_all.csv")]
    for agency, program, r in paid:
        uei = (r.get("uei") or "").strip()
        if not uei:
            no_uei += 1; continue
        gid = f"uei:{uei}"
        e = ents.setdefault(gid, {"global_id": gid, "type": "org", "names": [], "identifiers": {"uei": [gid]}, "project": "polar-star"})
        if r["recipient"] not in e["names"]: e["names"].append(r["recipient"])
        claims.append({"subject": gid, "predicate": "paid_by", "object": f"program:{agency}/{program}", "amount_musd": float(r["musd"]),
                       "window": window, "tier": "T1", "basis": ["USAspending recipient row: name + UEI"], "source_id": USASPENDING["source_id"]})
    OUT.mkdir(parents=True, exist_ok=True)
    for fn, xs in (("entities.jsonl", sorted(ents.values(), key=lambda e: e["global_id"])), ("claims.jsonl", claims), ("sources.jsonl", [USASPENDING | {"retrieved_at": window["read"]}])):
        tmp = OUT / (fn + ".part")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for x in xs: f.write(json.dumps(x, sort_keys=True) + "\n")
        tmp.replace(OUT / fn)
    summary = {"entities": len(ents), "claims": len(claims), "payee_rows_without_uei": no_uei, "window": window}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
