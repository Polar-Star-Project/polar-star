"""The whole refresh, in order. Used by the weekly job on GitHub and by run_refresh.ps1 on a PC.

Usage:  python pipeline/refresh_all.py                 (everything)
        python pipeline/refresh_all.py --only tests,build
        python pipeline/refresh_all.py --skip flights

A step marked required stops the run if it fails, and the published page is left as it was. Every other step
may fail (a site is down, a server is blocked): its data stays as it was, the failure is written to
data/refresh_status.json, and the page footer flags that source once it is older than it should be.
The page is rebuilt only after every test passes, and the previous page is put back if the build fails.
"""
import datetime as dt, json, os, shutil, signal, subprocess, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = "data/raw/"
STEPS = [  # name, command after "python", required
    # short checks that depend on no other step run first, so a long run that is cut off still keeps the court
    # statuses, help lines and organizations current
    ("disputes",   ["pipeline/disputes_check.py"], False),
    ("dockets",    ["pipeline/dockets.py"], False),
    ("hotlines",   ["pipeline/hotlines_check.py"], False),
    ("familyorgs", ["pipeline/family_orgs_check.py"], False),
    ("records",    ["pipeline/fetch.py"], True),
    ("custody",    ["pipeline/custody_trend.py"], False),
    ("removed_to", ["pipeline/removals_country.py"], False),
    ("arrests",    ["pipeline/arrests_trend.py"], False),
    ("detainers",  ["pipeline/detainers_trend.py"], False),
    ("days",       ["pipeline/person_days.py"], False),
    ("held",       ["pipeline/held_profile.py"], False),
    ("ice_site",   ["pipeline/refresh_contacts.py"], False),
    ("audits",     ["pipeline/prea_audits.py"], False),
    ("stats",      ["pipeline/detention_stats.py"], False),
    ("findings",   ["pipeline/inspection_findings.py"], False),
    ("spending",   ["pipeline/money_usaspending.py"], False),
    ("awards",     ["pipeline/money_awards.py"], False),
    ("others",     ["pipeline/other_agencies.py"], False),
    ("accounts",   ["pipeline/money_object_class.py"], False),
    ("staff",      ["pipeline/staff_opm.py"], False),
    ("court",      ["pipeline/court_outcomes.py"], False),
    ("memos",      ["pipeline/crcl_memos.py"], False),
    ("lobbying",   ["pipeline/money_lobbying.py"], False),
    ("vendorlobby", ["pipeline/vendor_lobbying.py"], False),
    ("fec",        ["pipeline/money_fec.py"], False),
    ("jfc",        ["pipeline/jfc_flows.py"], False),
    ("politicians", ["pipeline/politicians.py"], False),
    ("donors",     ["pipeline/money_donors.py"], False),
    ("membercom",  ["pipeline/member_committees.py"], False),
    ("fara",       ["pipeline/fara.py"], False),
    ("firms",      ["pipeline/firm_profiles.py"], False),
    ("firmbase",   ["pipeline/firm_base.py"], False),
    ("sec",        ["pipeline/sec_watch.py"], False),
    # the two slowest FEC readers last in the money group, so a cut-off loses only them
    ("topdonors",  ["pipeline/member_top_donors.py"], False),
    ("countrypacs", ["pipeline/country_pacs.py"], False),
    ("social",     ["pipeline/social_check.py"], False),
    ("officials",  ["pipeline/officials_check.py"], False),
    ("legalaid",   ["pipeline/eoir_probono.py"], False),
    ("moa",        ["pipeline/moa_links.py"], False),
    ("signers",    ["pipeline/moa_signers.py"], False),
    ("transfers",  ["pipeline/build_transfers.py", RAW + "detention-stints-latest.parquet", RAW + "facilities-latest.parquet",
                    "data/reference/ice_facility_contacts.csv", "data/reference/ice_field_offices.csv"], True),
    ("police",     ["pipeline/agency_contacts.py"], False),
    ("statements", ["pipeline/visit_statements.py"], False),
    ("districts",  ["pipeline/districts.py"], False),
    ("flights",    ["pipeline/flights.py", "--catchup", "8"], False),
    ("probe",      ["pipeline/probe_sources.py"], False),
    ("tests",      ["pipeline/run_tests.py"], True),
    ("build",      ["pipeline/build_site.py"], True),
]

# Longest a step may run before it is stopped (minutes), so one slow or stuck source cannot use up the whole run and keep the
# page from being rebuilt. A stopped step counts as failed: its data is left as it was and it is tried again next week.
LIMIT = 40
LIMITS = {"records": 60, "transfers": 60, "fec": 90, "jfc": 60, "donors": 60, "membercom": 60, "topdonors": 60, "countrypacs": 60,
          "firmbase": 60, "flights": 60, "tests": 30, "build": 20, "dockets": 20}

# The weekly workflow runs two groups side by side, each in its own job with its own time limit: "money" (the FEC and
# lobbying collectors, slow because those APIs limit requests per minute and hour) and "main" (everything else). The
# tests and the build run afterwards, in a third job, on what both saved.
MONEY = {"politicians", "membercom", "lobbying", "vendorlobby", "fec", "jfc", "donors", "fara", "firms", "firmbase", "sec", "topdonors", "countrypacs"}
GROUP_OF = lambda name: "build" if name in ("tests", "build") else "money" if name in MONEY else "main"

ON_REQUEST = {"probe"}   # steps that run only when named in --only
MONTHLY = set()          # steps that run only in the first week of a month (none now: the audit check is weekly again)


def pick(names, only, skip):
    """Which steps run, in the fixed order. Unknown names are an error, so a typo cannot silently skip the tests."""
    known = [n for n, _, _ in STEPS]
    bad = [x for x in (only or []) + (skip or []) if x not in known]
    if bad: raise SystemExit(f"unknown step(s): {', '.join(bad)}. Steps are: {', '.join(known)}")
    return [n for n in names if (not only or n in only) and n not in (skip or [])]


def main(argv):
    arg = lambda flag: argv[argv.index(flag) + 1].split(",") if flag in argv else None
    todo = pick([n for n, _, _ in STEPS], arg("--only"), arg("--skip"))
    if arg("--group"): todo = [n for n in todo if GROUP_OF(n) in arg("--group")]
    sp = ROOT / os.environ.get("REFRESH_STATUS", "data/refresh_status.json")     # a group writes its own file; the build job joins them
    page, keep = ROOT / "site" / "index.html", ROOT / "site" / "index.previous.html"
    status, ok = {"started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "steps": {}, "minutes": {}}, True
    partial = arg("--only") or arg("--group")
    if partial and sp.exists():           # a partial run (say, the rebuild after a cut-off refresh) adds to the last status, so what the full run did stays visible
        prev = json.loads(sp.read_text(encoding="utf-8"))
        status["steps"] = {k: v for k, v in (prev.get("steps") or {}).items() if k not in todo}
        status["errors"] = {k: v for k, v in (prev.get("errors") or {}).items() if k not in todo}
        status["minutes"] = {k: v for k, v in (prev.get("minutes") or {}).items() if k not in todo}
        status["earlier_run_started"] = prev.get("started", "")
    for name, cmd, required in STEPS:
        if name not in todo: continue
        if name in ON_REQUEST and not arg("--only"): continue
        save = lambda: sp.write_text(json.dumps(status, indent=1), encoding="utf-8")    # after every step: a job stopped from outside still leaves its record
        if name in MONTHLY and not arg("--only") and dt.date.today().day > 7: print(f"=== {name} === skipped: runs in the first week of each month", flush=True); status["steps"][name] = "not due"; continue
        if name == "build" and page.exists(): shutil.copy2(page, keep)
        print(f"=== {name} ===", flush=True)
        proc = subprocess.Popen([sys.executable, "-u"] + cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                start_new_session=True)        # its own process group, so stopping it also stops any browser it started
        limit, stopped, t0 = LIMITS.get(name, LIMIT), [], time.monotonic()
        timer = threading.Timer(limit * 60, lambda: (stopped.append(1), os.killpg(proc.pid, signal.SIGKILL)))
        timer.daemon = True; timer.start()
        tail = []
        for line in proc.stdout:                                     # shown live, and the last lines are kept so a failure explains itself in refresh_status.json
            print(line, end="", flush=True); tail = (tail + [line.rstrip()])[-6:]
        code = proc.wait(); timer.cancel(); status["minutes"][name] = round((time.monotonic() - t0) / 60, 1)
        if stopped: code = code or 1; tail.append(f"stopped after {limit} minutes")
        status["steps"][name] = "ok" if code == 0 else ("timed out" if stopped else "failed")
        if code != 0: status.setdefault("errors", {})[name] = " / ".join(t for t in tail if t)[-500:]
        if code != 0:
            print(f"{name} FAILED (exit {code})" + ("; stopping, page left as it was" if required else "; its data is left as it was"), flush=True)
            if name == "build" and keep.exists(): shutil.copy2(keep, page)
            if required: ok = False; save(); break
        save()
    status["finished"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"); status["page_rebuilt"] = status["steps"].get("build") == "ok"
    sp.write_text(json.dumps(status, indent=1), encoding="utf-8")
    print(json.dumps(status["steps"]), flush=True)
    return 0 if ok else 1


def join(paths, out=None):
    """The two groups' records -> data/refresh_status.json, one record for the week (the build job then adds tests and build)."""
    out = out or ROOT / "data" / "refresh_status.json"
    st = {"started": "", "steps": {}, "errors": {}, "minutes": {}, "groups": {}}
    for p in paths:
        p = Path(p)
        if not p.exists(): st["groups"][p.stem] = "no record (the job did not start or was cancelled)"; continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("steps", "errors", "minutes"): st[k].update(d.get(k) or {})
        st["started"] = min(x for x in (st["started"], d.get("started", "")) if x) if d.get("started") else st["started"]
        st["groups"][p.stem] = "finished" if d.get("finished") else "stopped before the end (time limit)"
    for name, _, _ in STEPS:                     # a step of a group that ran out of time and never started shows as such, not as missing
        g = GROUP_OF(name)
        if g != "build" and name not in ON_REQUEST and name not in st["steps"] and any(k.endswith(g) and v != "finished" for k, v in st["groups"].items()):
            st["steps"][name] = "cut off or not reached (time limit)"
    out.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return st


if __name__ == "__main__":
    if sys.argv[1:2] == ["--join"]: join(sys.argv[2:]); sys.exit(0)
    sys.exit(main(sys.argv[1:]))
