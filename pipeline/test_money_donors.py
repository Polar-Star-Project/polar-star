"""Named donors: which reported employers count, what is dropped as a double count, what is kept, and that no address survives."""
import money_donors as m


def test_employer_must_start_with_the_company():
    assert m.company_of("The GEO Group, Inc.") == "GEO" and m.company_of("GEO GROUP") == "GEO" and m.company_of("Geo Secure Services LLC") == "GEO"
    assert m.company_of("CoreCivic") == "CC" and m.company_of("Core Civic Inc") == "CC" and m.company_of("Corrections Corp. of America") == "CC"
    assert m.company_of("Management & Training Corp") == "MTC" and m.company_of("LaSalle Corrections") == "LAS"
    for e in ("GEOLOGY ASSOCIATES", "GEO", "FORMER GEO GROUP", "SELF-EMPLOYED", "RETIRED", "", None, "TRAINING MANAGEMENT CORP"):
        assert m.company_of(e) is None, e


def _r(**k):
    r = {"committee_id": "C1", "memo_code": None, "entity_type": "IND", "contributor_employer": "GEO GROUP", "contributor_name": "DOE, JANE",
         "contribution_receipt_date": "2025-03-01T00:00:00", "contribution_receipt_amount": 500.0, "contributor_street_1": "1 MAIN ST",
         "contributor_city": "BOCA RATON", "contributor_zip": "33431", "contributor_state": "FL", "image_number": "202503019000"}
    r.update(k); return r


def test_conduits_memos_organisations_and_repeats_are_dropped():
    rows = [_r(), _r(), _r(committee_id="C00694323"), _r(memo_code="X"), _r(entity_type="ORG"), _r(contributor_employer="GEOLOGY INC"), _r(contribution_receipt_amount=250.0)]
    k = m.keep(rows)
    assert len(k) == 2 and all(co == "GEO" for co, _ in k)


def test_row_keeps_state_but_no_street_city_or_zip_and_links_the_filing():
    co, r = m.keep([_r(contributor_name="DOE | JANE")])[0]
    out = m.row(co, 2026, r, {"C1": ("H", "R", "SMITH FOR CONGRESS")}, {"C1": "S000001"})
    assert list(out) == m.FIELDS and out["state"] == "FL" and out["name"] == "DOE / JANE" and out["bioguide"] == "S000001"
    assert not any(v in str(out.values()) for v in ("MAIN ST", "BOCA", "33431"))
    assert out["url"].startswith("https://www.fec.gov/data/receipts/?") and "committee_id=C1" in out["url"] and "two_year_transaction_period=2026" in out["url"]
    assert "docquery" not in out["url"]                    # scanned filings print the street address


def test_member_link_only_for_candidate_committees_and_leadership_funds_tied_to_one_person():
    by = {"H1": "A1", "S1": "B1", "H2": "C1"}
    recs = {"CA": {"committee_type": "H", "candidate_ids": ["H1"]}, "CB": {"committee_type": "Q", "designation": "D", "sponsor_candidate_ids": ["S1"]},
            "CC": {"committee_type": "Y", "candidate_ids": ["H1"]}, "CD": {"committee_type": "H", "candidate_ids": ["H1", "H2"]}, "CE": {"committee_type": "S", "candidate_ids": ["X9"]}}
    assert m.member_links(recs, by) == {"CA": "A1", "CB": "B1"}


def _d(**k):
    r = {"co": "GEO", "cycle": 2026, "date": "2026-01-02", "name": "DOE, JANE", "employer": "GEO GROUP", "occupation": "OFFICER", "state": "FL", "usd": 250.0,
         "committee_id": "C1", "committee": "X FOR CONGRESS", "ctype": "H", "party": "R", "bioguide": "A1", "url": "https://www.fec.gov/data/receipts/?x"}
    r.update(k); return r


def test_totals_count_people_once_and_name_no_one():
    rows = [_d(), _d(name="DOE, JANE A.", usd=50.0), _d(name="ROE, AL", usd=100.0, committee_id="C00382150", committee="GEO PAC", ctype="Q", bioguide=""),
            _d(co="CC", name="DOE, JANE", usd=1000.0)]           # same name at another company: a different donor
    agg, sm = m.totals(rows)
    assert sm["total"] == 1400.0 and sm["gifts"] == 4 and sm["people"] == 3 and sm["small"] == [2, 150.0]
    assert sm["by_co"] == {"GEO": [400.0, 3, 2], "CC": [1000.0, 1, 1]} and sm["by_year"] == {"2026": 1400.0}
    assert sm["by_member"] == {"A1": {"all": [1300.0, 3, 2], "GEO": [300.0, 2, 1], "CC": [1000.0, 1, 1]}}
    c1 = next(r for r in agg if r["co"] == "GEO" and r["committee_id"] == "C1")
    assert (c1["usd"], c1["gifts"], c1["donors"]) == (300.0, 2, 1)
    assert all(list(r) == m.TOTAL_FIELDS for r in agg)
    text = repr(agg) + repr(sm)
    assert not any(x in text for x in ("DOE", "ROE", "JANE", "OFFICER", "FL"))


def test_two_middle_initials_under_one_name_are_two_people():
    k = m.person_keys([_d(name="DOE, JANE A"), _d(name="DOE, JANE B"), _d(name="DOE, JANE")])
    assert len(set(k[:2])) == 2


def test_restricted_folder_must_exist_and_sit_outside_the_repository(tmp_path):
    assert m.restricted_dir(str(tmp_path)) == tmp_path.resolve()
    for bad in (str(m.ROOT), str(m.ROOT / "data"), str(tmp_path / "missing")):
        try: m.restricted_dir(bad); assert False, bad
        except SystemExit: pass


def _write(tmp, rows):
    import json
    agg, sm = m.totals(rows)
    (tmp / "fec_donor_totals.csv").write_text("|".join(m.TOTAL_FIELDS) + "\n" + "".join("|".join(str(r[k]) for k in m.TOTAL_FIELDS) + "\n" for r in agg), encoding="utf-8")
    (tmp / "fec_donor_totals_meta.json").write_text(json.dumps({"read": "2026-10-10", "cycles": [2024, 2026], **sm}), encoding="utf-8")
    return sm


def test_build_marks_the_company_pac_and_checks_the_total(tmp_path):
    import build_site as b, json
    _write(tmp_path, [_d(), _d(committee_id="C00382150", committee="GEO PAC", ctype="Q", usd=100.0, bioguide="")])
    out = b.donors_section(tmp_path)
    assert sorted(r[2] for r in out["rows"]) == ["H", "O"] and out["total"] == 350.0 and out["people"] == 1
    mf = tmp_path / "fec_donor_totals_meta.json"; meta = json.loads(mf.read_text()); meta["total"] = 999.0; mf.write_text(json.dumps(meta))
    try: b.donors_section(tmp_path); assert False, "should refuse a total that does not add up"
    except ValueError: pass
    _write(tmp_path, [_d()]); f = tmp_path / "fec_donor_totals.csv"
    f.write_text(f.read_text().replace("donors\n", "donors|name\n", 1).replace("\n", "|DOE\n").replace("|name|DOE", "|name"))
    try: b.donors_section(tmp_path); assert False, "should refuse a file with a name column"
    except ValueError: pass
