"""refresh_all.py: the weekly run's rules, pinned before the runner moved into clew_core (2026-11-11).
A required step that fails stops the run and leaves the page as it was; an optional one doesn't; a failed build puts
the previous page back; a step past its time limit is stopped; a partial run keeps the full run's record; join marks
steps a cut-off group never reached."""
import json, os, sys
import refresh_all as ra

PY = lambda code: ["-c", code]


def _setup(tmp, steps, limits=None):
    saved = (ra.STEPS, ra.ROOT, ra.LIMITS, ra.LIMIT, ra.MONTHLY, os.environ.get("REFRESH_STATUS"))
    (tmp / "site").mkdir(); (tmp / "data").mkdir()
    ra.STEPS, ra.ROOT, ra.LIMITS, ra.LIMIT, ra.MONTHLY = steps, tmp, limits or {}, 1, set()
    os.environ["REFRESH_STATUS"] = "data/status.json"
    def restore():
        ra.STEPS, ra.ROOT, ra.LIMITS, ra.LIMIT, ra.MONTHLY = saved[:5]
        if saved[5] is None: os.environ.pop("REFRESH_STATUS", None)
        else: os.environ["REFRESH_STATUS"] = saved[5]
    return restore


def _status(tmp): return json.loads((tmp / "data" / "status.json").read_text(encoding="utf-8"))


def test_unknown_step_names_stop_before_anything_runs(tmp):
    restore = _setup(tmp, [("a", PY("pass"), False)])
    try:
        try: ra.main(["--only", "a,typo"]); raise AssertionError("ran with an unknown step")
        except SystemExit as e: assert "typo" in str(e)
    finally: restore()


def test_required_failure_stops_the_run_and_optional_failure_does_not(tmp):
    restore = _setup(tmp, [("opt", PY("import sys; print('site down'); sys.exit(2)"), False),
                           ("req", PY("import sys; print('broken'); sys.exit(1)"), True),
                           ("after", PY("open('ran.txt','w').write('x')"), False)])
    try:
        assert ra.main([]) == 1
        st = _status(tmp)
        assert st["steps"] == {"opt": "failed", "req": "failed"} and "after" not in st["steps"]
        assert "site down" in st["errors"]["opt"] and "broken" in st["errors"]["req"]
        assert not (tmp / "ran.txt").exists() and st["page_rebuilt"] is False
    finally: restore()


def test_a_failed_build_puts_the_previous_page_back(tmp):
    restore = _setup(tmp, [("build", PY("open('site/index.html','w').write('half-written'); raise SystemExit(1)"), True)])
    try:
        (tmp / "site" / "index.html").write_text("good page", encoding="utf-8")
        assert ra.main([]) == 1
        assert (tmp / "site" / "index.html").read_text(encoding="utf-8") == "good page"
    finally: restore()


def test_a_step_past_its_limit_is_stopped(tmp):
    if not hasattr(os, "killpg"): return               # the runner stops steps by process group: Linux runners only
    restore = _setup(tmp, [("slow", PY("import time; time.sleep(30)"), False), ("next", PY("pass"), False)], {"slow": 0.02})
    try:
        assert ra.main([]) == 0
        st = _status(tmp)
        assert st["steps"] == {"slow": "timed out", "next": "ok"} and "stopped after 0.02 minutes" in st["errors"]["slow"]
    finally: restore()


def test_a_partial_run_keeps_the_full_runs_record(tmp):
    restore = _setup(tmp, [("a", PY("pass"), False), ("b", PY("pass"), False)])
    try:
        (tmp / "data" / "status.json").write_text(json.dumps({"started": "2026-11-09T11:17:00+00:00", "steps": {"a": "failed", "b": "failed"},
                                                              "errors": {"a": "x", "b": "y"}, "minutes": {"a": 1, "b": 2}}), encoding="utf-8")
        assert ra.main(["--only", "b"]) == 0
        st = _status(tmp)
        assert st["steps"] == {"a": "failed", "b": "ok"} and st["errors"] == {"a": "x"}
        assert st["earlier_run_started"] == "2026-11-09T11:17:00+00:00"
    finally: restore()


def test_join_marks_steps_a_cut_off_group_never_reached(tmp):
    restore = _setup(tmp, [("a", PY("pass"), False), ("fec", PY("pass"), False), ("tests", PY("pass"), True)])
    try:
        (tmp / "data" / "refresh_status_main.json").write_text(json.dumps({"started": "2026-11-09T11:17:00+00:00", "steps": {"a": "ok"}, "finished": "x"}))
        (tmp / "data" / "refresh_status_money.json").write_text(json.dumps({"started": "2026-11-09T11:18:00+00:00", "steps": {}}))
        st = ra.join([tmp / "data" / "refresh_status_main.json", tmp / "data" / "refresh_status_money.json"], tmp / "data" / "joined.json")
        assert st["steps"] == {"a": "ok", "fec": "cut off or not reached (time limit)"}
        assert st["groups"] == {"refresh_status_main": "finished", "refresh_status_money": "stopped before the end (time limit)"}
        assert st["started"] == "2026-11-09T11:17:00+00:00"
    finally: restore()
