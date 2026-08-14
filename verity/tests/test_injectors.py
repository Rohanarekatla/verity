import pytest
from bs4 import BeautifulSoup

from eval.inject import strip_alt, detach_label, reduce_contrast

def test_strip_alt_injector():
    clean_html = '<img src="logo.png" alt="Company Logo" class="header-img">'
    
    # 1. Test Injection
    injected = strip_alt.inject(clean_html, selector="img")
    soup = BeautifulSoup(injected, 'html.parser')
    img = soup.find('img')
    assert not img.has_attr('alt'), "Alt attribute should be removed"
    assert img['data-verity-original-alt'] == "Company Logo", "Original alt should be backed up"
    
    # 2. Test Reversal
    reverted = strip_alt.revert(injected, selector="img")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_img = rev_soup.find('img')
    assert rev_img['alt'] == "Company Logo", "Alt attribute should be restored"
    assert not rev_img.has_attr('data-verity-original-alt'), "Backup attribute should be cleaned up"


def test_detach_label_injector():
    clean_html = '<label for="email-input">Email</label><input id="email-input">'
    
    # 1. Test Injection
    injected = detach_label.inject(clean_html, selector="label")
    soup = BeautifulSoup(injected, 'html.parser')
    label = soup.find('label')
    assert label['for'] == "verity-broken-id", "For attribute should be mangled"
    assert label['data-verity-original-for'] == "email-input", "Original for attribute should be backed up"
    
    # 2. Test Reversal
    reverted = detach_label.revert(injected, selector="label")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_label = rev_soup.find('label')
    assert rev_label['for'] == "email-input", "For attribute should be restored"
    assert not rev_label.has_attr('data-verity-original-for'), "Backup attribute should be cleaned up"


def test_reduce_contrast_injector():
    clean_html = '<p id="target" style="font-size: 16px;">Hello</p>'
    
    # 1. Test Injection
    injected = reduce_contrast.inject(clean_html, selector="#target")
    soup = BeautifulSoup(injected, 'html.parser')
    p = soup.find('p')
    assert "color: #cccccc !important" in p['style'], "Low contrast style should be injected"
    assert p['data-verity-original-style'] == "font-size: 16px;", "Original style should be backed up"
    
    # 2. Test Reversal
    reverted = reduce_contrast.revert(injected, selector="#target")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_p = rev_soup.find('p')
    assert rev_p['style'] == "font-size: 16px;", "Original style should be completely restored"
    assert not rev_p.has_attr('data-verity-original-style'), "Backup attribute should be cleaned up"
    
def test_reduce_contrast_injector_no_style():
    clean_html = '<p id="target">Hello</p>'
    injected = reduce_contrast.inject(clean_html, selector="#target")
    reverted = reduce_contrast.revert(injected, selector="#target")
    rev_soup = BeautifulSoup(reverted, 'html.parser')
    rev_p = rev_soup.find('p')
    assert not rev_p.has_attr('style'), "Style attribute should be removed if it didn't exist originally"

# --- Injection verification pass (B1.5 acceptance criterion, second half) ---
#
# "Each injector has a unit test asserting the defect was introduced AND that
#  no unintended second defect appeared."
#
# The tests above cover the first half. These cover the second: injecting one
# defect must not silently alter anything else. Ground truth that is quietly
# wrong makes every downstream precision/recall number wrong, and the
# corruption is invisible without an explicit check. Week 14 (A14.2) turns
# this into a corpus-wide verification pass that aborts generation on failure.

def _attrs_by_tag(html: str) -> dict:
    """Every element's attributes, keyed by (tag, index), for collateral diffing."""
    soup = BeautifulSoup(html, "html.parser")
    return {
        (el.name, i): dict(el.attrs)
        for i, el in enumerate(soup.find_all(True))
    }


def test_strip_alt_touches_only_the_alt_attribute():
    clean = (
        '<div class="wrap"><img src="a.png" alt="A" title="t">'
        '<img src="b.png" alt="B"><p id="keep">text</p></div>'
    )
    before, after = _attrs_by_tag(clean), _attrs_by_tag(strip_alt.inject(clean, "img"))

    assert before.keys() == after.keys(), "no elements added or removed"
    for key in before:
        if key[0] == "img":
            continue
        assert before[key] == after[key], f"collateral change on {key}"

    for key in [k for k in before if k[0] == "img"]:
        removed = set(before[key]) - set(after[key])
        added = set(after[key]) - set(before[key])
        assert removed == {"alt"}, f"expected only alt removed, got {removed}"
        assert added == {"data-verity-original-alt"}, f"unexpected additions: {added}"
        # src/title etc. must survive untouched
        for attr in set(before[key]) - {"alt"}:
            assert after[key][attr] == before[key][attr]


def test_detach_label_touches_only_the_for_attribute():
    clean = (
        '<label for="e" class="lbl">Email</label><input id="e" required>'
        '<label class="no-for">Other</label>'
    )
    before, after = _attrs_by_tag(clean), _attrs_by_tag(detach_label.inject(clean, "label"))

    assert before.keys() == after.keys()
    for key in before:
        if key[0] != "label":
            assert before[key] == after[key], f"non-label element changed: {key}"

    # The input keeps its id — the association breaks from the label side only,
    # which is what makes the defect attributable to a single element.
    input_key = next(k for k in before if k[0] == "input")
    assert after[input_key]["id"] == "e"


def test_detach_label_leaves_labels_without_for_untouched():
    """A label with no `for` has nothing to detach; touching it would be a
    second, unintended defect."""
    clean = '<label class="no-for">Other</label>'
    assert detach_label.inject(clean, "label") == clean


def test_reduce_contrast_touches_only_the_style_attribute():
    clean = (
        '<p id="target" class="c" data-x="1">Hello</p>'
        '<p id="other" style="color:#000">Untouched</p>'
    )
    before, after = _attrs_by_tag(clean), _attrs_by_tag(reduce_contrast.inject(clean, "#target"))

    assert before.keys() == after.keys()

    target = next(k for k in before if before[k].get("id") == "target")
    other = next(k for k in before if before[k].get("id") == "other")

    assert after[other] == before[other], "non-selected element must be untouched"
    assert set(after[target]) - set(before[target]) == {"style", "data-verity-original-style"}
    assert after[target]["class"] == before[target]["class"]
    assert after[target]["data-x"] == before[target]["data-x"]


def test_injectors_are_idempotent_under_revert():
    """inject -> revert -> inject must land in the same place. If it doesn't,
    the paired corpus drifts every time it is regenerated."""
    clean = '<p id="t" style="font-size:16px">Hi</p>'
    once = reduce_contrast.inject(clean, "#t")
    twice = reduce_contrast.inject(reduce_contrast.revert(once, "#t"), "#t")
    assert once == twice
