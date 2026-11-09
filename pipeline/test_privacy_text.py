"""The page's own words about private people must match what it does: donors are counted, never named."""
from pathlib import Path

T = (Path(__file__).resolve().parent.parent / "site" / "template.html").read_text(encoding="utf-8")


def test_no_text_says_donors_are_named():
    for phrase in ("listed by name", "are listed as the Federal Election Commission publishes them", "aparecen con su nombre",
                   "Each gift links", "Cada donación enlaza", "aparecen tal como los publica la Comisión"):
        assert phrase not in T, phrase


def test_privacy_lines_say_counted_never_named():
    assert "counted, never named" in T and "se cuentan, nunca se nombran" in T


def test_search_hint_never_asks_for_a_name():
    assert 'ph:"Name' not in T and 'ph:"Nombre' not in T


def test_every_tab_is_a_linkable_view():
    """A tab missing from VIEWS opens For families when linked, reloaded or shared."""
    import re
    views = set(re.findall(r'"(\w+)"', re.search(r"const VIEWS = \[([^\]]*)\]", T).group(1)))
    tabs = set(re.findall(r'id="tab-(\w+)"', T))
    assert tabs <= views, tabs - views


def test_family_text_is_written_into_the_page_before_any_script_runs():
    """A slow phone shows the family steps as the HTML arrives; an empty labelled element there means the prefill broke."""
    import re
    from build_site import prefill_text
    out = prefill_text(T)
    main = out[:out.find("</main>")]
    for key in ("tab_fam", "fam_lead", "fam_1h", "s1", "fam_2h"):
        assert not re.search(r'data-t="%s"[^<>]*></' % key, main), key
    assert "<noscript>" in main and "locator.ice.gov" in main
