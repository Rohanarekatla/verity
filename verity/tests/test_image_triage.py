"""
A10.3 — image triage: which images are worth OCR, and why the rest are not.

The rules only ever skip work, so their failure mode is lost recall on SC
1.4.5, never a false finding. These pin each rule, the reasons it records,
and the one case where skipping is what prevents a false finding: a CSS
background behind real HTML text, whose crop would OCR that text.
"""

from pathlib import Path

import pytest

from verity.agents.image_triage import classify, inventory_and_triage, triage
from verity.models.schemas import BoundingBox, ImageInventory, ImageNode

REPO = Path(__file__).resolve().parents[2]
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"
FIXTURE = REPO / "data" / "fixtures" / "images.html"


def img(selector="#i", w=320, h=180, **kw) -> ImageNode:
    kw.setdefault("kind", "img")
    kw.setdefault("visible", True)
    return ImageNode(selector=selector, tag="img", box_css=BoundingBox(x=0, y=0, width=w, height=h), **kw)


@pytest.mark.parametrize(
    "node, category",
    [
        (img(alt="Team photo"), "content"),
        (img(), "content"),  # absent alt: still content — absence is not a decorative declaration
        (img(alt=""), "decorative"),
        (img(role="presentation"), "decorative"),
        (img(aria_hidden=True, alt="x"), "decorative"),
        (img(visible=False), "hidden"),
        (img(w=1, h=1), "tiny"),
        (img(alt="Acme logo"), "logo"),
        (img(sources=["https://x.test/assets/site-logo.svg"]), "logo"),
        (img(in_landmark="header", link_href="/", alt="Acme"), "logo"),
        (img(w=24, h=24, in_control=True, alt="Delete"), "icon"),
        (img(kind="svg", w=200, h=100), "not-text"),
        (img(kind="css-background", has_text_content=True, w=600, h=120), "not-text"),
        (img(kind="css-background", w=600, h=60), "content"),
        (img(kind="canvas", w=300, h=150), "content"),
    ],
    ids=["alt", "no-alt", "alt-empty", "presentation", "aria-hidden", "hidden", "tiny", "logo-alt",
         "logo-src", "logo-home-link", "icon", "svg", "bg-behind-text", "bg-texture", "canvas"],
)
def test_rules(node, category):
    r = classify(node)
    assert r.category == category, r.reasons
    assert r.ocr_candidate is (category == "content")
    assert r.reasons and all(r.reasons)


def test_logo_word_matching_is_not_a_substring_match():
    """'catalogue' contains 'logo'-ish letters but is not a logo."""
    assert classify(img(alt="Catalogue cover")).category == "content"
    assert classify(img(id_class_text="hero-image biologos")).category == "content"


@pytest.mark.parametrize("alt", [
    "Apple Card, front, Apple logo in top left corner",
    "Aerial view of a street intersection where a Hertz logo is painted",
    "Our new logo design process, step by step",
])
def test_alt_that_describes_a_scene_with_a_logo_is_content(alt):
    """apple.com / stripe.com: product and street photos were skipped as 'logos'."""
    assert classify(img(alt=alt)).category == "content"


@pytest.mark.parametrize("alt", ["Stripe logo", "Acme Logotype", "  Mozilla logo "])
def test_alt_that_names_the_image_a_logo_is_a_logo(alt):
    assert classify(img(alt=alt)).category == "logo"


def test_a_large_image_in_a_link_is_not_an_icon():
    assert classify(img(w=320, h=180, in_control=True, alt="Read the story")).category == "content"


def test_identical_candidates_share_a_dedup_key():
    a = classify(img("#a", sources=["/p.jpg"]))
    b = classify(img("#b", sources=["/p.jpg"]))
    c = classify(img("#c", sources=["/p.jpg"], w=160, h=90))
    assert a.dedup_key == b.dedup_key != c.dedup_key
    s = triage(ImageInventory(images=[img("#a", sources=["/p.jpg"]), img("#b", sources=["/p.jpg"])]))
    assert (s.candidates, s.distinct_candidates) == (2, 1)


# --- against a real render ----------------------------------------------------

needs_worker = pytest.mark.skipif(not WORKER_JS.exists(), reason="node worker not built")


@needs_worker
@pytest.mark.asyncio
async def test_fixture_end_to_end():
    from verity.orchestrator.rpc_client import RPCClient

    client = RPCClient(command=["node", str(WORKER_JS)], default_timeout=90.0)
    await client.start()
    try:
        render = await client.send_request("render", {"url": FIXTURE.as_uri()})
        out = await inventory_and_triage(client.send_request, render["artifactId"])
    finally:
        await client.stop()

    by = {r.selector: r for r in out["triage"].results}
    # Every fixture id names its expected category by its prefix.
    expected = {"content": "content", "decorative": "decorative", "logo": "logo", "icon": "icon",
                "tiny": "tiny", "hidden": "hidden", "notext": "not-text"}
    checked = 0
    for selector, r in by.items():
        prefix = selector.lstrip("#").split("-")[0]
        if prefix in expected:
            assert r.category == expected[prefix], (selector, r.reasons)
            checked += 1
    assert checked >= 15
    assert by["#svg-chart"].category == "not-text"
    assert by["#roleimg-stars"].category in ("not-text", "content", "icon")

    # Only candidates are cropped, one per distinct image.
    s = out["triage"]
    assert s.candidates < s.total
    assert set(out["captures"]) <= {r.selector for r in s.results if r.ocr_candidate}
    assert "#content-photo-dup" not in out["captures"], "a duplicate is not cropped again"
