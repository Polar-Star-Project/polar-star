"""Steady, resumable reading of slow or rate-limited sources (taken from Polar Star's fec_pace.py, 2026-11-11).

Instead of asking an agency for a higher limit, a collector reads at a steady pace, stops when its time for this run is up
or the server says "too many requests", saves where it got to, and carries on next run. The project passes its own
progress folder, API base and limits; nothing here is specific to one source.
"""
import datetime as dt, json, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path


class Pause(Exception):
    """Time is up for this run, or the server asked us to slow down: save and carry on next run."""


class Deadline:
    """This run's reading time for a collector that does not go through Reader."""
    def __init__(self, minutes, clock=time.monotonic):
        self.clock, self.end = clock, clock() + minutes * 60
    def up(self): return self.clock() >= self.end


def rested(progress_dir, name, meta, days, today=None):
    """True when no read is under way for `name` and the last complete read (the "read" date in its meta file) is under
    `days` old: the collector skips this run. A missing or unreadable meta file never rests."""
    today = today or dt.date.today()
    if (Path(progress_dir) / f"{name}.json").exists() or not Path(meta).exists(): return False
    try: last = dt.date.fromisoformat(json.loads(Path(meta).read_text(encoding="utf-8"))["read"][:10])
    except Exception: return False
    return (today - last).days < days


class Reader:
    """One API at a steady pace. `who` and `name` word the messages ("the FEC asked us...", "FEC did not answer...")."""
    def __init__(self, api, key, minutes, pace, opener=None, clock=time.monotonic, sleep=time.sleep, who="the source", name="Source"):
        self.api, self.key, self.pace, self.clock, self.sleep, self.who, self.name = api, key, pace, clock, sleep, who, name
        self.end = clock() + minutes * 60
        self.open = opener or (lambda url: urllib.request.urlopen(url, timeout=120))
        self.calls = 0

    def call(self, path, **q):
        """One request at the steady pace. Raises Pause when time is up or on HTTP 429; SystemExit when the source keeps failing."""
        url = f"{self.api}{path}?" + urllib.parse.urlencode(dict(q, api_key=self.key), doseq=True); err = ""
        for i in range(6):
            if self.clock() >= self.end: raise Pause("time is up for this run")
            try:
                with self.open(url) as r:
                    self.calls += 1; self.sleep(self.pace); return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429: raise Pause(f"{self.who} asked us to slow down (429)")
                err = f"HTTP {e.code}"
                if e.code == 422: break
            except Exception as e:
                err = str(e)[:160]
            self.sleep(45 if i < 3 else 120)                     # the source is busy or a request timed out: wait, then try again
        raise SystemExit(f"{self.name} did not answer {path}: {err}. Progress is kept; nothing else written.")


def load(progress_dir, name, cycle, max_age_days, today=None):
    """The saved position for this collector, or a fresh one when there is none, it is for another cycle, or it is too old."""
    today = today or dt.date.today()
    p = Path(progress_dir) / f"{name}.json"
    if p.exists():
        st = json.loads(p.read_text(encoding="utf-8"))
        if st.get("cycle") == cycle and (today - dt.date.fromisoformat(st["started"])).days <= max_age_days: return st
    return {"cycle": cycle, "started": str(today), "runs": 0}


def save(progress_dir, name, st):
    Path(progress_dir).mkdir(parents=True, exist_ok=True)
    st["runs"] = st.get("runs", 0) + 1
    (Path(progress_dir) / f"{name}.json").write_text(json.dumps(st, separators=(",", ":")), encoding="utf-8")


def clear(progress_dir, name):
    p = Path(progress_dir) / f"{name}.json"
    if p.exists(): p.unlink()
