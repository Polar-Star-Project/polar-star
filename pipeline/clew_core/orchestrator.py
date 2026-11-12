"""The refresh runner (taken from Polar Star's refresh_all.py, 2026-11-11). The project supplies its steps and limits.

A step marked required stops the run if it fails, and the published page is left as it was. Every other step may fail:
its data stays as it was and the failure is written to the status file. The page is rebuilt only after every test
passes, and the previous page is put back if the build fails. Each step has a time limit; a stopped step counts as failed.
"""
import datetime as dt, json, os, shutil, signal, subprocess, sys, threading, time
from pathlib import Path


def pick(names, only, skip, known):
    """Which steps run, in the fixed order. Unknown names are an error, so a typo cannot silently skip the tests."""
    bad = [x for x in (only or []) + (skip or []) if x not in known]
    if bad: raise SystemExit(f"unknown step(s): {', '.join(bad)}. Steps are: {', '.join(known)}")
    return [n for n in names if (not only or n in only) and n not in (skip or [])]


def run(argv, steps, root, limits, default_limit, group_of, on_request=(), monthly=(), status_file="data/refresh_status.json",
        page="site/index.html", keep="site/index.previous.html", build_step="build"):
    arg = lambda flag: argv[argv.index(flag) + 1].split(",") if flag in argv else None
    known = [n for n, _, _ in steps]
    todo = pick(known, arg("--only"), arg("--skip"), known)
    if arg("--group"): todo = [n for n in todo if group_of(n) in arg("--group")]
    root = Path(root); sp = root / status_file
    page, keep = root / page, root / keep
    status, ok = {"started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "steps": {}, "minutes": {}}, True
    partial = arg("--only") or arg("--group")
    if partial and sp.exists():           # a partial run (say, the rebuild after a cut-off refresh) adds to the last status, so what the full run did stays visible
        prev = json.loads(sp.read_text(encoding="utf-8"))
        status["steps"] = {k: v for k, v in (prev.get("steps") or {}).items() if k not in todo}
        status["errors"] = {k: v for k, v in (prev.get("errors") or {}).items() if k not in todo}
        status["minutes"] = {k: v for k, v in (prev.get("minutes") or {}).items() if k not in todo}
        status["earlier_run_started"] = prev.get("started", "")
    for name, cmd, required in steps:
        if name not in todo: continue
        if name in on_request and not arg("--only"): continue
        save = lambda: sp.write_text(json.dumps(status, indent=1), encoding="utf-8")    # after every step: a job stopped from outside still leaves its record
        if name in monthly and not arg("--only") and dt.date.today().day > 7: print(f"=== {name} === skipped: runs in the first week of each month", flush=True); status["steps"][name] = "not due"; continue
        if name == build_step and page.exists(): shutil.copy2(page, keep)
        print(f"=== {name} ===", flush=True)
        proc = subprocess.Popen([sys.executable, "-u"] + cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                start_new_session=True)        # its own process group, so stopping it also stops any browser it started
        limit, stopped, t0 = limits.get(name, default_limit), [], time.monotonic()
        timer = threading.Timer(limit * 60, lambda: (stopped.append(1), os.killpg(proc.pid, signal.SIGKILL)))
        timer.daemon = True; timer.start()
        tail = []
        for line in proc.stdout:                                     # shown live, and the last lines are kept so a failure explains itself in the status file
            print(line, end="", flush=True); tail = (tail + [line.rstrip()])[-6:]
        code = proc.wait(); timer.cancel(); status["minutes"][name] = round((time.monotonic() - t0) / 60, 1)
        if stopped: code = code or 1; tail.append(f"stopped after {limit} minutes")
        status["steps"][name] = "ok" if code == 0 else ("timed out" if stopped else "failed")
        if code != 0: status.setdefault("errors", {})[name] = " / ".join(t for t in tail if t)[-500:]
        if code != 0:
            print(f"{name} FAILED (exit {code})" + ("; stopping, page left as it was" if required else "; its data is left as it was"), flush=True)
            if name == build_step and keep.exists(): shutil.copy2(keep, page)
            if required: ok = False; save(); break
        save()
    status["finished"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"); status["page_rebuilt"] = status["steps"].get(build_step) == "ok"
    sp.write_text(json.dumps(status, indent=1), encoding="utf-8")
    print(json.dumps(status["steps"]), flush=True)
    return 0 if ok else 1


def join(paths, out, steps, group_of, on_request=(), build_group="build"):
    """The groups' records -> one status record for the run (the build job then adds tests and build)."""
    st = {"started": "", "steps": {}, "errors": {}, "minutes": {}, "groups": {}}
    for p in paths:
        p = Path(p)
        if not p.exists(): st["groups"][p.stem] = "no record (the job did not start or was cancelled)"; continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for k in ("steps", "errors", "minutes"): st[k].update(d.get(k) or {})
        st["started"] = min(x for x in (st["started"], d.get("started", "")) if x) if d.get("started") else st["started"]
        st["groups"][p.stem] = "finished" if d.get("finished") else "stopped before the end (time limit)"
    for name, _, _ in steps:                     # a step of a group that ran out of time and never started shows as such, not as missing
        g = group_of(name)
        if g != build_group and name not in on_request and name not in st["steps"] and any(k.endswith(g) and v != "finished" for k, v in st["groups"].items()):
            st["steps"][name] = "cut off or not reached (time limit)"
    Path(out).write_text(json.dumps(st, indent=1), encoding="utf-8")
    return st
