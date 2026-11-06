"""Political donations from people who work for detention and removal contractors, from the FEC's public records.

Usage:  python pipeline/money_donors.py                         (needs FEC_API_KEY; GitHub Actions: totals only)
        python pipeline/money_donors.py --restricted <folder>   (on the publisher's machine: totals, plus the named rows in <folder>)

The public repository and page get totals only: per company and recipient committee, the dollars, the number of gifts and the
number of distinct people. Donors are private individuals, so their names are never written inside the repository or printed
to a log. With --restricted, the named rows are also written to <folder>/fec_donors.csv, which must exist and must be outside
the repository (the publisher's encrypted store).

What it reads: itemized individual contributions (Schedule A) whose donor reported one of the companies below as employer,
in the current election cycle and the one before. Only contributions over $200 a year are itemized with a name, so smaller
ones are not here.

What it keeps, per contribution: the donor's name, employer and occupation exactly as the donor reported them, the state, the
amount, the date, the recipient committee, and a link to the FEC's image of the filing. It NEVER keeps a street address,
city or ZIP. Federal law (52 U.S.C. 30111(a)(4)) forbids using these names to ask for money or for any commercial purpose;
this project uses them only for a non-commercial public record.

Double counting: contributions made through WinRed or ActBlue appear twice in FEC data (once at the conduit, once at the
candidate), and a gift to a joint fundraiser reappears as memo entries at each participant. Rows filed by a conduit and memo
entries (memo code X) are dropped; the same name, date, amount and committee is kept once.

Recipients are tied to a member of Congress only through the FEC's own links: a candidate's authorized committee, or the
sponsor of a leadership fund. A committee linked to more than one person, or none, stays a committee.

Writes data/reference/fec_donor_totals.csv ("|" separated) and fec_donor_totals_meta.json. Without a key it stops and changes nothing.
"""
import argparse, csv, datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"
API = "https://api.open.fec.gov/v1"
SRC = "https://raw.githubusercontent.com/unitedstates/congress-legislators/gh-pages/"
# Companies whose main business is immigration detention or removal. Large firms where ICE work is a small share of what
# their staff do (Amentum, Akima, Ahtna) are left out: their employees' politics say little about detention.
# code: (queries sent to the FEC's employer search, pattern the reported employer must match after norm())
COMPANIES = {
    "GEO": (["GEO GROUP", "GEO SECURE SERVICES", "GEO CARE", "GEO TRANSPORT", "BI INCORPORATED"],
            r"^(?:THE )?GEO (?:GROUP|SECURE SERVICES|CARE|TRANSPORT|REENTRY)\b|^GEOGROUP\b|^BI INCORPORATED\b"),
    "CC": (["CORECIVIC", "CORE CIVIC", "CORRECTIONS CORPORATION OF AMERICA"],
           r"^CORE ?CIVIC\b|^CORRECTIONS CORP(?:ORATION)? OF AMERICA\b"),
    "MTC": (["MANAGEMENT TRAINING CORPORATION", "MANAGEMENT AND TRAINING CORPORATION", "MANAGEMENT TRAINING CORP"],
            r"^MANAGEMENT (?:AND )?TRAINING CORP"),
    "LAS": (["LASALLE CORRECTIONS", "LA SALLE CORRECTIONS", "LASALLE MANAGEMENT"],
            r"^LA ?SALLE (?:CORRECTIONS|MANAGEMENT)\b"),
    "ICA": (["IMMIGRATION CENTERS OF AMERICA"], r"^IMMIGRATION CENTERS OF AMERICA\b"),
    "CSI": (["CSI AVIATION"], r"^CSI AVIATION\b"),
}
CONDUITS = {"C00694323": "WinRed", "C00401224": "ActBlue"}
FIELDS = ["co", "cycle", "date", "name", "employer", "occupation", "state", "usd", "committee_id", "committee", "ctype", "party", "bioguide", "url"]
TOTAL_FIELDS = ["co", "committee_id", "committee", "ctype", "party", "bioguide", "usd", "gifts", "donors"]   # no field names a person
TITLES = {"MR", "MRS", "MS", "DR", "COL", "HON", "JR", "SR", "II", "III", "IV", "MD", "PHD", "ESQ"}


def norm(s):
    return " ".join(re.sub(r"[^A-Z0-9 ]+", " ", (s or "").upper().replace("&", " AND ")).split())


def company_of(employer):
    """Reported employer -> company code, or None. Matches the start of the field so 'GEOLOGY' or 'FORMER GEO GROUP' do not count."""
    e = norm(employer)
    for co, (_, pat) in COMPANIES.items():
        if re.search(pat, e): return co
    return None


def cycles(today):
    cur = today.year + today.year % 2; return [cur - 2, cur]


def keep(rows):
    """Schedule A records -> one row per real contribution: drop conduits and memo entries, then exact repeats."""
    out, seen = [], set()
    for r in rows:
        if r.get("committee_id") in CONDUITS or (r.get("memo_code") or "").upper() == "X": continue
        if (r.get("entity_type") or "IND") != "IND": continue
        co = company_of(r.get("contributor_employer"))
        if not co: continue
        k = (norm(r.get("contributor_name")), (r.get("contribution_receipt_date") or "")[:10], r.get("contribution_receipt_amount"), r.get("committee_id"))
        if k in seen: continue
        seen.add(k); out.append((co, r))
    return out


def filing_url(r, cycle=None):
    """The FEC's own record of this gift: its itemized-receipts search for the donor's name at the committee and cycle.
    Never the scanned filing image: images print the donor's street address, which this page promises never to show."""
    q = {"committee_id": r.get("committee_id") or "", "contributor_name": r.get("contributor_name") or r.get("name") or ""}
    if cycle: q["two_year_transaction_period"] = str(cycle)
    return "https://www.fec.gov/data/receipts/?" + urllib.parse.urlencode(q)


def clean(s):
    return " ".join((s or "").replace("|", "/").split())


def row(co, cyc, r, cinfo, member):
    cid = r.get("committee_id") or ""; ct, party, name = cinfo.get(cid, ("", "", ""))
    return {"co": co, "cycle": cyc, "date": (r.get("contribution_receipt_date") or "")[:10], "name": clean(r.get("contributor_name")),
            "employer": clean(r.get("contributor_employer")), "occupation": clean(r.get("contributor_occupation")),
            "state": (r.get("contributor_state") or "")[:2], "usd": round(float(r.get("contribution_receipt_amount") or 0), 2),
            "committee_id": cid, "committee": clean(name or (r.get("committee") or {}).get("name") or cid), "ctype": ct, "party": party,
            "bioguide": member.get(cid, ""), "url": filing_url(r, cyc)}


def person_keys(rows):
    """Named rows -> one key per row identifying the donor: the same person filed as "DOE, JANE", "DOE, JANE A." and
    "DOE, JANE A MRS" at the same company is one donor; two different middle initials under one name stay two people."""
    def parts(r):
        last, _, rest = (r["name"] or "").upper().partition(",")
        w = [x for x in re.sub(r"[^A-Z ]+", " ", rest).split() if x not in TITLES]
        return (r["co"], re.sub(r"[^A-Z ]+", " ", last).strip(), w[0] if w else ""), (w[1][:1] if len(w) > 1 else "")
    p = [parts(r) for r in rows]; mi = {}
    for b, m in p:
        mi.setdefault(b, set())
        if m: mi[b].add(m)
    return [b + ((m,) if len(mi[b]) > 1 else ()) for b, m in p]


def totals(rows):
    """Named rows -> (rows of TOTAL_FIELDS, summary). Counts only: nothing returned names, describes or locates a donor."""
    keys = person_keys(rows); by = {}
    for r, k in zip(rows, keys):
        g = by.setdefault((r["co"], r["committee_id"]), {"co": r["co"], "committee_id": r["committee_id"], "committee": r["committee"],
                                                         "ctype": r["ctype"], "party": r["party"], "bioguide": r["bioguide"], "usd": 0.0, "gifts": 0, "p": set()})
        g["usd"] += r["usd"]; g["gifts"] += 1; g["p"].add(k)
    out = sorted(({**{f: g[f] for f in TOTAL_FIELDS[:6]}, "usd": round(g["usd"], 2), "gifts": g["gifts"], "donors": len(g["p"])} for g in by.values()),
                 key=lambda x: (x["co"], -x["usd"], x["committee_id"]))
    def agg(sel):
        s = [(r, k) for r, k in zip(rows, keys) if sel(r)]
        return [round(sum(r["usd"] for r, _ in s), 2), len(s), len({k for _, k in s})]
    members = sorted({r["bioguide"] for r in rows if r["bioguide"]})
    small = [r["usd"] for r in rows if 0 < r["usd"] < 200]
    years = {}
    for r in rows: years[r["date"][:4]] = round(years.get(r["date"][:4], 0) + r["usd"], 2)
    return out, {"total": round(sum(r["usd"] for r in rows), 2), "gifts": len(rows), "people": len(set(keys)),
                 "small": [len(small), round(sum(small), 2)], "by_year": dict(sorted(years.items())),
                 "by_co": {co: agg(lambda r, co=co: r["co"] == co) for co in COMPANIES if any(r["co"] == co for r in rows)},
                 "by_member": {bg: {"all": agg(lambda r, bg=bg: r["bioguide"] == bg),
                                    **{co: agg(lambda r, bg=bg, co=co: r["bioguide"] == bg and r["co"] == co) for co in COMPANIES
                                       if any(r["bioguide"] == bg and r["co"] == co for r in rows)}} for bg in members}}


def restricted_dir(arg):
    """The folder for named rows: it must exist and must not be inside the repository, so names can never be committed."""
    d = Path(arg).resolve()
    if not d.is_dir(): raise SystemExit(f"--restricted {arg}: no such folder (is the encrypted store mounted?). Nothing written.")
    if d == ROOT or ROOT in d.parents: raise SystemExit(f"--restricted {arg} is inside the repository; named rows never go there. Nothing written.")
    return d


def member_links(cinfo_raw, byfec):
    """{committee_id: FEC committee record} -> {committee_id: bioguide} where the FEC ties it to exactly one member of Congress."""
    out = {}
    for cid, rec in cinfo_raw.items():
        cands = set(rec.get("candidate_ids") or []) | set(rec.get("sponsor_candidate_ids") or [])
        if rec.get("committee_type") not in ("H", "S") and rec.get("designation") != "D" and not rec.get("leadership_pac"): continue
        who = {byfec[c] for c in cands if c in byfec}
        if len(who) == 1: out[cid] = who.pop()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--restricted", help="folder outside the repository for the named rows")
    a = ap.parse_args(argv)
    named_dir = restricted_dir(a.restricted) if a.restricted else None
    key = os.environ.get("FEC_API_KEY", "").strip()
    if not key: print("FEC_API_KEY is not set: the donor totals were left as they were."); return
    def call(path, **q):
        url = f"{API}{path}?" + urllib.parse.urlencode(dict(q, api_key=key), doseq=True)
        for i in range(6):
            try:
                with urllib.request.urlopen(url, timeout=90) as r: time.sleep(0.4); return json.loads(r.read().decode("utf-8"))
            except Exception as e: err = str(e)[:120]; time.sleep(30 if "429" in err else 6)
        raise SystemExit(f"FEC did not answer {path}: {err}. Nothing written.")
    cyc = cycles(dt.date.today()); raw = {}
    for co, (queries, _) in COMPANIES.items():
        for q in queries:
            for c in cyc:
                last, n = {}, 0
                while True:
                    j = call("/schedules/schedule_a/", contributor_employer=q, two_year_transaction_period=c, is_individual="true",
                             per_page=100, sort="contribution_receipt_date", **last)
                    res = j.get("results") or []
                    for r in res:
                        raw[r.get("sub_id") or r.get("transaction_id") or id(r)] = (c, r)
                    n += len(res); li = (j.get("pagination") or {}).get("last_indexes")
                    if not res or not li: break
                    last = {k: v for k, v in li.items() if v is not None}
                print(f"{co} '{q}' {c}: {n} records read", file=sys.stderr)
    by_c = {}
    for c, r in raw.values(): by_c.setdefault(c, []).append(r)
    kept = [(c, co, r) for c, rs in by_c.items() for co, r in keep(rs)]
    cinfo_raw = {}
    for cid in sorted({r.get("committee_id") for _, _, r in kept if r.get("committee_id")}):
        cinfo_raw[cid] = (call(f"/committee/{cid}/").get("results") or [{}])[0]
    cinfo = {cid: ({"H": "H", "S": "S", "P": "P", "X": "Y", "Y": "Y", "Z": "Y"}.get(x.get("committee_type") or "", "Q"),
                   {"REP": "R", "DEM": "D"}.get(x.get("party") or "", ""), " ".join((x.get("name") or "").split())) for cid, x in cinfo_raw.items()}
    legs = [l for f in ("legislators-current.json", "legislators-historical.json") for l in json.load(urllib.request.urlopen(SRC + f))]
    byfec = {f: l["id"]["bioguide"] for l in legs for f in l["id"].get("fec", [])}
    member = member_links(cinfo_raw, byfec)
    rows = sorted((row(co, c, r, cinfo, member) for c, co, r in kept), key=lambda x: (x["co"], x["date"], x["name"]))
    if len(rows) < 20: raise SystemExit(f"Implausible result ({len(rows)} contributions). Nothing written.")
    agg, summ = totals(rows)
    if named_dir:
        with open(named_dir / "fec_donors.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, delimiter="|", lineterminator="\n"); w.writeheader(); w.writerows(rows)
    with open(REF / "fec_donor_totals.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TOTAL_FIELDS, delimiter="|", lineterminator="\n"); w.writeheader(); w.writerows(agg)
    (REF / "fec_donor_totals_meta.json").write_text(json.dumps({"read": str(dt.date.today()), "cycles": cyc, **summ, "read_records": len(raw)},
                                                               indent=1), encoding="utf-8")
    for old in ("fec_donors.csv", "fec_donors_meta.json"):        # the named file of earlier versions: never kept in the repository
        if (REF / old).exists(): (REF / old).unlink()
    print(f"{summ['gifts']} contributions kept of {len(raw)} read from {summ['people']} people, ${summ['total']:,.0f}; "
          f"by company {summ['by_co']}" + ("; named rows written to the restricted folder" if named_dir else ""), file=sys.stderr)


if __name__ == "__main__": main()
