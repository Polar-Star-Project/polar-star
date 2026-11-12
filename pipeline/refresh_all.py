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
    ("contract",   ["pipeline/export_contract.py"], False),          # data contract for Ariadne's Clew (entities/claims/sources by UEI)
    ("tests",      ["pipeline/run_tests.py"], True),
    ("build",      ["pipeline/build_site.py"], True),
]

# Longest a step may run before it is stopped (minutes), so one slow or stuck source cannot use up the whole run and keep the
# page from being rebuilt. A stopped step counts as failed: its data is left as it was and it is tried again next week.
LIMIT = 40
LIMITS = {"records": 60, "transfers": 60, "fec": 90, "jfc": 60, "donors": 60, "membercom": 60, "topdonors": 60, "countrypacs": 60,
          "firmbase": 60, "flights": 60, "tests": 30, "build": 20, "dockets": 20,
          "awards": 60,                                            # about 47 minutes for ~1,160 awards and the retries
          "statements": 70, "fara": 90, "vendorlobby": 45}         # these read for a set time (60, 80, 30 minutes) and carry on next run

# The weekly workflow runs two groups side by side, each in its own job with its own time limit: "money" (the FEC and
# lobbying collectors, slow because those APIs limit requests per minute and hour) and "main" (everything else). The
# tests and the build run afterwards, in a third job, on what both saved.
MONEY = {"politicians", "membercom", "lobbying", "vendorlobby", "fec", "jfc", "donors", "fara", "firms", "firmbase", "sec", "topdonors", "countrypacs"}
GROUP_OF = lambda name: "build" if name in ("tests", "build") else "money" if name in MONEY else "main"

ON_REQUEST = {"probe"}   # steps that run only when named in --only
MONTHLY = set()          # steps that run only in the first week of a month (none now: the audit check is weekly again)


from clew_core import orchestrator as _orch    # shared framework (pipeline/clew_core); same rules as before


def pick(names, only, skip):
    """Which steps run, in the fixed order. Unknown names are an error, so a typo cannot silently skip the tests."""
    return _orch.pick(names, only, skip, [n for n, _, _ in STEPS])


def main(argv):
    return _orch.run(argv, STEPS, ROOT, LIMITS, LIMIT, GROUP_OF, ON_REQUEST, MONTHLY,
                     status_file=os.environ.get("REFRESH_STATUS", "data/refresh_status.json"))


def join(paths, out=None):
    """The two groups' records -> data/refresh_status.json, one record for the week (the build job then adds tests and build)."""
    return _orch.join(paths, out or ROOT / "data" / "refresh_status.json", STEPS, GROUP_OF, ON_REQUEST)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--join"]: join(sys.argv[2:]); sys.exit(0)
    sys.exit(main(sys.argv[1:]))
