"""Donors are private individuals: no named donor file, column or name may reach the repository or the published page.
Runs everywhere. The last check also runs on the publisher's machine, against the named rows kept outside the repository
(POLAR_STAR_RESTRICTED, a folder; skipped when it is not set or not mounted)."""
import csv, json, os, pathlib, re
import money_donors

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMED_COLUMNS = {"name", "employer", "occupation", "contributor_name", "contributor_employer", "contributor_occupation"}


def test_no_named_donor_file_in_the_repository():
    hits = [str(p.relative_to(ROOT)) for d in ("data", "site") for p in (ROOT / d).rglob("fec_donors*")]
    assert not hits, f"named donor files must stay outside the repository: {hits}"


def test_donor_totals_carry_no_personal_column():
    f = ROOT / "data" / "reference" / "fec_donor_totals.csv"
    if not f.exists(): return
    cols = next(csv.reader(open(f, encoding="utf-8"), delimiter="|"))
    assert cols == money_donors.TOTAL_FIELDS and not NAMED_COLUMNS & set(cols), cols
    meta = json.loads((f.parent / "fec_donor_totals_meta.json").read_text(encoding="utf-8"))
    assert set(meta) <= {"read", "cycles", "total", "gifts", "people", "small", "by_year", "by_co", "by_member", "read_records"}, set(meta)


def test_built_page_has_no_donor_list():
    more = ROOT / "site" / "more-data.js"
    if not more.exists(): return
    d = json.loads(re.match(r"window\.DATA_MORE=(.*);\s*$", more.read_text(encoding="utf-8"), re.S).group(1))["d"].get("donors")
    if d: assert all(len(r) == 9 and isinstance(r[5], float) and isinstance(r[7], int) for r in d["rows"]), "donor rows must be totals"
    persons = ROOT / "site" / "persons-data.js"
    if persons.exists(): assert '"dn":' not in persons.read_text(encoding="utf-8") and '["$",' not in persons.read_text(encoding="utf-8")


def test_no_restricted_name_appears_on_the_page():
    folder = os.environ.get("POLAR_STAR_RESTRICTED", "")
    f = pathlib.Path(folder) / "fec_donors.csv" if folder else None
    if not f or not f.exists(): return
    names = set()
    for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="|"):
        last, _, rest = r["name"].upper().partition(",")
        first = next((w for w in re.sub(r"[^A-Z ]+", " ", rest).split() if w not in money_donors.TITLES and len(w) > 1), "")
        last = re.sub(r"[^A-Z ]+", " ", last).strip()
        if first and len(last) > 2: names.add((first, last))
    # people on the page in a public role (members, governors, sheriffs, registered lobbyists...) have a person card; a
    # donor who is also one of them may appear there, for that role only
    pf = ROOT / "site" / "persons-data.js"
    public = set()
    if pf.exists():
        P = json.loads(re.match(r"window\.PERSONS=(.*);\s*$", pf.read_text(encoding="utf-8"), re.S).group(1))["d"]["p"]
        for e in P.values():
            for nm in e["n"]:
                w = re.sub(r"[^A-Z ]+", " ", nm.upper()).split()
                if len(w) >= 2: public.add((w[0], w[-1]))
    pages = " ".join(p.read_text(encoding="utf-8").upper() for p in (ROOT / "site").glob("*.*") if p.suffix in (".html", ".js"))
    # a different person who shares a donor's name (say, a former member in a lobbyist's past post), reviewed by hand; kept
    # beside the named rows, never in the repository, since the list itself would reveal who donated
    rv = f.parent / "reviewed_same_name.txt"
    reviewed = {tuple(l.split("#")[0].strip().upper().split()[:2]) for l in rv.read_text(encoding="utf-8").splitlines() if l.split("#")[0].strip()} if rv.exists() else set()
    hits = sorted(f"{a} {b}" for a, b in names - public - reviewed
                  if re.search(rf"\b{a}\s+(?:[A-Z]\.?\s+)?{b}\b|\b{b},\s*{a}\b", pages))
    assert not hits, f"{len(hits)} donor names appear on the page, e.g. {hits[:5]}"
