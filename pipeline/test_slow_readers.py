"""fara.py, vendor_lobbying.py and visit_statements.py read for a set time per run and carry on next run: a read cut into
pieces ends with the same file as one read in one go, and a source read completely less than REST_DAYS ago is not read."""
import csv, datetime as dt, json
import fec_pace as fp


def _with(tmp_path, mod):
    ref = tmp_path / "ref"; ref.mkdir()
    saved = (mod.REF, fp.PROGRESS, fp.REST_DAYS)
    mod.REF, fp.PROGRESS, fp.REST_DAYS = ref, tmp_path / "progress", 0
    return ref, lambda: setattr(mod, "REF", saved[0]) or setattr(fp, "PROGRESS", saved[1]) or setattr(fp, "REST_DAYS", saved[2])


def test_rested_only_after_a_complete_read(tmp_path):
    old = (fp.PROGRESS, fp.REST_DAYS); fp.PROGRESS = tmp_path / "p"
    try:
        fp.REST_DAYS = 28; meta = tmp_path / "m.json"
        assert not fp.rested("x", meta)                                               # never read
        meta.write_text(json.dumps({"read": "2026-11-01"}))
        assert fp.rested("x", meta, today=dt.date(2026, 11, 8)) and not fp.rested("x", meta, today=dt.date(2026, 12, 1))
        fp.save("x", {"cycle": 1, "started": "2026-11-08"})
        assert not fp.rested("x", meta, today=dt.date(2026, 11, 8))                   # a read under way always carries on
        meta.write_text("not json"); fp.clear("x")
        assert not fp.rested("x", meta, today=dt.date(2026, 11, 8))
    finally: fp.PROGRESS, fp.REST_DAYS = old


def test_fara_in_pieces_equals_one_read(tmp_path):
    import fara
    ref, undo = _with(tmp_path, fara)
    reg = [{"Registration_Number": str(6000 + i), "Name": f"FIRM {i}"} for i in range(150)]
    t = [0.0]
    def get(url):
        t[0] += 60                                                                    # one minute per request (the clock counts seconds)
        if url.endswith("/Registrants/json/Active"): return {"REGISTRANTS_ACTIVE": {"ROW": reg}}
        n = url.rsplit("/", 1)[1]
        if "/ForeignPrincipals/" in url:
            return {} if int(n) % 3 else {"ROWSET": {"ROW": {"FP_NAME": f"Ministry {n}", "COUNTRY_NAME": "RURITANIA", "REGISTRANT_NAME": f"FIRM {n}", "FP_REG_DATE": "2024-01-02T00:00:00"}}}
        return {"ROWSET": {"ROW": [{"DOCUMENT_TYPE": "Exhibit AB", "FOREIGN_PRINCIPAL_NAME": f"Ministry {n}", "URL": f"https://efile.fara.gov/{n}.pdf", "DATE_STAMPED": "2024"}]}}
    try:
        fara.main(get=get, minutes=10 ** 6, clock=lambda: t[0]); one = (ref / "fara_principals.csv").read_text(encoding="utf-8")
        assert one.count("\n") == 51 and "Ruritania|Ministry 6000|FIRM 6000|6000|2024-01-02|https://efile.fara.gov/6000.pdf" in one
        (ref / "fara_principals.csv").unlink(); runs = 0
        while not (ref / "fara_principals.csv").exists():
            fara.main(get=get, minutes=40, clock=lambda: t[0]); runs += 1; assert runs < 30
        assert runs > 2 and (ref / "fara_principals.csv").read_text(encoding="utf-8") == one
        assert not (tmp_path / "progress" / "fara.json").exists()
        fp.REST_DAYS = 28; t0 = t[0]; fara.main(get=get, minutes=40, clock=lambda: t[0]); assert t[0] == t0     # rests after a complete read
    finally: undo()


def test_vendor_lobbying_in_pieces_equals_one_read(tmp_path):
    import vendor_lobbying as v
    ref, undo = _with(tmp_path, v)
    names = [f"ACME {w} INC" for w in ("ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL")]
    (ref / "ice_awards.csv").write_text("recipient|window_usd\n" + "".join(f"{n}|{20_000_000 + i}\n" for i, n in enumerate(names)), encoding="utf-8")
    t = [0.0]
    def fetch(url):
        t[0] += 60
        k = url.split("client_name=")[1].split("&")[0].replace("+", " ")
        f = {"client": {"name": k + " INC", "id": 1}, "registrant": {"id": 2}, "filing_type": "Q1", "filing_year": 2024, "filing_period": "first_quarter",
             "dt_posted": "2024-04-01", "income": "10000", "expenses": None, "filing_document_url": "https://lda.gov/x",
             "lobbying_activities": [{"general_issue_code": "IMM", "government_entities": [{"name": "Immigration & Customs Enforcement (ICE)"}]}]}
        return {"results": [f] if "filing_year=2024" in url else [], "next": None}
    try:
        v.main(fetch=fetch, minutes=10 ** 6, clock=lambda: t[0]); one = (ref / "vendor_lobbying.csv").read_text(encoding="utf-8")
        assert one.count("\n") == 9 and "ACME ALPHA INC|ACME ALPHA|10000|1|1|1|https://lda.gov/x" in one
        (ref / "vendor_lobbying.csv").unlink(); runs = 0
        while not (ref / "vendor_lobbying.csv").exists():
            v.main(fetch=fetch, minutes=10, clock=lambda: t[0]); runs += 1; assert runs < 30
        assert runs > 1 and (ref / "vendor_lobbying.csv").read_text(encoding="utf-8") == one
    finally: undo()


def test_statements_take_members_in_turn():
    import visit_statements as vs
    members = [{"full_name": f"M{i}", "type": "rep", "state": "CA", "party": "D", "url": ""} for i in range(10)]
    seen = []
    def stop(): return len(seen) >= 4
    def read(m, *a): seen.append(m["full_name"]); return [], "no_site", ""
    old = vs.read_member; vs.read_member = read
    try:
        _, stats, cover = vs.collect(members, None, {}, set(), "2026-11-08", stop=stop)
        assert stats["members"] == 4 and [c["member"] for c in cover] == ["M0", "M1", "M2", "M3"]
    finally: vs.read_member = old
