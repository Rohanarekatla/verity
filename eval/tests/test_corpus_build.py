"""
Fast, offline tests for the corpus harness (A2.3).

These exercise the structural half of build.py without a network fetch or
a browser: manifest parsing, single-element targeting, and the verify()
collateral check. The rendered verification pass (verify.py) is covered
separately and is too slow to run here.
"""

from bs4 import BeautifulSoup

from eval.corpus import build


def test_manifest_parses_every_source():
    sources = build.read_sources()
    assert len(sources) >= 25, "manifest shrank unexpectedly"
    for s in sources:
        assert s["id"] and s["url"].startswith("http")
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids)), "duplicate source ids"


def test_verify_accepts_a_clean_single_element_injection():
    clean = build.normalise('<img alt="A logo" src="x.png">')
    marked = BeautifulSoup(clean, "html.parser")
    marked.find("img")[build.MARKER] = "1"
    injected_soup = BeautifulSoup(
        build.strip_alt.inject(str(marked), f"[{build.MARKER}]"), "html.parser"
    )
    for el in injected_soup.select(f"[{build.MARKER}]"):
        del el[build.MARKER]
    injected = build.normalise(str(injected_soup))

    result = build.verify(clean, injected, build.INJECTIONS[0])
    assert result["ok"], result
    assert result["elements_changed"] == 1


def test_verify_rejects_a_no_op_injection():
    """An injection that changes nothing is not a defect and must be rejected."""
    clean = build.normalise("<p>text</p>")
    result = build.verify(clean, clean, build.INJECTIONS[0])
    assert not result["ok"]
    assert "no change" in result["reason"]


def test_targets_exclude_non_injectable_elements():
    soup = BeautifulSoup(
        '<img src="a.png"><img alt="has alt" src="b.png">'
        '<label>no for</label><label for="x">has for</label>'
        "<p></p><p>visible text</p>",
        "html.parser",
    )
    by_name = {i.name: i for i in build.INJECTIONS}

    # strip_alt only targets images that actually have alt.
    assert len(by_name["strip_alt"].targets(soup)) == 1
    # detach_label only targets labels with a `for`.
    assert len(by_name["detach_label"].targets(soup)) == 1
    # reduce_contrast skips empty paragraphs.
    assert len(by_name["reduce_contrast"].targets(soup)) == 1
