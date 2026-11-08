"""fec_pace.py and the two collectors that use it: a read cut into pieces across runs ends with the same result as one
read in one go, a page is never counted twice, and nothing is written until the read is complete."""
import io, json, urllib.error
import fec_pace as fp


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_reader_paces_and_pauses_on_time_and_on_429():
    t = [0.0]; slept = []
    r = fp.Reader("k", minutes=1, pace=4, opener=lambda u: Resp(b'{"ok": 1}'), clock=lambda: t[0], sleep=lambda s: slept.append(s))
    assert r.call("/x/") == {"ok": 1} and slept == [4] and r.calls == 1
    t[0] = 61
    try: r.call("/x/"); assert False
    except fp.Pause: pass
    def busy(u): raise urllib.error.HTTPError(u, 429, "too many", {}, None)
    r2 = fp.Reader("k", minutes=5, opener=busy, clock=lambda: 0, sleep=lambda s: None)
    try: r2.call("/x/"); assert False
    except fp.Pause as e: assert "429" in str(e)


def test_progress_is_kept_for_the_same_cycle_only_and_not_too_long(tmp_path):
    import datetime as dt
    old = fp.PROGRESS; fp.PROGRESS = tmp_path
    try:
        st = fp.load("x", 2026, dt.date(2026, 11, 1)); st["n"] = 5; fp.save("x", st)
        assert fp.load("x", 2026, dt.date(2026, 11, 8))["n"] == 5
        assert "n" not in fp.load("x", 2028, dt.date(2026, 11, 8))                  # another cycle starts over
        assert "n" not in fp.load("x", 2026, dt.date(2026, 12, 31))                 # too old starts over
        fp.clear("x"); assert not (tmp_path / "x.json").exists()
    finally: fp.PROGRESS = old


def _fake_fec(pages_per_chunk=3):
    """Schedule A: every chunk of committees answers in pages_per_chunk pages of one 100-dollar gift each; schedule E: one page."""
    def call(path, **q):
        if "schedule_a" in path:
            n = int((q.get("last_index") or 0)) + 1
            res = [{"committee_id": ch, "contributor_id": "C9", "contributor_name": "SOME PAC", "contribution_receipt_amount": 100.0} for ch in q["committee_id"]]
            return {"results": res, "pagination": {"last_indexes": {"last_index": n} if n < pages_per_chunk else None}}
        return {"results": [{"candidate_id": c, "support_oppose_indicator": "S", "committee_id": "C7", "committee_name": "SUPER PAC", "total": 50.0, "count": 1} for c in q["candidate_id"]],
                "pagination": {"pages": 1}}
    return call


def test_member_top_donors_read_in_pieces_equals_one_read(tmp_path):
    import csv, member_top_donors as m
    ref = tmp_path / "ref"; ref.mkdir()
    bgs = [f"B{i:03d}" for i in range(320)]
    (ref / "members.csv").write_text("bioguide|current\n" + "".join(f"{b}|1\n" for b in bgs))
    (ref / "member_committees.csv").write_text("bioguide|committee_id|designation\n" + "".join(f"{b}|C{b}|P\n" for b in bgs))
    legs = json.dumps([{"id": {"bioguide": b, "fec": ["H" + b]}} for b in bgs]).encode()
    old = (m.REF, fp.PROGRESS, fp.Reader, m.urllib.request.urlopen); rest = fp.REST_DAYS
    def run(limit):
        class R:
            calls = 0
            def __init__(self, key): pass
            def call(self, path, **q):
                if limit is not None and R.calls >= limit: raise fp.Pause("time is up for this run")
                R.calls += 1; return _fake_fec()(path, **q)
        fp.Reader = R; m.main(); return R.calls
    try:
        m.REF, fp.PROGRESS = ref, tmp_path / "progress"; fp.REST_DAYS = 0
        m.urllib.request.urlopen = lambda *a, **k: Resp(legs)
        import os; os.environ["FEC_API_KEY"] = "k"
        run(None); one = (ref / "member_top_donors.csv").read_text()
        (ref / "member_top_donors.csv").unlink()
        runs = 0
        while not (ref / "member_top_donors.csv").exists():
            run(7); runs += 1
            assert runs < 40
            if not (ref / "member_top_donors.csv").exists(): assert (tmp_path / "progress" / "member_top_donors.json").exists()
        assert runs > 1 and (ref / "member_top_donors.csv").read_text() == one          # same totals: no page counted twice
        assert not (tmp_path / "progress" / "member_top_donors.json").exists()
    finally:
        m.REF, fp.PROGRESS, fp.Reader, m.urllib.request.urlopen = old; fp.REST_DAYS = rest


def test_country_pacs_read_in_pieces_equals_one_read(tmp_path):
    import country_pacs as c
    ref = tmp_path / "ref"; ref.mkdir()
    bgs = [f"B{i:03d}" for i in range(150)]
    (ref / "members.csv").write_text("bioguide|current\n" + "".join(f"{b}|1\n" for b in bgs))
    (ref / "member_committees.csv").write_text("bioguide|committee_id|designation\n" + "".join(f"{b}|C{b}|P\n" for b in bgs))
    (ref / "country_pacs_affiliates.csv").write_text("name|affiliate_of|country\n")
    legs = json.dumps([{"id": {"bioguide": b, "fec": ["H" + b]}} for b in bgs]).encode()
    def fec(path, **q):
        if path == "/committees/":
            hit = [{"committee_id": "C00ANC", "name": "ARMENIAN NATIONAL COMMITTEE PAC", "designation": "U"}] if q["q"] == "ARMENIAN" else []
            return {"results": hit, "pagination": {"pages": 1}}
        if "schedule_b" in path:
            n = int(q.get("last_index") or 0) + 1
            return {"results": [{"recipient_committee_id": q["recipient_committee_id"][n], "disbursement_amount": 1000.0}], "pagination": {"last_indexes": {"last_index": n} if n < 3 else None}}
        return {"results": [], "pagination": {}}
    old = (c.REF, fp.PROGRESS, fp.Reader, c.urllib.request.urlopen); rest = fp.REST_DAYS
    def run(limit):
        class R:
            calls = 0
            def __init__(self, key): pass
            def call(self, path, **q):
                if limit is not None and R.calls >= limit: raise fp.Pause("time is up for this run")
                R.calls += 1; return fec(path, **q)
        fp.Reader = R; c.main()
    try:
        c.REF, fp.PROGRESS = ref, tmp_path / "progress"; fp.REST_DAYS = 0
        c.urllib.request.urlopen = lambda *a, **k: Resp(legs)
        import os; os.environ["FEC_API_KEY"] = "k"
        run(None); one = (ref / "country_pacs_money.csv").read_text()
        assert "C00ANC|B001|G|1000|1" in one
        (ref / "country_pacs_money.csv").unlink(); runs = 0
        while not (ref / "country_pacs_money.csv").exists():
            run(9); runs += 1; assert runs < 60
        assert runs > 1 and (ref / "country_pacs_money.csv").read_text() == one
    finally:
        c.REF, fp.PROGRESS, fp.Reader, c.urllib.request.urlopen = old; fp.REST_DAYS = rest
