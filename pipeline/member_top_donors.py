"""Each current member's largest political-committee donors and the largest outside spending for or against them, from any
cause, in the current election cycle (FEC). Shown on every scorecard beside the detention money, so a reader sees who funds a
member without the page choosing which causes to show.

Usage:  python pipeline/member_top_donors.py      (needs FEC_API_KEY; run in GitHub Actions)
Reads data/reference/members.csv and member_committees.csv (from member_committees.py).

  gave   Schedule A, line 11C of the member's own committees' reports: contributions from other political committees (PACs,
         other members' leadership funds, party-affiliated PACs). Party committees (line 11B) and transfers from joint
         fundraisers (line 12) are not included. Grouped by the giving committee's FEC id.
  spent  Schedule E independent expenditures by candidate: money outside groups (super PACs and others) reported spending to
         support or oppose the member, grouped by the spending committee and whether it supported or opposed.

Writes data/reference/member_top_donors.csv ("|" separated): bioguide | kind (G gave, S supported, O opposed) | committee_id |
name | usd | count, the twenty largest of each kind per member (a tie at twentieth place is shown in full when that keeps the list
at thirty or fewer, otherwise as one row of kind TG/TS/TO giving the tied amount and how many committees share it), and member_top_donors_meta.json. Organizations only: individual
donors to members are not read. Without a key it stops and changes nothing. Reads in pieces across weekly runs (fec_pace.py).
"""
import csv, datetime as dt, json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "data" / "reference"
API = "https://api.open.fec.gov/v1"
SRC = "https://raw.githubusercontent.com/unitedstates/congress-legislators/gh-pages/"
TOP = 20


def cycle(today):
    return today.year + today.year % 2


def top(groups, n=TOP):
    """{(bg, kind, cid): [name, usd, count]} -> rows, the n largest per member and kind, positive totals only."""
    by = {}
    for (bg, kind, cid), (name, usd, cnt) in groups.items():
        if usd > 0: by.setdefault((bg, kind), []).append({"bioguide": bg, "kind": kind, "committee_id": cid, "name": " ".join(name.split()).replace("|", "/"), "usd": round(usd), "count": cnt})
    out = []
    for (bg, kind), L in sorted(by.items()):
        L.sort(key=lambda r: -r["usd"])
        if len(L) <= n: out += L; continue
        cut = L[n - 1]["usd"]; above = [r for r in L if r["usd"] > cut]; at = [r for r in L if r["usd"] == cut]
        # Many committees give the legal maximum, so the tenth place is often a tie. Never break a tie by name (that would favour
        # names early in the alphabet): show everyone at the cut-off amount when that keeps the list short, otherwise count them.
        if len(above) + len(at) <= n + 10: out += above + sorted(at, key=lambda r: r["committee_id"])
        else: out += above + [{"bioguide": bg, "kind": "T" + kind, "committee_id": "", "name": "", "usd": cut, "count": len(at)}]
    return out


def add(groups, bg, kind, cid, name, usd, cnt=1):
    g = groups.setdefault((bg, kind, cid), [name, 0.0, 0]); g[1] += usd or 0; g[2] += cnt
    if name and not g[0]: g[0] = name


def main():
    """Reads at a steady pace and in pieces (fec_pace.py): when this run's time is up, or the FEC asks to slow down, it saves
    where it got to and the next weekly run carries on. The files are replaced only when a full read is finished."""
    import fec_pace as fp
    key = os.environ.get("FEC_API_KEY", "").strip()
    if not key: print("FEC_API_KEY is not set: top donors were left as they were."); return
    rd, name = fp.Reader(key), "member_top_donors"
    cyc = cycle(dt.date.today())
    st = fp.load(name, cyc)
    if "ids" not in st:                                     # the committee and candidate lists are fixed when a read starts
        cur = {r["bioguide"] for r in csv.DictReader(open(REF / "members.csv", encoding="utf-8"), delimiter="|") if r["current"]}
        own = {}
        for r in csv.DictReader(open(REF / "member_committees.csv", encoding="utf-8"), delimiter="|"):
            if r["bioguide"] in cur and r["designation"] in ("P", "A"): own[r["committee_id"]] = r["bioguide"]
        legs = {l["id"]["bioguide"]: l for l in json.load(urllib.request.urlopen(SRC + "legislators-current.json", timeout=120))}
        cand = {c: bg for bg in cur for c in (legs.get(bg) or {}).get("id", {}).get("fec", [])}
        st.update(own=own, cand=cand, ids=sorted(own), cids=sorted(cand), gave_next=0, gave_last={}, spent_next=0, spent_page=1, rows_read=0, groups=[])
    own, cand, ids, cids = st["own"], st["cand"], st["ids"], st["cids"]
    groups = {(g[0], g[1], g[2]): [g[3], g[4], g[5]] for g in st["groups"]}
    try:
        while st["gave_next"] < len(ids):                   # ten committees per request (the API caps list filters); keyset paging through every 11C line
            i = st["gave_next"]; chunk = ids[i:i + 10]
            while True:
                j = rd.call("/schedules/schedule_a/", committee_id=chunk, two_year_transaction_period=cyc, line_number="F3-11C", per_page=100, sort="contribution_receipt_date", **st["gave_last"])
                res = j.get("results") or []
                for r in res:
                    if (r.get("memo_code") or "").upper() == "X": continue
                    bg = own.get(r.get("committee_id"))
                    if bg: add(groups, bg, "G", r.get("contributor_id") or r.get("contributor_name") or "", r.get("contributor_name") or "", r.get("contribution_receipt_amount"))
                st["rows_read"] += len(res); li = (j.get("pagination") or {}).get("last_indexes")
                if not res or not li: break
                st["gave_last"] = {k: v for k, v in li.items() if v is not None}       # saved with the totals so far, so a pause never counts a page twice
            st["gave_next"], st["gave_last"] = i + len(chunk), {}
            print(f"gave: {st['gave_next']} of {len(ids)} committees, {st['rows_read']} lines", file=sys.stderr)
        while st["spent_next"] < len(cids):
            i = st["spent_next"]
            while True:
                j = rd.call("/schedules/schedule_e/by_candidate/", candidate_id=cids[i:i + 10], cycle=cyc, per_page=100, page=st["spent_page"])
                for r in j.get("results") or []:
                    bg = cand.get(r.get("candidate_id")); kind = {"S": "S", "O": "O"}.get(r.get("support_oppose_indicator"))
                    if bg and kind: add(groups, bg, kind, r.get("committee_id") or "", r.get("committee_name") or "", r.get("total"), r.get("count") or 0)
                if st["spent_page"] >= (j.get("pagination") or {}).get("pages", 1): break
                st["spent_page"] += 1
            st["spent_next"], st["spent_page"] = i + 10, 1
    except fp.Pause as e:
        st["groups"] = [[*k, *v] for k, v in groups.items()]
        fp.save(name, st)
        print(f"paused ({e}) after {rd.calls} requests: committees {st['gave_next']} of {len(ids)}, candidates {min(st['spent_next'], len(cids))} of {len(cids)}; "
              f"the next run carries on (read started {st['started']}, run {st['runs']}). The page keeps the last complete read.", file=sys.stderr)
        return
    rows = top(groups)
    if len({r["bioguide"] for r in rows if r["kind"] == "G"}) < 300:
        fp.clear(name); raise SystemExit(f"Implausible: PAC donors for only {len({r['bioguide'] for r in rows if r['kind'] == 'G'})} members. Nothing written; the next run starts over.")
    with open(REF / "member_top_donors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bioguide", "kind", "committee_id", "name", "usd", "count"], delimiter="|", lineterminator="\n"); w.writeheader(); w.writerows(rows)
    (REF / "member_top_donors_meta.json").write_text(json.dumps({"read": str(dt.date.today()), "cycle": cyc, "lines_read": st["rows_read"], "read_started": st["started"],
                                                                 "runs": st.get("runs", 0) + 1}, indent=1), encoding="utf-8")
    fp.clear(name)
    print(f"{len(rows)} rows for {len({r['bioguide'] for r in rows})} members", file=sys.stderr)


if __name__ == "__main__": main()
