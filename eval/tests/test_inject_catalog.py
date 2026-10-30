"""
A14.3 — the complete injector catalog and prevalence weighting.

Proves the catalog is complete (~15 injectors across the families), the WebAIM
top defects are present with their prevalence, the agent-relevant defects are
carried but excluded from the prevalence-weighted mix, and the new
missing-document-language injector round-trips.
"""

from eval.inject import catalog
from eval.inject.catalog import CATALOG, prevalence_weighted, prevalence_weights, summary


def test_catalog_is_complete_and_spans_families():
    s = summary()
    assert s["injectors"] >= 15
    # Every defect family the benchmark and WebAIM care about is represented.
    assert set(s["families"]) >= {"name", "contrast", "keyboard", "focus", "structure", "language"}


def test_webaim_top_defects_present_with_prevalence():
    for inj in ("low_contrast", "missing_alt", "missing_form_label", "empty_link", "empty_button"):
        assert inj in CATALOG and CATALOG[inj].prevalence is not None
    # Ordered most-common first, matching WebAIM Million 2026.
    ranked = [s.id for s in prevalence_weighted()]
    assert ranked[0] == "low_contrast"           # 83.9%
    assert ranked.index("missing_alt") < ranked.index("empty_button")  # 53.1% > 30.6%


def test_prevalence_weights_normalise_and_exclude_unscored():
    w = prevalence_weights()
    assert abs(sum(w.values()) - 1.0) < 1e-9
    # Agent-relevant, WebAIM-unscored defects are not in the weighted mix.
    assert "div_button" not in w and "keyboard_trap" not in w
    assert CATALOG["div_button"].prevalence is None


def test_every_spec_has_an_sc_and_callables():
    for spec in CATALOG.values():
        assert spec.sc and spec.sc_name and spec.level in ("A", "AA", "AAA")
        assert callable(spec._inject) and callable(spec._revert)


def test_missing_document_language_injects_and_reverts():
    from bs4 import BeautifulSoup

    html = '<html lang="en"><body><p>hi</p></body></html>'
    broken = CATALOG["missing_document_language"].inject(html)
    assert BeautifulSoup(broken, "html.parser").select_one("html").get("lang") is None
    restored = CATALOG["missing_document_language"].revert(broken)
    assert BeautifulSoup(restored, "html.parser").select_one("html").get("lang") == "en"


def test_empty_link_is_strip_name_scoped_to_links():
    html = '<a href="/x">Products</a><button>Go</button>'
    broken = CATALOG["empty_link"].inject(html)
    # The link lost its text; the button (a different selector) did not.
    assert ">Products<" not in broken
    assert ">Go<" in broken
