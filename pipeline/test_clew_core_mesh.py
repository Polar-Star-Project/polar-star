"""clew_core ids / crosswalk / ftm, moved from constellation-property (cprop) with their tests; Polar Star's runner does
not need pytest, so expected errors are checked with a small helper."""

from clew_core.crosswalk import Crosswalk
from clew_core.ftm import cluster_to_entity, ownership
from clew_core.ids import InvalidId, gid, try_gid


def _raises(exc, fn):
    try: fn()
    except exc: return
    raise AssertionError(f"{exc.__name__} not raised")


# --- ids -----------------------------------------------------------------
def test_npi_luhn():
    assert gid("npi", "1234567893") == "npi:1234567893"   # CMS-published valid example
    _raises(InvalidId, lambda: gid("npi", "1234567890"))


def test_ein_ccn_license_normalization():
    assert gid("ein", "94-1156365") == "ein:941156365"
    assert gid("ccn", "50001") == "ccn:050001"            # leading zero restored
    assert gid("ca_license", "000230000123") == gid("ca_license", "230000123")
    _raises(InvalidId, lambda: gid("ein", "000000000"))


def test_apn_scoped_by_county():
    assert gid("apn", "123-45-678", county="06085") != gid("apn", "123-45-678", county="06075")


def test_invalid_returns_none_and_never_links():
    cw = Crosswalk()
    assert try_gid("npi", "bad") is None
    assert cw.add(try_gid("npi", "bad"), gid("ein", "941156365"), "same_record", "s", "b") is None
    assert cw.clusters() == []


# --- crosswalk -----------------------------------------------------------
def hospital_chain(cw):
    # 990 Schedule H row: EIN + state license
    cw.add(gid("ein", "941156365"), gid("ca_license", "230000123"), "same_record", "irs990:x", "Sched H Part V A")
    # CDPH facility row: license + CCN + NPI
    cw.add(gid("ca_license", "230000123"), gid("ccn", "050001"), "same_record", "cdph:x", "CDPH row")
    cw.add(gid("ca_license", "230000123"), gid("npi", "1234567893"), "same_record", "cdph:x", "CDPH row")
    # CMS enrollment row: CCN + PAC
    cw.add(gid("ccn", "050001"), gid("pac", "1234567890"), "same_record", "cms:x", "Hospital Enrollments row")


def test_chain_resolves_without_name_matching():
    cw = Crosswalk()
    hospital_chain(cw)
    c = cw.resolve("pac:1234567890")
    assert c["status"] == "ok"
    assert "ein:941156365" in c["ids"] and "npi:1234567893" in c["ids"]
    assert all(l["method"] == "same_record" for l in c["links"])


def test_conflict_quarantines_cluster():
    cw = Crosswalk()
    hospital_chain(cw)
    # a bad link drags a second EIN into the cluster
    cw.add(gid("ein", "770000001"), gid("ccn", "050001"), "reviewed_match", "review:1", "name match", "T3", reviewer="ian")
    c = cw.resolve("ccn:050001")
    assert c["status"] == "conflict" and len(c["conflicts"]["ein"]) == 2
    _raises(ValueError, lambda: cluster_to_entity(c, ["Example Hospital"]))


def test_review_requires_reviewer_and_same_record_requires_t1():
    cw = Crosswalk()
    _raises(ValueError, lambda: cw.add(gid("ein", "941156365"), gid("ccn", "050001"), "reviewed_match", "s", "b"))
    _raises(ValueError, lambda: cw.add(gid("ein", "941156365"), gid("ccn", "050001"), "same_record", "s", "b", tier="T2"))


def test_multiple_npis_are_not_a_conflict():
    cw = Crosswalk()
    cw.add(gid("ccn", "050001"), gid("npi", "1234567893"), "same_record", "s", "b")
    cw.add(gid("ccn", "050001"), gid("npi", "1245319599"), "same_record", "s", "b")
    assert cw.resolve("ccn:050001")["status"] == "ok"


# --- ftm export ----------------------------------------------------------
def test_ftm_export_carries_ids_and_provenance():
    cw = Crosswalk()
    hospital_chain(cw)
    e = cluster_to_entity(cw.resolve("ein:941156365"), ["EXAMPLE HOSPITAL"],
                          sources=[{"url": "https://example.gov/x", "publisher": "CDPH",
                                    "retrieved_at": "2026-11-01"}])
    p = e["properties"]
    assert e["schema"] == "Organization"
    assert p["taxNumber"] == ["941156365"] and p["npiCode"] == ["1234567893"]
    assert p["licenseNumber"] == ["230000123"] and p["sourceUrl"] == ["https://example.gov/x"]


def test_ownership_edge():
    o = ownership("cst-a", "cst-b", {"url": "https://data.cms.gov/x", "retrieved_at": "2026-11-01"}, "100", "Owner")
    assert o["schema"] == "Ownership" and o["properties"]["asset"] == ["cst-b"]
