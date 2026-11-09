"""PACs focused on US policy toward one specific country, and what they gave to or spent on current members of Congress.

Usage:  python pipeline/country_pacs.py        (needs FEC_API_KEY; runs in GitHub Actions)

The FEC does not classify PACs by cause, so one written rule is applied to every country alike:

  A. Name. A political action committee or super PAC whose registered name names a foreign country, or its people in
     the way a foreign-policy group does ("Armenian National Committee", "Turkish Coalition"), is listed. Names built
     on "<people> American" ("Indian American", "Irish American") describe a US community, not a country's policy,
     and are left out unless the country itself is also named. Leadership PACs, joint fundraisers and a company's own
     PAC (FEC organization type "corporation", e.g. "Chipotle Mexican Grill PAC") are left out, as are committees in
     data/reference/country_pacs_excluded.csv (each with the reason it was reviewed out). Leadership PACs and joint fundraisers are left out
     because their names are usually a politician's name, and some surnames are also country names. Country names that are
     also US state or common place or personal names (Georgia, Jordan, Chad, Niger, Turkey as a word alone) are not
     used as search terms.
  B. Affiliates. A committee whose own FEC registration names a committee listed under A as its affiliated committee.
     Candidates are kept in data/reference/country_pacs_affiliates.csv, and each is listed only when the FEC's record
     for it says so; a news or fact-check source alone is not enough, for any country.
A PAC whose name does not name a country is not found by rule A, whatever country it focuses on.

For each listed committee, in the current two-year cycle, from its own reports:
  gave       (G) Schedule B contributions from its own funds to current members' campaign committees.
  forwarded  (E) Schedule B payments it passed on as a conduit: an individual donor gave to the committee and named the
             member, so the money is that donor's contribution, which the committee transmitted. Shown separately, never
             added to G.
  spent      (S/O) Schedule E independent expenditures it reported to support or oppose a current member.

Writes data/reference/country_pacs.csv, country_pacs_money.csv and country_pacs_meta.json. Reads in pieces across weekly runs
(fec_pace.py); the files are replaced only when a full read is finished.
"""
import csv, datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "data" / "reference"
API = "https://api.open.fec.gov/v1"
SRC = "https://raw.githubusercontent.com/unitedstates/congress-legislators/gh-pages/"
PAC_TYPES = ["N", "Q", "O", "V", "W"]           # PACs (non-qualified, qualified), super PACs, hybrid PACs
# country: words that name it or its people. Ambiguous names (US states, common surnames or places) are left out.
COUNTRIES = {
 "Afghanistan": ["AFGHANISTAN", "AFGHAN"], "Albania": ["ALBANIA", "ALBANIAN"], "Algeria": ["ALGERIA", "ALGERIAN"], "Argentina": ["ARGENTINA", "ARGENTINE"],
 "Armenia": ["ARMENIA", "ARMENIAN"], "Azerbaijan": ["AZERBAIJAN", "AZERBAIJANI"], "Bangladesh": ["BANGLADESH", "BANGLADESHI"], "Belarus": ["BELARUS", "BELARUSIAN"],
 "Bosnia and Herzegovina": ["BOSNIA", "BOSNIAN"], "Brazil": ["BRAZIL", "BRAZILIAN"], "Bulgaria": ["BULGARIA", "BULGARIAN"], "Cambodia": ["CAMBODIA", "CAMBODIAN"],
 "Canada": ["CANADA"], "China": ["CHINA", "CHINESE"], "Colombia": ["COLOMBIA", "COLOMBIAN"], "Croatia": ["CROATIA", "CROATIAN"], "Cuba": ["CUBA", "CUBAN"],
 "Cyprus": ["CYPRUS", "CYPRIOT"], "Dominican Republic": ["DOMINICAN REPUBLIC"], "Ecuador": ["ECUADOR", "ECUADORIAN"], "Egypt": ["EGYPT", "EGYPTIAN"],
 "El Salvador": ["EL SALVADOR", "SALVADORAN"], "Eritrea": ["ERITREA", "ERITREAN"], "Estonia": ["ESTONIA", "ESTONIAN"], "Ethiopia": ["ETHIOPIA", "ETHIOPIAN"],
 "Greece": ["GREECE", "HELLENIC"], "Guatemala": ["GUATEMALA", "GUATEMALAN"], "Haiti": ["HAITI", "HAITIAN"], "Honduras": ["HONDURAS", "HONDURAN"],
 "Hungary": ["HUNGARY", "HUNGARIAN"], "India": ["INDIA"], "Indonesia": ["INDONESIA", "INDONESIAN"], "Iran": ["IRAN", "IRANIAN"], "Iraq": ["IRAQ", "IRAQI"],
 "Ireland": ["IRELAND", "IRISH"], "Israel": ["ISRAEL", "ISRAELI"], "Japan": ["JAPAN", "JAPANESE"], "Kenya": ["KENYA", "KENYAN"], "Korea": ["KOREA", "KOREAN"], "Kosovo": ["KOSOVO"],
 "Kurdistan": ["KURDISTAN", "KURDISH"], "Latvia": ["LATVIA", "LATVIAN"], "Lithuania": ["LITHUANIA", "LITHUANIAN"], "Mexico": ["MEXICAN"], "Morocco": ["MOROCCO", "MOROCCAN"],
 "Nepal": ["NEPAL", "NEPALI"], "Nicaragua": ["NICARAGUA", "NICARAGUAN"], "Nigeria": ["NIGERIA", "NIGERIAN"], "Pakistan": ["PAKISTAN", "PAKISTANI"],
 "Palestine": ["PALESTINE", "PALESTINIAN"], "Philippines": ["PHILIPPINES", "PHILIPPINE", "FILIPINO"], "Poland": ["POLAND", "POLISH"], "Portugal": ["PORTUGAL"],
 "Romania": ["ROMANIA", "ROMANIAN"], "Russia": ["RUSSIA", "RUSSIAN"], "Saudi Arabia": ["SAUDI"], "Serbia": ["SERBIA", "SERBIAN"], "Somalia": ["SOMALIA", "SOMALI"],
 "Sri Lanka": ["SRI LANKA", "SRI LANKAN"], "Sudan": ["SUDAN", "SUDANESE"], "Syria": ["SYRIA", "SYRIAN"], "Taiwan": ["TAIWAN", "TAIWANESE", "FORMOSAN"],
 "Turkey": ["TURKISH", "TURKIYE"], "Ukraine": ["UKRAINE", "UKRAINIAN"], "United Kingdom": ["BRITISH"], "Venezuela": ["VENEZUELA", "VENEZUELAN"],
 "Vietnam": ["VIETNAM", "VIETNAMESE"], "Yemen": ["YEMEN", "YEMENI"],
}


def fec_affiliated(d, parent):
    """True when the FEC's committee record names the parent as its affiliated committee or connected organization."""
    key = re.sub(r"\W", "", parent.upper())
    return any(key and key in re.sub(r"\W", "", str(d.get(f) or "").upper()) for f in ("affiliated_committee_name", "connected_organization_name"))


def matches(name, words):
    """The country words found in a committee name, under rule A. '<people> American' alone is a community name."""
    n = " " + re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9'& ]+", " ", name.upper())) + " "
    hits = [w for w in words if re.search(r"(?<![A-Z])" + re.escape(w) + r"(?![A-Z])", n)]
    if not hits: return []
    community = all(re.search(r"(?<![A-Z])" + re.escape(w) + r" ?AMERICANS?(?![A-Z])", n) for w in hits)
    # "of the United States and Canada": a union or trade group whose members are in both countries, not a foreign-policy group
    binational = all(re.search(r"(?:UNITED STATES|U S|USA|AMERICA) (?:AND|&) " + re.escape(w) + r"(?![A-Z])", n) for w in hits)
    return [] if community or binational else hits



def earmarked(r):
    """True for a payment the committee forwarded on behalf of an individual donor (an earmarked contribution, where the
    committee is only the conduit), rather than a contribution from the committee's own funds."""
    t = " ".join(str(r.get(k) or "") for k in ("disbursement_description", "memo_text", "disbursement_type_description")).upper()
    return "EARMARK" in t or "CONDUIT" in t or (r.get("disbursement_type") or "") in ("24T", "24Z")

def main():
    """Reads at a steady pace and in pieces (fec_pace.py): when this run's time is up, or the FEC asks to slow down, it saves
    where it got to and the next weekly run carries on. The files are replaced only when a full read is finished."""
    import fec_pace as fp
    key = os.environ.get("FEC_API_KEY", "").strip()
    if fp.rested("country_pacs", REF / "country_pacs_meta.json"): print("Read completed less than a month ago: resting this week (fec_pace.REST_DAYS).", file=sys.stderr); return
    if not key: print("FEC_API_KEY is not set: country PACs left as they were."); return
    rd, name = fp.Reader(key), "country_pacs"
    today = dt.date.today(); cyc = today.year + today.year % 2
    st = fp.load(name, cyc)
    if "words" not in st:
        cur = {r["bioguide"] for r in csv.DictReader(open(REF / "members.csv", encoding="utf-8"), delimiter="|") if r["current"]}
        legs = json.load(urllib.request.urlopen(SRC + "legislators-current.json", timeout=120))
        st.update(words=[[c, w] for c, ws in COUNTRIES.items() for w in ws], w_next=0, w_page=1, found={}, a_next=0,
                  own={r["committee_id"]: r["bioguide"] for r in csv.DictReader(open(REF / "member_committees.csv", encoding="utf-8"), delimiter="|") if r["bioguide"] in cur and r["designation"] in ("P", "A")},
                  cand={c: l["id"]["bioguide"] for l in legs for c in l["id"].get("fec", []) if l["id"]["bioguide"] in cur},
                  m_next=0, m_k=0, m_last={}, m_part="b", money=[])
    found, own, cand = st["found"], st["own"], st["cand"]
    money = {(m[0], m[1], m[2]): [m[3], m[4]] for m in st["money"]}
    affiliates = list(csv.DictReader(open(REF / "country_pacs_affiliates.csv", encoding="utf-8"), delimiter="|"))
    xf = REF / "country_pacs_excluded.csv"           # reviewed: committees the name rule catches that are not about a country (a company's name)
    excluded = {r["committee_id"] for r in csv.DictReader(open(xf, encoding="utf-8"), delimiter="|")} if xf.exists() else set()
    try:
        # rule A: search committee names for every country word
        while st["w_next"] < len(st["words"]):
            country, w = st["words"][st["w_next"]]; words = COUNTRIES.get(country, [w])
            while True:
                j = rd.call("/committees/", q=w, committee_type=PAC_TYPES, per_page=100, page=st["w_page"], cycle=[cyc, cyc - 2])
                for c in j.get("results") or []:
                    if c.get("designation") in ("D", "J") or c.get("organization_type") == "C" or c["committee_id"] in excluded: continue   # leadership PACs, joint funds, companies' own PACs
                    if matches(c.get("name") or "", words): found.setdefault(c["committee_id"], {"committee_id": c["committee_id"], "name": c["name"], "country": country, "basis": "name", "source": ""})
                if st["w_page"] >= (j.get("pagination") or {}).get("pages", 1): break
                st["w_page"] += 1
            st["w_next"], st["w_page"] = st["w_next"] + 1, 1
        # rule B: affiliates named in a public record
        while st["a_next"] < len(affiliates):
            r = affiliates[st["a_next"]]
            j = rd.call("/committees/", q=r["name"], per_page=20)
            want = re.sub(r"\W", "", r["name"].upper())
            hit = [c for c in j.get("results") or [] if re.sub(r"\W", "", (c.get("name") or "").upper()).startswith(want) and c.get("committee_type") in PAC_TYPES]
            if not hit: print(f"affiliate not found at the FEC: {r['name']}", file=sys.stderr)
            else:
                cid = hit[0]["committee_id"]; d = (rd.call(f"/committee/{cid}/").get("results") or [{}])[0]
                if fec_affiliated(d, r["affiliate_of"]):
                    found.setdefault(cid, {"committee_id": cid, "name": hit[0]["name"], "country": r["country"], "basis": "affiliate of " + r["affiliate_of"], "source": f"https://www.fec.gov/data/committee/{cid}/"})
                else: print(f"not listed: the FEC's record for {r['name']} does not name {r['affiliate_of']} as an affiliated committee", file=sys.stderr)
            st["a_next"] += 1
        if st["a_next"] == len(affiliates) and st["m_next"] == 0 and "listed" not in st:
            st["listed"] = sorted(found); print(f"{len(found)} committees match the rule", file=sys.stderr)
        # money to current members, one committee at a time
        listed, targets = st["listed"], sorted(own)
        while st["m_next"] < len(listed):
            cid = listed[st["m_next"]]
            if st["m_part"] == "b":
                # The committee's own report of what it paid out, asked for 100 members' committees at a time: a large committee's
                # full list (tens of thousands of forwarded donations) makes the FEC time out, while these narrower asks answer.
                while st["m_k"] < len(targets):
                    while True:
                        j = rd.call("/schedules/schedule_b/", committee_id=cid, recipient_committee_id=targets[st["m_k"]:st["m_k"] + 100], two_year_transaction_period=cyc, per_page=100, sort="disbursement_date", **st["m_last"])
                        res = j.get("results") or []
                        for r in res:
                            if (r.get("memo_code") or "").upper() == "X": continue
                            bg = own.get(r.get("recipient_committee_id"))
                            if not bg: continue
                            kind = "E" if earmarked(r) else "G"
                            m = money.setdefault((cid, bg, kind), [0.0, 0]); m[0] += r.get("disbursement_amount") or 0; m[1] += 1
                        li = (j.get("pagination") or {}).get("last_indexes")
                        if not res or not li: break
                        st["m_last"] = {k2: v for k2, v in li.items() if v is not None}
                    st["m_k"], st["m_last"] = st["m_k"] + 100, {}
                st["m_part"] = "e"
            while True:                                       # regular reports only (not the 24- and 48-hour notices, which repeat them)
                j = rd.call("/schedules/schedule_e/", committee_id=cid, cycle=cyc, is_notice="false", per_page=100, sort="expenditure_date", **st["m_last"])
                res = j.get("results") or []
                for r in res:
                    if (r.get("memo_code") or "").upper() == "X": continue
                    bg, kind = cand.get(r.get("candidate_id")), {"S": "S", "O": "O"}.get(r.get("support_oppose_indicator"))
                    if bg and kind:
                        m = money.setdefault((cid, bg, kind), [0.0, 0]); m[0] += r.get("expenditure_amount") or 0; m[1] += 1
                li = (j.get("pagination") or {}).get("last_indexes")
                if not res or not li: break
                st["m_last"] = {k: v for k, v in li.items() if v is not None}
            st["m_next"], st["m_k"], st["m_last"], st["m_part"] = st["m_next"] + 1, 0, {}, "b"
    except fp.Pause as e:
        st["money"] = [[*k, *v] for k, v in money.items()]
        fp.save(name, st)
        print(f"paused ({e}) after {rd.calls} requests: words {st['w_next']} of {len(st['words'])}, committees {st['m_next']} of {len(st.get('listed', []))}; "
              f"the next run carries on (read started {st['started']}, run {st['runs']}). The page keeps the last complete read.", file=sys.stderr)
        return
    gave = {cid for (cid, _, _), v in money.items() if v[0] > 0}                # G, E, S or O
    rows = [found[c] for c in sorted(found, key=lambda c: (found[c]["country"], found[c]["name"])) if c in gave]
    with open(REF / "country_pacs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["committee_id", "name", "country", "basis", "source"], delimiter="|", lineterminator="\n"); w.writeheader(); w.writerows(rows)
    with open(REF / "country_pacs_money.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="|", lineterminator="\n"); w.writerow(["committee_id", "bioguide", "kind", "usd", "count"])
        for (cid, bg, kind), (usd, n) in sorted(money.items()):
            if usd > 0: w.writerow([cid, bg, kind, round(usd), n])
    (REF / "country_pacs_meta.json").write_text(json.dumps({"read": str(today), "cycle": cyc, "matched": len(found), "with_money": len(rows), "read_started": st["started"]}, indent=1), encoding="utf-8")
    fp.clear(name)
    print(f"{len(rows)} of {len(found)} committees gave to or spent on current members", file=sys.stderr)


if __name__ == "__main__": main()
