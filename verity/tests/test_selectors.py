"""
A6.1 / A7.1 — selector normalisation and the stable finding signature.

The property under test is the whole point of the module: the signature must
NOT change when a class-name hasher or a code formatter rewrites a selector,
and it MUST still change when the element genuinely differs. The failure mode
on either side is expensive — a churning signature invalidates every waiver and
baseline; an over-collapsed one lets a waiver for one finding silently suppress
another.
"""

import pytest

from verity.agents.validator import normalize_selector, generate_finding_signature


# --- stable class names must be kept (the false-drop guard) ----------------

@pytest.mark.parametrize(
    "selector",
    [
        "div.container > button.btn.primary",
        "nav.navbar ul.menu > li.item",
        "div.grid-cols-3.mt-4",          # Tailwind utilities — digits, but stable
        "section.card__title",            # BEM element — __ but a word suffix
        "button.btn--primary",            # BEM modifier — -- but a word suffix
        "#main-content p",
    ],
)
def test_stable_selectors_are_preserved_in_substance(selector):
    """Normalisation must not discard authored, stable classes/ids."""
    out = normalize_selector(selector)
    # Every authored class/id word survives (possibly reordered/lowercased).
    for token in ("container", "btn", "primary", "navbar", "menu", "item",
                  "grid-cols-3", "mt-4", "card__title", "btn--primary",
                  "main-content"):
        if token in selector:
            assert token in out, f"stable token '{token}' was dropped: {selector} -> {out}"


# --- generated class names must be neutralised (the churn guard) -----------

def test_css_modules_hash_reduces_to_stem():
    a = normalize_selector("button.Button__a1b2c3")
    b = normalize_selector("button.Button__9f8e7d")
    assert a == b, "a CSS-modules hash must not change identity between builds"
    assert "button" in a


def test_framework_hashes_are_dropped():
    for hashed in ("div.css-1a2b3c", "div.sc-bdVaJa", "div.jsx-1837472", "div.emotion-7x"):
        out = normalize_selector(hashed)
        assert out == "div", f"framework hash should drop to bare tag, got {out}"


def test_bare_hash_class_is_dropped():
    assert normalize_selector("span.a1b2c3d4") == "span"
    assert normalize_selector("span.aB3xK9z") == "span"


def test_hashed_id_is_neutralised_but_element_still_distinct_by_structure():
    a = normalize_selector("div#radix-a1b2 > button")
    b = normalize_selector("div#radix-9z8y > button")
    assert a == b, "a hashed id must not churn the signature"


# --- formatter churn: class order and whitespace ---------------------------

def test_class_order_does_not_matter():
    assert normalize_selector("button.b.a.c") == normalize_selector("button.c.a.b")


def test_combinator_spacing_does_not_matter():
    assert normalize_selector("a>b+c~d") == normalize_selector("a > b  +  c ~ d")


def test_state_pseudo_dropped_structural_pseudo_kept():
    assert normalize_selector("button:hover") == "button"
    assert normalize_selector("li:nth-child(2)") == "li:nth-child(2)"


def test_normalisation_is_idempotent():
    once = normalize_selector("DIV.Button__a1b2c3 > LI.b.a:hover:nth-child(3)")
    twice = normalize_selector(once)
    assert once == twice


# --- the signature, end to end ---------------------------------------------

def test_signature_survives_a_class_name_hasher():
    before = generate_finding_signature("1.4.3", "div.container > button.Button__a1b2c3", "color-contrast")
    after = generate_finding_signature("1.4.3", "div.container > button.Button__9f8e7d", "color-contrast")
    assert before == after, "the signature must survive a rebuild that re-hashes class names"


def test_signature_still_distinguishes_genuinely_different_elements():
    one = generate_finding_signature("1.4.3", "div.header > button.cta", "color-contrast")
    two = generate_finding_signature("1.4.3", "div.footer > button.cta", "color-contrast")
    assert one != two


def test_signature_distinguishes_rule_and_criterion():
    base = generate_finding_signature("1.4.3", "button.cta", "color-contrast")
    assert base != generate_finding_signature("1.4.3", "button.cta", "link-in-text-block")
    assert base != generate_finding_signature("1.1.1", "button.cta", "color-contrast")


def test_region_fallback_separates_selectorless_findings():
    # No selector on either, but distinct regions must not collide.
    a = generate_finding_signature("1.4.3", "", "color-contrast", region="name=Submit")
    b = generate_finding_signature("1.4.3", "", "color-contrast", region="name=Cancel")
    assert a != b
    # And with neither selector nor region, they fall together on the sentinel
    # (callers are expected to supply a region when the selector is empty).
    c = generate_finding_signature("1.4.3", "", "color-contrast")
    d = generate_finding_signature("1.4.3", "   ", "color-contrast")
    assert c == d
