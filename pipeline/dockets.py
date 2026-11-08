"""Court dockets for the disputes tab, read weekly from CourtListener (Free Law Project's free copy of federal court records).

Usage:  python pipeline/dockets.py        (needs internet; runs in GitHub Actions)

data/reference/dispute_dockets.csv lists, by hand, the court and docket number of each dispute that is a federal case
(id | court | docket_number; court is CourtListener's court id, e.g. ilnd). This step adds what CourtListener knows:
  cl_id | cl_url | last_filing | entry_date | entry_text | entry_doc | checked
The page links each docket as an official record and says when the docket shows filings newer than the step on file,
so a stale status shows itself. entry_* is the newest docket entry, where CourtListener lets this account read entries.

Automatic status (decision 2026-11-06, replacing "never applied automatically"): every entry newer than the status on file
is read and sorted by classify(). A court action (an order that decides something, an opinion, a judgment, an injunction,
a dismissal, a mandate, a notice of appeal, a verdict or sentence) becomes the new status, quoted word for word from the
docket with its date and a link (auto_date | auto_text | auto_url). Anything else (lawyers joining, transcripts, scheduling,
the parties' own filings) changes nothing but counts as looked at (reviewed_auto). An entry with no readable text stops the
walk: it and everything after it stay flagged until CourtListener has the text. Nothing is written in our own words.

CourtListener allows 5 requests a minute and 50 an hour per account. A docket id, once found, is kept, so a normal week
needs one or two requests per case; the run stops at the budget and carries on next week. A token in COURTLISTENER_TOKEN
(the project's own CourtListener account) is used when set; without it the step tries anonymously.
"""
import csv, datetime as dt, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "data" / "reference"
API = "https://www.courtlistener.com/api/rest/v4/"
SITE = "https://www.courtlistener.com"
COLS = ["id", "court", "docket_number", "cl_id", "cl_url", "last_filing", "entry_date", "entry_text", "entry_doc", "checked",
        "auto_date", "auto_text", "auto_url", "reviewed_auto"]
MAX_PAGES = 3          # docket-entry pages read per case per run (newest first); the rest waits for next week

# What the court did, by how the docket entry begins. A notice of appeal and a dismissal by the parties end or move a case,
# so they count too. Everything else is a filing that does not change where the case stands.
COURT_ACTION = re.compile(r"^(?:\((?:text[- ]only|court only)\)\s*)?(?:"
    r"(?:final |clerk'?s |amended |default )?judgment|opinion|memorandum (?:opinion|and order|decision)|mandate|"
    r"(?:preliminary |permanent )?injunction|temporary restraining order|verdict|"
    r"notice of appeal(?! due)|(?:joint )?stipulation (?:of|for) (?:voluntary )?dismissal|notice of voluntary dismissal|"
    r"(?:minute |memorandum |text |electronic )?order\b.*\b(?:dismiss\w*|injunction|restraining|judgment|stay(?:ed|ing)?\b|remand\w*|vacat\w*|moot|clos(?:e|ed|ing) (?:the )?case|terminat\w*|declaratory)"
    r")", re.I | re.S)
NOT_AN_ACTION = re.compile(r"\b(?:due letter|transmission of|transcript|notice to usca|appearance|withdraw\w*|pro hac vice|extension of time|schedul\w*|deadlines?|briefing|page limits?|hearing (?:is )?(?:set|reset|continued|vacated))\b", re.I)


def classify(text):
    """'court' (a court action or an end-of-case filing), 'other' (anything that does not change the status) or
    'unreadable' (no text). Conservative: an entry is a court action only when it begins as one."""
    t = " ".join((text or "").split())
    if not t: return "unreadable"
    if COURT_ACTION.match(t) and not NOT_AN_ACTION.search(t[:120]): return "court"
    return "other"


def entry_row(e, docket_url=""):
    """[date, text, document or entry link] for one CourtListener docket entry. The entry's own text, else its first
    document's description; the document's file when CourtListener holds it, else the entry on the docket page."""
    docs = e.get("recap_documents") or []
    text = " ".join((e.get("description") or next((d.get("description") or "" for d in docs if d.get("description")), "") or "").split())[:300]
    doc = next((d.get("filepath_local") for d in docs if d.get("filepath_local")), "")
    if doc and not doc.startswith("http"): doc = "https://storage.courtlistener.com/" + doc.lstrip("/")
    link = doc or (f"{docket_url}#entry-{e['entry_number']}" if docket_url and e.get("entry_number") else "")
    return [(e.get("date_filed") or "")[:10], text, link]


def entries_since(cl_id, since, get_json, docket_url=""):
    """Every docket entry filed after `since`, oldest first, or None when the entries cannot be read (or more pages than
    MAX_PAGES would be needed: then nothing is decided this week)."""
    url, out = API + "docket-entries/?" + urllib.parse.urlencode({"docket": cl_id, "order_by": "-date_filed"}), []
    for _ in range(MAX_PAGES):
        j = get_json(url)
        if not j: return None
        for e in j.get("results") or []:
            r = entry_row(e, docket_url)
            if r[0] and r[0] <= since: return list(reversed(out))
            out.append(r)
        url = j.get("next")
        if not url: return list(reversed(out))
    return None


def decide(entries, since):
    """Entries after the status on file (oldest first) -> (newest court action or None, date looked at through).
    The walk stops at the first entry without text, so nothing after it counts as looked at."""
    action, through = None, ""
    for r in entries:
        k = classify(r[1])
        if k == "unreadable" or not r[0] or (k == "court" and not r[2].startswith("https://")): break     # no text, or a court action with nothing to link to
        if k == "court": action = r
        through = r[0]
    return action, through

BUDGET, PAUSE = 45, 13          # requests per run, seconds between them (under 5 a minute and 50 an hour)


def find_docket(court, number, get_json):
    """CourtListener's docket for a court and docket number, or None. Tries the docket list, then search (whose docket
    numbers are sometimes written without the office prefix, e.g. 25-cv-01285)."""
    j = get_json(API + "dockets/?" + urllib.parse.urlencode({"court": court, "docket_number": number}))
    for d in (j or {}).get("results") or []:
        return d
    core = number.split(":", 1)[-1]
    j = get_json(API + "search/?" + urllib.parse.urlencode({"type": "r", "court": court, "q": f'docketNumber:"{core}"'}))
    for r in (j or {}).get("results") or []:
        if core in (r.get("docketNumber") or ""):
            return {"id": r.get("docket_id"), "absolute_url": r.get("docket_absolute_url"), "date_last_filing": r.get("dateLastFiling") or r.get("date_last_filing")}
    return None


def newest_entry(cl_id, get_json):
    """The newest docket entry: date, text and, when CourtListener holds it, the document's own file. None when this
    account cannot read entries (that endpoint is limited to some accounts)."""
    j = get_json(API + "docket-entries/?" + urllib.parse.urlencode({"docket": cl_id, "order_by": "-date_filed"}))
    for e in (j or {}).get("results") or []:
        doc = next((d.get("filepath_local") for d in e.get("recap_documents") or [] if d.get("filepath_local")), "")
        if doc and not doc.startswith("http"): doc = "https://storage.courtlistener.com/" + doc.lstrip("/")
        return [e.get("date_filed") or "", " ".join((e.get("description") or "").split())[:300], doc or ""]
    return None


def run(rows, prev, get_json, today, budget=BUDGET, status=None):
    """One row per hand-listed case; what was found before is kept when a request fails or the budget runs out.
    status = {id: the date of the status on file}: entries after it are read and decided (decide())."""
    status = status or {}
    out, left = [], [budget]
    def g(url):
        if left[0] <= 0: return None
        left[0] -= 1; return get_json(url)
    for r in rows:
        p = {k: prev.get(r["id"], {}).get(k, "") for k in COLS}
        o = {**p, "id": r["id"], "court": r["court"], "docket_number": r["docket_number"]}
        if p["court"] != r["court"] or p["docket_number"] != r["docket_number"]:      # the hand entry changed: look it up again
            o.update(cl_id="", cl_url="", last_filing="", entry_date="", entry_text="", entry_doc="")
        if not o["cl_id"]:
            d = find_docket(r["court"], r["docket_number"], g)
            if d and d.get("id"):
                o.update(cl_id=str(d["id"]), cl_url=SITE + (d.get("absolute_url") or f"/docket/{d['id']}/"), last_filing=(d.get("date_last_filing") or "")[:10], checked=str(today))
        elif left[0] > 0:
            d = g(API + f"dockets/{o['cl_id']}/")
            if d and d.get("id"): o.update(last_filing=(d.get("date_last_filing") or o["last_filing"])[:10], checked=str(today))
        if o["cl_id"] and left[0] > 0:
            e = newest_entry(o["cl_id"], g)
            if e: o.update(entry_date=e[0], entry_text=e[1], entry_doc=e[2])
        since = max(status.get(r["id"], ""), o["auto_date"], o["reviewed_auto"], r.get("reviewed_through") or "")
        if o["cl_id"] and o["last_filing"] and since and o["last_filing"] > since and left[0] > 0:
            es = entries_since(o["cl_id"], since, g, o["cl_url"])
            if es is not None:
                action, through = decide(es, since)
                if action: o.update(auto_date=action[0], auto_text=action[1], auto_url=action[2])
                if through: o["reviewed_auto"] = max(o["reviewed_auto"], through)
        out.append(o)
    return out, budget - left[0]


def fetcher(token):
    def get_json(url):
        h = {"Accept": "application/json", "User-Agent": "polar-star-data-refresh (public-interest, non-commercial)"}
        if token: h["Authorization"] = f"Token {token}"
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r: return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"  {e.code} {url}", file=sys.stderr); return None
        except Exception as e:
            print(f"  failed {url}: {e}", file=sys.stderr); return None
    return get_json


def main():
    src = REF / "dispute_dockets.csv"
    rows = [r for r in csv.DictReader(open(src, encoding="utf-8"), delimiter="|")]
    pp = REF / "dispute_dockets_checked.csv"
    prev = {r["id"]: r for r in csv.DictReader(open(pp, encoding="utf-8"), delimiter="|")} if pp.exists() else {}
    st = {r["id"]: (r.get("status_date") or r.get("date") or "") for r in csv.DictReader(open(REF / "ice_local_disputes.csv", encoding="utf-8"), delimiter="|")}
    out, used = run(rows, prev, fetcher(os.environ.get("COURTLISTENER_TOKEN", "").strip()), dt.date.today(), status=st)
    with open(pp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, delimiter="|", lineterminator="\n"); w.writeheader(); w.writerows(out)   # standard quoting: every reader of this file uses the default csv reader
    found = sum(1 for o in out if o["cl_id"])
    print(f"{found} of {len(out)} dockets found on CourtListener; {sum(1 for o in out if o['entry_date'])} with a newest entry; "
          f"{sum(1 for o in out if o['auto_date'])} with a status from the docket; {used} requests")
    if used and not found: raise SystemExit("no docket could be read: check COURTLISTENER_TOKEN or CourtListener's status")


def review():
    """python pipeline/dockets.py --review : the cases whose docket has moved past the status on file, with the newest entry
    and its document, so the status (and a copied or news-report source) can be updated by hand from the court record."""
    st = {r["id"]: r for r in csv.DictReader(open(REF / "ice_local_disputes.csv", encoding="utf-8"), delimiter="|")}
    pp = REF / "dispute_dockets_checked.csv"
    for o in (csv.DictReader(open(pp, encoding="utf-8"), delimiter="|") if pp.exists() else []):
        r = st.get(o["id"]); since = (r or {}).get("status_date") or (r or {}).get("date", "")
        if o["last_filing"] and o["last_filing"] > since:
            print(f"{o['id']}: status {since or '-'}, docket {o['last_filing']}  {o['cl_url']}")
            if o["entry_date"]: print(f"    newest entry {o['entry_date']}: {o['entry_text']}  {o['entry_doc']}")


if __name__ == "__main__": review() if "--review" in sys.argv else main()
