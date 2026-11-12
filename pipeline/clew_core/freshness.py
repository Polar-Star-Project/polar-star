"""Per-source freshness: every source row has max_age_days; a stale source is flagged on the page, never served as current."""
import datetime as dt


def source_rows(rows, dyn, today, checked=None):
    """Footer list of sources. A row with a key takes its date from the data itself (dyn); the others carry the date they were
    last read by hand. stale = older than the row's max_age_days (0 = never goes stale). checked = {key: the day the collector
    last looked at the publisher}: a stale source checked within its max_age_days is the newest the publisher has posted, and
    the page says so (row[8]) instead of leaving the reader to guess whether the refresh fell behind. Returns rows and the stale names."""
    out, stale, checked = [], [], checked or {}
    for r in rows:
        d = dyn.get(r["key"]) or r["read"]; age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(d)).days
        old = int(r["max_age_days"]) > 0 and age > int(r["max_age_days"])
        ck = checked.get(r["key"], "") if old else ""
        if ck and (dt.date.fromisoformat(today) - dt.date.fromisoformat(ck)).days > int(r["max_age_days"]): ck = ""
        if old: stale.append(f'{r["what_en"]} ({d}, {age} days' + (f'; nothing newer posted, checked {ck})' if ck else ')'))
        out.append([r["what_en"], r["what_es"], r["publisher"], d, r["url"], int(bool(r["key"])), int(old), r["key"], ck])
    return out, stale
