"""export_contract.py: only payees with a UEI are exported, keyed by it; names never key anything."""
import json
import export_contract as ec
from other_agencies import uei_from, payee_rows


def test_payees_export_by_uei_and_rows_without_one_are_counted(tmp):
    ref, out = tmp / "ref", tmp / "out"; ref.mkdir()
    (ref / "other_money_payees.csv").write_text("agency|program|recipient|musd|uei\nHHS|children_grants|SOUTHWEST KEY PROGRAMS INC|5755.0|FPN9K4TA97H7\n"
                                               "HHS|children_grants|SOME CHARITY|12.0|\n", encoding="utf-8")
    (ref / "ice_payees_all.csv").write_text("recipient|musd|uei\nGEO GROUP INC|900.0|ABCDEFGHJKL1\n", encoding="utf-8")
    (ref / "other_money_meta.json").write_text(json.dumps({"from": "2021-10-01", "to": "2026-09-30", "read": "2026-11-10"}), encoding="utf-8")
    s = ec.build(ref, out)
    assert (s["entities"], s["claims"], s["payee_rows_without_uei"]) == (2, 2, 1)
    ents = [json.loads(l) for l in (out / "entities.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["global_id"] for e in ents] == ["uei:ABCDEFGHJKL1", "uei:FPN9K4TA97H7"]
    c = [json.loads(l) for l in (out / "claims.jsonl").read_text(encoding="utf-8").splitlines()]
    assert c[0]["object"] == "program:HHS/children_grants" and c[0]["window"]["from"] == "2021-10-01" and c[1]["object"] == "program:ICE/contracts"


def test_uei_is_read_from_the_recipient_row_and_validated():
    assert uei_from({"uei": "fpn9k4ta97h7"}) == "FPN9K4TA97H7"
    assert uei_from({"uei": None, "code": "FPN9K4TA97H7"}) == "FPN9K4TA97H7"
    assert uei_from({"uei": "123456789", "code": "DUNS12345"}) == ""                 # old DUNS, not a UEI
    rows = payee_rows("HHS", "children_grants", [("A INC", 2e6), ("B INC", 4e5)], {"A INC": "FPN9K4TA97H7"})
    assert rows == [{"agency": "HHS", "program": "children_grants", "recipient": "A INC", "musd": 2.0, "uei": "FPN9K4TA97H7"}]
