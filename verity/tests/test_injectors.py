import pytest
from bs4 import BeautifulSoup

from eval.inject import (
    strip_alt,
    detach_label,
    reduce_contrast,
    contrast_over_image,
    keyboard_trap,
    positive_tabindex,
    outline_none,
)

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


# --- B3.4: contrast_over_image ---------------------------------------------

def test_contrast_over_image_injector():
    clean_html = '<p id="target" style="font-size: 16px;">Hello</p>'

    injected = contrast_over_image.inject(clean_html, selector="#target")
    soup = BeautifulSoup(injected, 'html.parser')
    p = soup.find('p')
    assert "background-image" in p['style'], "A background image must be applied"
    assert "data:image/png;base64," in p['style'], "Image must be inlined, not fetched"
    assert "font-size: 16px" in p['style'], "Original style must be preserved"
    assert p['data-verity-original-style-coi'] == "font-size: 16px;"

    reverted = contrast_over_image.revert(injected, selector="#target")
    rev_p = BeautifulSoup(reverted, 'html.parser').find('p')
    assert rev_p['style'] == "font-size: 16px;"
    assert not rev_p.has_attr('data-verity-original-style-coi')


def test_contrast_over_image_on_element_without_style():
    clean_html = '<p id="target">Hello</p>'

    injected = contrast_over_image.inject(clean_html, selector="#target")
    p = BeautifulSoup(injected, 'html.parser').find('p')
    assert p.has_attr('style')
    assert p['data-verity-original-style-coi'] == "VERITY_NO_STYLE"

    reverted = contrast_over_image.revert(injected, selector="#target")
    rev_p = BeautifulSoup(reverted, 'html.parser').find('p')
    assert not rev_p.has_attr('style'), "style must be removed, not left empty"
    assert not rev_p.has_attr('data-verity-original-style-coi')


def test_contrast_over_image_uses_its_own_marker_attribute():
    """
    Both this and reduce_contrast write to `style`. If they shared a marker,
    one injector's revert would silently undo the other's — showing up as a
    corpus case that quietly lost its defect.
    """
    clean = '<p id="t">Hi</p>'
    coi = contrast_over_image.inject(clean, "#t")
    # reduce_contrast's revert must not disturb a contrast_over_image case.
    assert reduce_contrast.revert(coi, "#t") == coi


def test_contrast_over_image_touches_only_the_selected_element():
    clean = (
        '<p id="target" class="c" data-x="1">Hello</p>'
        '<p id="other" style="color:#000">Untouched</p>'
    )
    before = _attrs_by_tag(clean)
    after = _attrs_by_tag(contrast_over_image.inject(clean, "#target"))

    assert before.keys() == after.keys()
    target = next(k for k in before if before[k].get("id") == "target")
    other = next(k for k in before if before[k].get("id") == "other")

    assert after[other] == before[other], "non-selected element must be untouched"
    assert set(after[target]) - set(before[target]) == {
        "style",
        "data-verity-original-style-coi",
    }
    assert after[target]["class"] == before[target]["class"]


def test_contrast_over_image_is_idempotent_under_revert():
    clean = '<p id="t" style="font-size:16px">Hi</p>'
    once = contrast_over_image.inject(clean, "#t")
    twice = contrast_over_image.inject(contrast_over_image.revert(once, "#t"), "#t")
    assert once == twice


# --- B4.3: keyboard_trap ----------------------------------------------------

def test_keyboard_trap_injector():
    clean_html = '<button id="target">Go</button>'

    injected = keyboard_trap.inject(clean_html, selector="#target")
    btn = BeautifulSoup(injected, 'html.parser').find('button')
    assert "Tab" in btn['onkeydown'], "Tab must be intercepted"
    assert "preventDefault" in btn['onkeydown']
    assert btn['data-verity-original-onkeydown-trap'] == "VERITY_NO_ONKEYDOWN"

    reverted = keyboard_trap.revert(injected, selector="#target")
    rev = BeautifulSoup(reverted, 'html.parser').find('button')
    assert not rev.has_attr('onkeydown')
    assert not rev.has_attr('data-verity-original-onkeydown-trap')


def test_keyboard_trap_makes_a_non_focusable_element_focusable_then_undoes_it():
    """An element that cannot receive focus cannot be trapped."""
    clean_html = '<div id="target">Panel</div>'

    injected = keyboard_trap.inject(clean_html, selector="#target")
    div = BeautifulSoup(injected, 'html.parser').find('div')
    assert div['tabindex'] == "0"

    reverted = keyboard_trap.revert(injected, selector="#target")
    rev = BeautifulSoup(reverted, 'html.parser').find('div')
    assert not rev.has_attr('tabindex'), "added tabindex must be removed again"
    assert not rev.has_attr('data-verity-added-tabindex-trap')


def test_keyboard_trap_preserves_an_existing_handler_and_tabindex():
    clean_html = '<button id="t" onkeydown="log()" tabindex="0">Go</button>'

    injected = keyboard_trap.inject(clean_html, selector="#t")
    btn = BeautifulSoup(injected, 'html.parser').find('button')
    assert "log()" in btn['onkeydown']

    reverted = keyboard_trap.revert(injected, selector="#t")
    rev = BeautifulSoup(reverted, 'html.parser').find('button')
    assert rev['onkeydown'] == "log()"
    assert rev['tabindex'] == "0", "a pre-existing tabindex must survive"


def test_keyboard_trap_is_idempotent_under_revert():
    clean = '<button id="t">Go</button>'
    once = keyboard_trap.inject(clean, "#t")
    twice = keyboard_trap.inject(keyboard_trap.revert(once, "#t"), "#t")
    assert once == twice


# --- B4.3: positive_tabindex ------------------------------------------------

def test_positive_tabindex_injector():
    clean_html = '<a id="target" href="#">Link</a>'

    injected = positive_tabindex.inject(clean_html, selector="#target")
    a = BeautifulSoup(injected, 'html.parser').find('a')
    assert int(a['tabindex']) > 0, "must be positive to disrupt document order"
    assert a['data-verity-original-tabindex-pos'] == "VERITY_NO_TABINDEX"

    reverted = positive_tabindex.revert(injected, selector="#target")
    rev = BeautifulSoup(reverted, 'html.parser').find('a')
    assert not rev.has_attr('tabindex')
    assert not rev.has_attr('data-verity-original-tabindex-pos')


def test_positive_tabindex_restores_an_existing_value():
    clean_html = '<a id="t" href="#" tabindex="-1">Link</a>'

    injected = positive_tabindex.inject(clean_html, selector="#t")
    assert int(BeautifulSoup(injected, 'html.parser').find('a')['tabindex']) > 0

    reverted = positive_tabindex.revert(injected, selector="#t")
    assert BeautifulSoup(reverted, 'html.parser').find('a')['tabindex'] == "-1"


def test_positive_tabindex_is_idempotent_under_revert():
    clean = '<a id="t" href="#">Link</a>'
    once = positive_tabindex.inject(clean, "#t")
    twice = positive_tabindex.inject(positive_tabindex.revert(once, "#t"), "#t")
    assert once == twice


# --- B4.3: outline_none -----------------------------------------------------

def test_outline_none_injector():
    clean_html = '<button id="target" style="color: blue;">Go</button>'

    injected = outline_none.inject(clean_html, selector="#target")
    btn = BeautifulSoup(injected, 'html.parser').find('button')
    assert "outline: none" in btn['style']
    assert "box-shadow: none" in btn['style'], "focus rings are often box-shadows"
    assert "color: blue" in btn['style'], "original style must be preserved"
    assert btn['data-verity-original-style-outline'] == "color: blue;"

    reverted = outline_none.revert(injected, selector="#target")
    rev = BeautifulSoup(reverted, 'html.parser').find('button')
    assert rev['style'] == "color: blue;"
    assert not rev.has_attr('data-verity-original-style-outline')


def test_outline_none_adds_no_replacement_indicator():
    """
    Removing the outline is only a failure when nothing replaces it. This
    injector must not accidentally draw a ring of its own, or the case stops
    testing SC 2.4.7.
    """
    injected = outline_none.inject('<button id="t">Go</button>', "#t")
    style = BeautifulSoup(injected, 'html.parser').find('button')['style']
    assert "outline: none" in style
    assert "outline:" not in style.replace("outline: none", "")
    assert "border" not in style


def test_outline_none_is_idempotent_under_revert():
    clean = '<button id="t" style="color:red">Go</button>'
    once = outline_none.inject(clean, "#t")
    twice = outline_none.inject(outline_none.revert(once, "#t"), "#t")
    assert once == twice


# --- markers must not collide ----------------------------------------------

def test_style_writing_injectors_use_distinct_markers():
    """
    reduce_contrast, contrast_over_image and outline_none all write to
    `style`. A shared marker would let one injector's revert silently undo
    another's, producing a corpus case that quietly lost its defect.
    """
    clean = '<p id="t">Hi</p>'
    cases = {
        "reduce_contrast": reduce_contrast.inject(clean, "#t"),
        "contrast_over_image": contrast_over_image.inject(clean, "#t"),
        "outline_none": outline_none.inject(clean, "#t"),
    }
    modules = {
        "reduce_contrast": reduce_contrast,
        "contrast_over_image": contrast_over_image,
        "outline_none": outline_none,
    }

    for owner, injected in cases.items():
        for other_name, other in modules.items():
            if other_name == owner:
                continue
            assert other.revert(injected, "#t") == injected, (
                f"{other_name}.revert must not disturb a {owner} case"
            )
