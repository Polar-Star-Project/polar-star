"""people_index: one card per named person. Records join by Bioguide id or by first and last name, and say so when the join is by name only."""
from build_site import people_index, dispute_people

def mem(bg, name, st, votes="YY", current=True):
    return [bg, name, "H", "R", st, 1, "", [], votes, 0, 0, current, "", 0, 0]

def site(**kw):
    s = {"pol": {"m": [mem("A1", "Mike Rogers", "AL"), mem("B2", "Mike Rogers", "MI"), mem("C3", 'Jesús "Chuy" García', "IL"), mem("D4", "Mikie Sherrill", "NJ", "NN", False)],
                 "gov": [["NJ", "Mikie Sherrill", "D", "2026-01-20", "https://nj.gov", 0, [], False, [], 0, ""]],
                 "local": [["FAC1", "County Jail", "TX", "John Doe", "Sheriff", "Doe County Sheriff's Office", "https://x", "2026-10-01"]],
                 "rev": [["GEO", "Jane Roe", "Chief of Staff, Rep. Jesús García", "SOME FIRM", 2024, 2025]]}}
    s.update(kw); return s

def test_two_members_with_one_name_stay_apart_and_others_do_not_join_them():
    x = people_index(site(local=None, disputes=[[ "2026-01-01", "AL", "Town", 0,0,0,0,0,0,0,0,0,0,0,0,0, [["Mike Rogers", "Mayor", "alcalde"]], [], False, [], []]]), {})
    assert "A1" in x["p"] and "B2" in x["p"] and x["p"]["A1"]["r"] == [["m", "A1"]]
    assert x["nk"]["Mike Rogers"] == "mike rogers" and x["p"]["mike rogers"]["r"][0][0] == "d"

def test_nickname_member_joins_by_first_and_last_name():
    x = people_index(site(disputes=[["2026-01-01", "IL", "Chicago", 0,0,0,0,0,0,0,0,0,0,0,0,0, [["Jesús García", "Rep.", "rep."]], [], False, [], []]]), {})
    assert x["nk"]["Jesús García"] == "C3" and [r[0] for r in x["p"]["C3"]["r"]] == ["m", "d"] and "x" not in x["p"]["C3"]

def test_member_who_became_governor_is_one_card_without_a_warning():
    e = people_index(site(), {})["p"]["D4"]
    assert [r[0] for r in e["r"]] == ["m", "g"] and "x" not in e and e["v"][0] == "ag"

def test_287g_signer_only_when_signed_by_the_agency():
    st = {"TX": [["Doe PD", "", "T", "2025-06-18", "", "", "", "a.pdf", ["John Doe", "Chief", "s"]], ["Roe PD", "", "T", "2025-06-18", "", "", "", "", ["Ann Contact", "Lt", "c"]]]}
    x = people_index(site(), st)
    assert [r[0] for r in x["p"]["john doe"]["r"]] == ["l", "a"] and "ann contact" not in x["p"]
    assert x["p"]["john doe"]["x"] == 1     # a sheriff and an agency signer are different lists: joined by name, so flagged

def test_sheriff_and_signer_in_different_states_are_flagged():
    st = {"FL": [["Doe PD", "", "T", "2025-06-18", "", "", "", "", ["John Doe", "Chief", "s"]]]}
    assert people_index(site(), st)["p"]["john doe"]["x"] == 1

def test_donors_never_get_a_card():
    x = people_index(site(), {})
    assert "dn" not in x and not any(r[0] == "$" for e in x["p"].values() for r in e["r"])     # personal donations are joined to no one

def test_lobbyist_past_post_ties_to_the_member():
    e = people_index(site(firms={"cards": {"SOME FIRM": {"money": [], "former": [["Jane Roe", "Chief of Staff, Rep. Jesús García", []]]}}}), {})["p"]["C3"]
    assert ["fs", [["SOME FIRM", []]]] in e["t"]

def test_dispute_people_unchanged_by_the_shared_tie_code():
    s = site(disputes=[["2026-01-01", "IL", "Chicago", 0,0,0,0,0,0,0,0,0,0,0,0,0, [["Jesús García", "Rep.", "rep."]], [], False, [], []]],
             firms={"cards": {"SOME FIRM": {"money": [], "former": [["Jane Roe", "Chief of Staff, Rep. Jesús García", []]]}}})
    d = dispute_people(s)["Jesús García"]
    assert d["bg"] == "C3" and d["t"] == [["fs", [["SOME FIRM", []]]]]

def test_governor_in_office_when_a_dispute_began_gets_it_on_their_card():
    D = [["2026-03-01", "NJ", "Newark", 0,0,0,0,0,0,0,0,0,0,0,0,0, [], [], False, [], []], ["2025-06-01", "NJ", "Elizabeth", 0,0,0,0,0,0,0,0,0,0,0,0,0, [], [], False, [], []]]
    x = people_index(site(disputes=D, gov_terms={"NJ": [["Phil Murphy", "D", "2018-01-16", "2026-01-20"]]}), {})["p"]
    assert [r[1] for r in x["D4"]["r"] if r[0] == "d"] == ["2026-03-01"] and [r[1] for r in x["phil murphy"]["r"] if r[0] == "d"] == ["2025-06-01"]
