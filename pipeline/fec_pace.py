"""Steady, resumable reading of the FEC API for the long collectors (member_top_donors.py, country_pacs.py).

The FEC allows a key 1,000 requests an hour. Rather than asking for more, these collectors read at a steady pace below that
(PACE seconds between requests), stop for the week when their time is up or when the FEC says "too many requests", and save
where they got to in data/progress/<name>.json. The next weekly run picks up from there. The page keeps showing the last
complete read until a new one is finished; only then are the output files replaced and the progress file removed.

A saved position is used only for the same election cycle and for at most MAX_AGE_DAYS; otherwise the read starts over.
The progress files hold committee-level totals only (organizations, never individual donors), like the outputs.
"""
import datetime as dt, json, os, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

API = "https://api.open.fec.gov/v1"
PROGRESS = Path(__file__).resolve().parent.parent / "data" / "progress"
PACE = float(os.environ.get("FEC_PACE_SECONDS", "4"))          # 900 requests an hour at most, under the FEC's 1,000
MINUTES = float(os.environ.get("FEC_MINUTES", "50"))           # reading time per run, under refresh_all's 60-minute step limit
MAX_AGE_DAYS = 42


class Pause(Exception):
    """Time is up for this run, or the FEC asked us to slow down: save and carry on next week."""


class Reader:
    def __init__(self, key, minutes=MINUTES, pace=PACE, opener=None, clock=time.monotonic, sleep=time.sleep):
        self.key, self.pace, self.clock, self.sleep = key, pace, clock, sleep
        self.end = clock() + minutes * 60
        self.open = opener or (lambda url: urllib.request.urlopen(url, timeout=120))
        self.calls = 0

    def call(self, path, **q):
        """One FEC request at the steady pace. Raises Pause when time is up or on HTTP 429; SystemExit when the FEC keeps failing."""
        url = f"{API}{path}?" + urllib.parse.urlencode(dict(q, api_key=self.key), doseq=True); err = ""
        for i in range(6):
            if self.clock() >= self.end: raise Pause("time is up for this run")
            try:
                with self.open(url) as r:
                    self.calls += 1; self.sleep(self.pace); return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429: raise Pause("the FEC asked us to slow down (429)")
                err = f"HTTP {e.code}"
                if e.code == 422: break
            except Exception as e:
                err = str(e)[:160]
            self.sleep(45 if i < 3 else 120)                     # the FEC is busy or a request timed out: wait, then try again
        raise SystemExit(f"FEC did not answer {path}: {err}. Progress is kept; nothing else written.")


def load(name, cycle, today=None):
    """The saved position for this collector, or a fresh one when there is none, it is for another cycle, or it is too old."""
    today = today or dt.date.today()
    p = PROGRESS / f"{name}.json"
    if p.exists():
        st = json.loads(p.read_text(encoding="utf-8"))
        if st.get("cycle") == cycle and (today - dt.date.fromisoformat(st["started"])).days <= MAX_AGE_DAYS: return st
    return {"cycle": cycle, "started": str(today), "runs": 0}


def save(name, st):
    PROGRESS.mkdir(parents=True, exist_ok=True)
    st["runs"] = st.get("runs", 0) + 1
    (PROGRESS / f"{name}.json").write_text(json.dumps(st, separators=(",", ":")), encoding="utf-8")


def clear(name):
    p = PROGRESS / f"{name}.json"
    if p.exists(): p.unlink()
