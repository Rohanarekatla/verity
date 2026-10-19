"""
B9.1–B9.3 (Track B, Week 9) — announcement prediction, the virtual screen
reader, and the browser-computed accessible names that feed both.

The pure half runs everywhere on hand-built CDP trees. The browser half
renders real fixtures through the worker — the "virtual screen reader in CI"
the plan asks for: headless Linux, no real screen reader — and is skipped
when the worker is not built.
"""

from pathlib import Path

import pytest

from verity.agents.announce import predict, predict_for_widget_node
from verity.agents.virtual_sr import browse, focusables, load_ax_tree, transcript, unnamed_controls
from verity.models.schemas import WidgetNode

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "data" / "fixtures"
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"

needs_worker = pytest.mark.skipif(
    not WORKER_JS.exists(),
    reason="node worker not built (cd node-worker && npm run build)",
)


# --- B9.1: announcement prediction ----------------------------------------------

@pytest.mark.parametrize("role, name, states, expected", [
    ("button", "Show details", {"expanded": False}, "Show details, button, collapsed"),
    ("button", "Show details", {"expanded": "true"}, "Show details, button, expanded"),
    ("tab", "Shipping", {"selected": True}, "Shipping, tab, selected"),
    ("checkbox", "Accept", {"checked": "mixed"}, "Accept, checkbox, half checked"),
    ("switch", "Wi-Fi", {"checked": "true"}, "Wi-Fi, switch, on"),
    ("button", "Bold", {"pressed": "false"}, "Bold, button, not pressed"),
    ("heading", "Delivery", {"level": 2}, "Delivery, heading, level 2"),
    ("textbox", "Email", {"required": True, "invalid": "true"}, "Email, edit, required, invalid entry"),
    ("combobox", "State", {"expanded": False}, "State, combo box, collapsed"),
    ("link", "Home", {"disabled": True}, "Home, link, unavailable"),
])
def test_announcement_is_name_role_states(role, name, states, expected):
    assert predict(role, name, states).text == expected


def test_an_unnamed_control_is_announced_as_its_role_alone_and_flagged():
    a = predict("button", "   ")
    assert a.text == "button"
    assert a.unnamed_control


def test_unnamed_structure_is_not_flagged_as_an_unnamed_control():
    assert not predict("list", None).unnamed_control


def test_selected_is_not_spoken_for_roles_that_do_not_support_it():
    assert predict("button", "Go", {"selected": True}).text == "Go, button"


def test_widget_node_announcement_uses_aria_states_and_native_disabled():
    node = WidgetNode(selector="#b", tag="button", role="button", accessible_name="Menu",
                      attributes={"aria-expanded": "false", "aria-haspopup": "true"}, disabled=True)
    assert predict_for_widget_node(node).text == "Menu, button, has popup menu, collapsed, unavailable"


# --- B9.2: the virtual screen reader over a CDP accessibility tree -------------

def _n(node_id, role, name=None, kids=(), parent=None, ignored=False, **props):
    raw = {
        "nodeId": node_id, "ignored": ignored, "role": {"type": "role", "value": role},
        "childIds": list(kids),
        "properties": [{"name": k, "value": {"type": "x", "value": v}} for k, v in props.items()],
    }
    if name is not None:
        raw["name"] = {"type": "computedString", "value": name}
    if parent is not None:
        raw["parentId"] = parent
    return raw


TREE = {"nodes": [
    _n("1", "RootWebArea", "Checkout", ["2"]),
    _n("2", "none", None, ["3", "4", "6", "8"], "1", ignored=True),
    _n("3", "heading", "Delivery", ["30"], "2", level=1),
    _n("30", "StaticText", "Delivery", [], "3"),
    _n("4", "button", "Show details", ["5"], "2", expanded=False, focusable=True),
    _n("5", "StaticText", "Show details", ["50"], "4"),
    _n("50", "InlineTextBox", "Show details", [], "5"),
    _n("6", "button", "", [], "2", focusable=True),
    _n("8", "dialog", "Address", ["9"], "2", modal=True),
    _n("9", "StaticText", "Enter your street.", [], "8"),
]}


def test_browse_mode_transcript_reads_each_stop_once_in_document_order():
    assert transcript(load_ax_tree(TREE)).splitlines() == [
        "Delivery, heading, level 1",
        "Show details, button, collapsed",   # its StaticText child is its name, not read again
        "button",
        "Address, dialog, modal",
        "Enter your street.",
    ]


def test_ignored_wrappers_are_skipped_but_their_content_is_read():
    texts = [a.text for a in browse(load_ax_tree(TREE))]
    assert "Delivery, heading, level 1" in texts  # under an ignored node


def test_unnamed_controls_are_what_a_screen_reader_user_hears_as_just_button():
    assert [a.source for a in unnamed_controls(load_ax_tree(TREE))] == ["6"]


def test_focusables_announce_what_landing_on_them_sounds_like():
    assert [a.text for a in focusables(load_ax_tree(TREE))] == ["Show details, button, collapsed", "button"]


def test_a_deep_tree_does_not_hit_the_recursion_limit():
    depth = 5000
    nodes = [_n("0", "RootWebArea", "Deep", ["1"])]
    for i in range(1, depth):
        nodes.append(_n(str(i), "generic", None, [str(i + 1)], str(i - 1)))
    nodes.append(_n(str(depth), "button", "Bottom", [], str(depth - 1)))
    assert transcript(load_ax_tree({"nodes": nodes})) == "Bottom, button"


# --- in CI, against the real browser ---------------------------------------------

async def _render(client, name: str) -> dict:
    return await client.send_request("render", {"url": (FIXTURES / name).as_uri()})


async def _client():
    from verity.orchestrator.rpc_client import RPCClient

    client = RPCClient(command=["node", str(WORKER_JS)], default_timeout=60.0)
    await client.start()
    return client


@needs_worker
@pytest.mark.asyncio
async def test_inventory_takes_the_browsers_accessible_name_including_shadow_dom():
    """B9.1/B9.3: <label for>, img alt, aria-hidden children and a shadow-root label."""
    from verity.models.schemas import WidgetInventory

    client = await _client()
    try:
        render = await _render(client, "accname-shadow.html")
        raw = await client.send_request("inventoryWidgets", {"artifactId": render["artifactId"]})
        await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})
    finally:
        await client.stop()

    names = {w.root.selector: w.root.accessible_name for w in WidgetInventory.model_validate(raw).widgets}
    assert names["#shadow-toggle"] == "Show shipping details"   # label inside the shadow root
    assert names["#icon-toggle"] == "Settings"                  # from <img alt>
    assert names["#hidden-child"] == "More"                     # aria-hidden "▼" excluded
    assert names["#state"] == "State"                           # from <label for>


@needs_worker
@pytest.mark.asyncio
async def test_virtual_screen_reader_reads_a_rendered_page():
    """B9.2 in CI: the transcript of a real render's accessibility tree."""
    client = await _client()
    try:
        render = await _render(client, "accname-shadow.html")
        await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})
    finally:
        await client.stop()

    tree = load_ax_tree(Path(render["ax_tree_path"]))
    lines = transcript(tree).splitlines()
    assert any(line.startswith("Show shipping details, button") and "collapsed" in line for line in lines), lines
    assert any(line.startswith("Settings, button") for line in lines), lines
    assert any(line.startswith("State, combo box") for line in lines), lines
    assert unnamed_controls(tree) == []
