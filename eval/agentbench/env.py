"""
eval/agentbench/env.py — browser environment for the Agent Accessibility Benchmark.

One episode = one MiniWoB++ task at one seed, optionally with one injected
accessibility defect (defects.js). The agent sees ONLY the accessibility tree
Chrome computes (CDP Accessibility.getFullAXTree) rendered as indented text —
the same signal tree-based agents (Playwright MCP, ChatGPT Atlas per OpenAI)
use — and acts only by element id or keyboard.

Every interactive or named element carries a stable `bid` (benchmark id),
assigned in the page, so actions can target it. Elements without a role and
without a name are still listed if they are clickable, as `generic` — a
div-button is not invisible to the agent, it is *unnamed and roleless*, which
is the realistic failure, not a magic disappearance.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, Page, sync_playwright

HERE = Path(__file__).resolve().parent
MINIWOB = HERE / "vendor" / "miniwob-plusplus" / "miniwob" / "html" / "miniwob"
DEFECTS_JS = (HERE / "defects.js").read_text(encoding="utf-8")

# Roles the observation never shows on their own (pure structure).
_SKIP_ROLES = {"none", "presentation", "InlineTextBox", "LineBreak", "ignored"}

_ASSIGN_BIDS = """() => {
  let n = window.__vbid || 0;
  for (const el of document.querySelectorAll('body *')) {
    if (!el.hasAttribute('data-vbid')) el.setAttribute('data-vbid', String(n++));
  }
  window.__vbid = n;
}"""

_CLICKABLE = """() => Array.from(document.querySelectorAll('[data-vbid]'))
  .filter(el => { const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
                  return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' &&
                         (cs.cursor === 'pointer' || el.onclick || el.tagName === 'INPUT'); })
  .map(el => el.getAttribute('data-vbid'))"""


def chromium_path() -> Optional[str]:
    """Reuse the Chromium the Node worker's Playwright installed (no second download)."""
    candidates = sorted(Path.home().glob(
        "Library/Caches/ms-playwright/chromium-*/chrome-mac*/*.app/Contents/MacOS/*"))
    return str(candidates[-1]) if candidates else None


@dataclass
class Step:
    observation: str
    action: str
    ok: bool
    error: Optional[str] = None


@dataclass
class Episode:
    task: str
    seed: int
    defect: Optional[str]
    goal: str = ""
    reward: float = 0.0
    done: bool = False
    steps: list[Step] = field(default_factory=list)
    seconds: float = 0.0


class MiniWoBEnv:
    """Context manager owning one browser; `reset()` starts an episode."""

    def __init__(self, headless: bool = True, episode_max_ms: int = 60_000):
        self.headless = headless
        self.episode_max_ms = episode_max_ms
        self._pw = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    def __enter__(self) -> "MiniWoBEnv":
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless, executable_path=chromium_path())
        return self

    def __exit__(self, *exc) -> None:
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()

    # -- episodes -------------------------------------------------------------

    def reset(self, task: str, seed: int, defect: Optional[str] = None) -> str:
        if self.page:
            self.page.close()
        self.page = self.browser.new_page(viewport={"width": 500, "height": 400})
        self.page.add_init_script(DEFECTS_JS)
        self.page.goto((MINIWOB / f"{task}.html").as_uri(), wait_until="load")
        self._settle()
        self.page.evaluate(f"core.EPISODE_MAX_TIME = {self.episode_max_ms}")
        self.page.evaluate(f"Math.seedrandom({seed})")
        self.page.evaluate("core.startEpisodeReal()")
        if defect:
            self.page.evaluate(f"window.__verityDefect({json.dumps(defect)})")
        self._settle()
        return self.page.evaluate("core.getUtterance()")

    def _settle(self) -> None:
        """
        Wait until images and fonts are loaded. Without this a clean episode
        could start before an icon sprite had painted while a defect episode
        (a few ms slower) started after — a timing difference that the pixel
        check first mistook for the defect being visible.
        """
        self.page.evaluate("""async () => {
          await document.fonts.ready;
          await Promise.all(Array.from(document.images).filter(i => !i.complete)
            .map(i => new Promise(r => { i.onload = i.onerror = r; })));
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        }""")
        # CSS background images (jQuery UI icon sprites) have no load event;
        # a short idle wait covers them.
        self.page.wait_for_load_state("networkidle")

    def status(self) -> tuple[bool, float]:
        done = bool(self.page.evaluate("WOB_DONE_GLOBAL"))
        return done, float(self.page.evaluate("WOB_RAW_REWARD_GLOBAL"))

    # -- observation ------------------------------------------------------------

    def observe(self) -> str:
        """The accessibility tree as indented text: `[bid] role "name" (states)`."""
        page = self.page
        page.evaluate(_ASSIGN_BIDS)
        clickable = set(page.evaluate(_CLICKABLE))
        cdp = page.context.new_cdp_session(page)
        try:
            cdp.send("DOM.enable")
            cdp.send("Accessibility.enable")
            root = cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
            bid_of = {}
            stack = [root]
            while stack:
                node = stack.pop()
                attrs = node.get("attributes") or []
                pairs = dict(zip(attrs[::2], attrs[1::2]))
                if "data-vbid" in pairs:
                    bid_of[node["backendNodeId"]] = pairs["data-vbid"]
                stack.extend(node.get("children") or [])
                if node.get("contentDocument"):
                    stack.append(node["contentDocument"])
            ax = cdp.send("Accessibility.getFullAXTree")["nodes"]
        finally:
            cdp.detach()

        by_id = {n["nodeId"]: n for n in ax}
        lines: list[str] = []

        def visit(node_id: str, depth: int) -> None:
            n = by_id.get(node_id)
            if not n:
                return
            role = (n.get("role") or {}).get("value", "")
            name = ((n.get("name") or {}).get("value") or "").strip()
            bid = bid_of.get(n.get("backendDOMNodeId"))
            # A roleless element that directly holds text (a div-button) is
            # still something an agent can click — it is unnamed and has no
            # role, which is the realistic failure. Hiding it would overstate
            # the defect's effect.
            holds_text = role in ("generic", "") and bid is not None and any(
                ((by_id.get(c) or {}).get("role") or {}).get("value") == "StaticText"
                for c in n.get("childIds") or [])
            shown = role not in _SKIP_ROLES and (holds_text or not n.get("ignored")) and (
                name or holds_text or role not in ("generic", "StaticText", "paragraph") or bid in clickable)
            if role == "StaticText":
                shown = bool(name)
            if shown:
                states = []
                for p in n.get("properties") or []:
                    v = (p.get("value") or {}).get("value")
                    if p["name"] in ("checked", "selected", "expanded", "disabled", "focused") and v not in (None, False, "false"):
                        states.append(p["name"] if v is True or v == "true" else f"{p['name']}={v}")
                label = f'[{bid}] ' if bid is not None and role != "StaticText" else ""
                text = f'{label}{role} "{name}"' if name else f"{label}{role}"
                if bid in clickable and role in ("generic", ""):
                    text += " (clickable)"
                lines.append("  " * depth + text + (f" ({', '.join(states)})" if states else ""))
            for child in n.get("childIds") or []:
                visit(child, depth + (1 if shown else 0))

        visit(ax[0]["nodeId"], 0)
        return "\n".join(lines)

    # -- actions ----------------------------------------------------------------

    def act(self, action: dict) -> Optional[str]:
        """Perform one action; return an error string or None."""
        kind = action.get("action")
        page = self.page
        try:
            if kind in ("click", "fill", "focus", "select", "check"):
                loc = page.locator(f'[data-vbid="{action.get("bid")}"]')
                if loc.count() == 0:
                    return f"no element with bid {action.get('bid')}"
                if kind == "click":
                    loc.first.click(timeout=3000)
                elif kind == "fill":
                    loc.first.fill(str(action.get("text", "")), timeout=3000)
                elif kind == "focus":
                    loc.first.focus(timeout=3000)
                elif kind == "check":
                    loc.first.check(timeout=3000)
                else:
                    loc.first.select_option(str(action.get("value", "")), timeout=3000)
            elif kind == "press":
                page.keyboard.press(str(action.get("key", "")))
            elif kind == "type":
                page.keyboard.type(str(action.get("text", "")))
            elif kind == "done":
                return None
            else:
                return f"unknown action {kind!r}"
        except Exception as exc:  # the agent must see why its action failed
            return f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
        time.sleep(0.05)
        return None

    def screenshot(self) -> bytes:
        return self.page.screenshot()
