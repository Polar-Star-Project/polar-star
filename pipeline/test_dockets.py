"""dockets.py: finds each case once, keeps what it found, stays inside CourtListener's request limits."""
from dockets import run, find_docket, newest_entry

ROWS = [{"id": "a", "court": "ilnd", "docket_number": "1:25-cv-01285"}, {"id": "b", "court": "mad", "docket_number": "1:25-cv-12456"}]


def fake(calls):
    def g(url):
        calls.append(url)
        if "dockets/?" in url and "ilnd" in url: return {"results": [{"id": 11, "absolute_url": "/docket/11/us-v-illinois/", "date_last_filing": "2026-10-20"}]}
        if "dockets/?" in url: return {"results": []}
        if "search/?" in url: return {"results": [{"docket_id": 22, "docketNumber": "25-cv-12456", "docket_absolute_url": "/docket/22/us-v-boston/", "dateLastFiling": "2026-07-23"}]}
        if "docket-entries/" in url and "docket=11" in url: return {"results": [{"date_filed": "2026-10-20", "description": "ORDER  setting argument", "recap_documents": [{"filepath_local": "recap/gov.uscourts.ilnd.1/x.pdf"}]}]}
        if "docket-entries/" in url: return None                     # not allowed for this account
        if "dockets/11/" in url: return {"id": 11, "date_last_filing": "2026-10-25"}
        return None
    return g


def test_first_run_finds_dockets_and_entries():
    calls = []; out, used = run(ROWS, {}, fake(calls), "2026-10-26")
    a, b = out
    assert a["cl_id"] == "11" and a["cl_url"] == "https://www.courtlistener.com/docket/11/us-v-illinois/" and a["last_filing"] == "2026-10-20"
    assert a["entry_date"] == "2026-10-20" and a["entry_text"] == "ORDER setting argument" and a["entry_doc"].startswith("https://storage.courtlistener.com/recap/")
    assert b["cl_id"] == "22" and b["last_filing"] == "2026-07-23" and b["entry_date"] == ""     # found through search; entries not readable
    assert used == len(calls) == 5


def test_next_run_reuses_the_id_and_respects_the_budget():
    prev = {o["id"]: o for o in run(ROWS, {}, fake([]), "2026-10-26")[0]}
    calls = []; out, used = run(ROWS, prev, fake(calls), "2026-11-02", budget=1)
    assert used == 1 and calls == ["https://www.courtlistener.com/api/rest/v4/dockets/11/"]
    assert out[0]["last_filing"] == "2026-10-25" and out[1]["cl_id"] == "22" and out[1]["checked"] == "2026-10-26"   # kept, not lost


def test_a_changed_hand_entry_is_looked_up_again():
    prev = {o["id"]: o for o in run(ROWS, {}, fake([]), "2026-10-26")[0]}
    rows = [{**ROWS[0], "docket_number": "1:25-cv-09999"}, ROWS[1]]
    calls = []; out, _ = run(rows, prev, fake(calls), "2026-11-02")
    assert any("1%3A25-cv-09999" in c for c in calls)


# --- automatic status from the docket (2026-11-06) -------------------------------------------------------------------
from dockets import classify, decide, entries_since


def test_court_actions_are_recognised_by_how_the_entry_begins():
    court = ["FINAL JUDGMENT dismissing the action without prejudice; the Clerk of Court shall mark this matter as CLOSED.",
             "CLERK'S JUDGMENT: that judgment is entered in favor of Defendants.", "OPINION filed. Signed by Judge Georgette Castner on 9/4/2026.",
             "ORDER granting 12 Motion for Preliminary Injunction.", "MEMORANDUM AND ORDER: the motion to dismiss is DENIED.",
             "NOTICE OF APPEAL to the 9th Circuit by Gavin Newsom.", "MANDATE of USCA as to 45 Notice of Appeal.",
             "(Text-Only) ORDER: the case is stayed pending appeal.", "Joint STIPULATION of Dismissal by all parties"]
    other = ["NOTICE of Appeal Due letter sent to counsel of record regarding notice of appeal 91",
             "Notice of Appearance or Withdrawal of Counsel: for attorney Brandon David Neuman",
             "STATUS REPORT Joint Status Report on Stipulation Regarding Motion to Clarify Injunction by State of California.",
             "TRANSCRIPT of Sentencing Hearing as to Hannah C Dugan held on July 8, 2026", "ORDER granting Motion for Extension of Time to file answer",
             "SCHEDULING ORDER: status conference set for 11/20/2026", "MOTION to Dismiss for Lack of Jurisdiction filed by the State",
             "(Text-Only) NOTICE to USCA of subsequent filing in a civil case, Re: Notice of Withdrawal as Attorney 83",
             "ORDER setting argument", "REPLY to Response to Motion re 7 MOTION to Dismiss"]
    assert [classify(t) for t in court] == ["court"] * len(court), [t for t in court if classify(t) != "court"]
    assert [classify(t) for t in other] == ["other"] * len(other), [t for t in other if classify(t) != "other"]
    assert classify("") == classify("   ") == "unreadable"


def test_the_newest_court_action_wins_and_the_walk_stops_at_unreadable_text():
    E = [["2026-09-01", "ORDER granting Motion to Dismiss", "https://x/1"], ["2026-09-05", "NOTICE of Appearance by A", "https://x/2"],
         ["2026-09-10", "NOTICE OF APPEAL by State", "https://x/3"], ["2026-09-12", "TRANSCRIPT of hearing", "https://x/4"]]
    assert decide(E, "2026-08-01") == (E[2], "2026-09-12")
    assert decide(E[:1] + [["2026-09-03", "", "https://x/9"]] + E[1:], "2026-08-01") == (E[0], "2026-09-01")   # nothing past the gap counts
    assert decide([["2026-09-01", "ORDER dismissing the case", ""]], "2026-08-01") == (None, "")                # a court action needs a link
    assert decide([E[1]], "2026-08-01") == (None, "2026-09-05")


def test_entries_since_reads_back_to_the_status_and_gives_up_past_the_page_limit():
    page = {"results": [{"date_filed": "2026-10-20", "description": "ORDER dismissing the case", "entry_number": 40, "recap_documents": []},
                        {"date_filed": "2026-10-01", "description": "", "entry_number": 39, "recap_documents": [{"description": "Motion to Dismiss"}]},
                        {"date_filed": "2026-09-01", "description": "old", "entry_number": 30, "recap_documents": []}], "next": None}
    got = entries_since(11, "2026-09-15", lambda u: page, "https://www.courtlistener.com/docket/11/x/")
    assert got == [["2026-10-01", "Motion to Dismiss", "https://www.courtlistener.com/docket/11/x/#entry-39"],
                   ["2026-10-20", "ORDER dismissing the case", "https://www.courtlistener.com/docket/11/x/#entry-40"]]
    endless = {"results": [{"date_filed": "2026-10-20", "description": "x", "entry_number": 1}], "next": "https://next"}
    assert entries_since(11, "2026-01-01", lambda u: endless) is None
    assert entries_since(11, "2026-01-01", lambda u: None) is None


def test_run_records_the_court_action_and_how_far_it_looked():
    def g(url):
        if "dockets/?" in url: return {"results": [{"id": 11, "absolute_url": "/docket/11/x/", "date_last_filing": "2026-10-20"}]}
        if "docket-entries/" in url: return {"results": [
            {"date_filed": "2026-10-20", "description": "NOTICE of Appearance by B", "entry_number": 41},
            {"date_filed": "2026-10-10", "description": "MEMORANDUM OPINION granting summary judgment", "entry_number": 40,
             "recap_documents": [{"filepath_local": "recap/gov.x/40.pdf"}]},
            {"date_filed": "2026-08-01", "description": "old"}], "next": None}
        return None
    out, _ = run([ROWS[0]], {}, g, "2026-10-26", status={"a": "2026-09-01"})
    o = out[0]
    assert (o["auto_date"], o["auto_url"], o["reviewed_auto"]) == ("2026-10-10", "https://storage.courtlistener.com/recap/gov.x/40.pdf", "2026-10-20")
    assert o["auto_text"].startswith("MEMORANDUM OPINION")
