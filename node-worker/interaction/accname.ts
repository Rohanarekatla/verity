/**
 * B9.1 / B9.3 — the browser's own accessible name for inventoried elements.
 * (Track B, Week 9.)
 *
 * The widget inventory guesses names in-page: aria-label, then
 * aria-labelledby, then textContent. That guess is wrong in exactly the
 * places a contract check cares about:
 *
 *   - `<label for>` on an `<input role="combobox">` — textContent is empty,
 *     so the APG's own combobox examples would fail "has an accessible name";
 *   - `alt` on an `<img>` inside a button, `title`, `aria-hidden` children
 *     (counted by textContent, excluded by the spec);
 *   - SHADOW DOM (B9.3): a custom element whose label lives in its shadow
 *     root has an empty light-DOM textContent, so a perfectly named
 *     `<x-toggle role="button">` would read as nameless.
 *
 * Chromium already implements the accname spec (computeAccessibleName) over
 * the flat, shadow-including tree; it is what render.ts saves as ax-tree.json
 * and what a screen reader on that browser would hear. So instead of a second
 * hand-rolled implementation, ask the browser, per node, over CDP:
 *
 *   Runtime.evaluate(querySelector) -> objectId
 *   Accessibility.getPartialAXTree({objectId, fetchRelatives:false}) -> name
 *
 * Rules, so this can only make names MORE correct:
 *   - a node the browser reports as ignored (display:none, a closed popup's
 *     options) keeps the in-page guess — the accessibility tree has no name
 *     for something that is not rendered;
 *   - a rendered node takes the browser's name, including an empty one —
 *     a dialog with no label is nameless even if it contains text;
 *   - any CDP failure leaves the inventory exactly as the in-page code built
 *     it. A missing supplement is never a reason to fail the scan.
 */

import type { Page } from "playwright";
import type { Widget, WidgetInventory, WidgetNode } from "../contract/contract-types.js";

export interface ComputedAccessible {
  name: string | null;
  role: string | null;
  ignored: boolean;
}

/** The browser-computed name/role for each selector it could resolve. */
export async function computeAccessible(page: Page, selectors: string[]): Promise<Map<string, ComputedAccessible>> {
  const out = new Map<string, ComputedAccessible>();
  const cdp = await page.context().newCDPSession(page);
  try {
    for (const sel of new Set(selectors)) {
      let objectId: string | undefined;
      try {
        const evaluated = await cdp.send("Runtime.evaluate", {
          expression: `document.querySelector(${JSON.stringify(sel)})`,
        });
        objectId = evaluated.result.objectId;
        if (!objectId) continue;
        const { nodes } = await cdp.send("Accessibility.getPartialAXTree", { objectId, fetchRelatives: false });
        const n = nodes[0];
        if (!n) continue;
        const raw = n.name?.value;
        const name = typeof raw === "string" && raw.trim() ? raw.trim().replace(/\s+/g, " ") : null;
        const role = typeof n.role?.value === "string" ? (n.role.value as string) : null;
        out.set(sel, { name, role, ignored: n.ignored === true });
      } catch {
        // One element the browser cannot describe never fails the inventory.
      } finally {
        if (objectId) await cdp.send("Runtime.releaseObject", { objectId }).catch(() => {});
      }
    }
  } finally {
    await cdp.detach().catch(() => {});
  }
  return out;
}

/** Apply the browser's name to one node, under the rules in the header. */
export function applyComputedName(node: WidgetNode, computed: ComputedAccessible | undefined): WidgetNode {
  if (!computed || computed.ignored) return node;
  return { ...node, accessible_name: computed.name };
}

/** Return the inventory with every rendered node's name taken from the browser. */
export async function withComputedNames(page: Page, inventory: WidgetInventory): Promise<WidgetInventory> {
  const widgets = inventory.widgets ?? [];
  const selectors = widgets.flatMap((w) => [w.root, ...(w.items ?? []), ...(w.related ?? [])]).map((n) => n.selector);
  if (selectors.length === 0) return inventory;

  let computed: Map<string, ComputedAccessible>;
  try {
    computed = await computeAccessible(page, selectors);
  } catch {
    return inventory;
  }
  const fix = (n: WidgetNode) => applyComputedName(n, computed.get(n.selector));
  const fixed: Widget[] = widgets.map((w) => ({
    ...w,
    root: fix(w.root),
    items: (w.items ?? []).map(fix),
    related: (w.related ?? []).map(fix),
  }));
  return { ...inventory, widgets: fixed };
}
