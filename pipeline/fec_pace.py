"""Steady, resumable reading of the FEC API for the long collectors (member_top_donors.py, country_pacs.py).

The FEC allows a key 1,000 requests an hour. Rather than asking for more, these collectors read at a steady pace below that
(PACE seconds between requests), stop for the week when their time is up or when the FEC says "too many requests", and save
where they got to in data/progress/<name>.json. The next weekly run picks up from there. The page keeps showing the last
complete read until a new one is finished; only then are the output files replaced and the progress file removed.

A saved position is used only for the same election cycle and for at most MAX_AGE_DAYS; otherwise the read starts over.
The progress files hold committee-level totals only (organizations, never individual donors), like the outputs.

load/save/clear, Deadline and rested() also serve the other slow collectors (fara.py, vendor_lobbying.py,
visit_statements.py): each reads for a fixed time per run and carries on next week, so no step runs into refresh_all's
limit and every read finishes. A collector whose source changes slowly rests for REST_DAYS after a complete read, which
keeps the weekly run, and the Actions minutes it uses, short.
"""
import datetime as dt, json, os, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

API = "https://api.open.fec.gov/v1"
PROGRESS = Path(__file__).resolve().parent.parent / "data" / "progress"
PACE = float(os.environ.get("FEC_PACE_SECONDS", "4"))          # 900 requests an hour at most, under the FEC's 1,000
MINUTES = float(os.environ.get("FEC_MINUTES", "50"))           # reading time per run, under refresh_all's 60-minute step limit
MAX_AGE_DAYS = 42
REST_DAYS = int(os.environ.get("REST_DAYS", "28"))            # after a complete read, a slow-changing source is read again after this many days


from clew_core.pacing import Pause, Deadline          # shared framework (pipeline/clew_core); same classes as before
from clew_core import pacing as _pacing


def rested(name, meta, days=None, today=None):
    """True when no read is under way for `name` and the last complete read (the "read" date in its meta file) is under
    `days` old: the collector skips this run. A missing or unreadable meta file never rests."""
    return _pacing.rested(PROGRESS, name, meta, REST_DAYS if days is None else days, today)


class Reader(_pacing.Reader):
    def __init__(self, key, minutes=MINUTES, pace=PACE, opener=None, clock=time.monotonic, sleep=time.sleep):
        super().__init__(API, key, minutes, pace, opener, clock, sleep, who="the FEC", name="FEC")


def load(name, cycle, today=None):
    """The saved position for this collector, or a fresh one when there is none, it is for another cycle, or it is too old."""
    return _pacing.load(PROGRESS, name, cycle, MAX_AGE_DAYS, today)


def save(name, st):
    _pacing.save(PROGRESS, name, st)


def clear(name):
    _pacing.clear(PROGRESS, name)
