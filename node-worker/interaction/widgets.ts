/**
 * Widget inventory (A9.2) and widget exercising (A9.1, A9.3).
 *
 * The Interaction Agent's browser half. Two methods, same split as the
 * keyboard wedge: report what is there, report what happened — never decide.
 *
 *   inventoryWidgets — every widget on the page that carries EXPLICIT ARIA
 *                      semantics. "Never speculative": a role attribute, or
 *                      a native <button> with aria-expanded/aria-haspopup.
 *                      A <div class="tabs"> with no role is not a tablist,
 *                      and guessing that it is would hand the contract runner
 *                      a widget the author never claimed to have built.
 *   exerciseWidget   — play a list of focus/key steps and snapshot the
 *                      watched elements after each one. Whether the
 *                      transitions are correct APG behaviour is judged in
 *                      Python (verity/agents/interaction.py) against the
 *                      contracts in data/apg-contracts/.
 *
 * A9.3 lives in exerciseWidget: every step is raced against a timeout (a key
 * handler that never returns cannot hang the worker), the whole run has a
 * step budget and a wall-clock budget, and a step that navigates the page
 * away stops the run. Each of those is reported as `complete: false` with a
 * reason — a truncated run is never presented as a whole one.
 *
 * Shapes mirror WidgetInventory / ExerciseResult in verity/models/schemas.py.
 */

import type { Page } from "playwright";
import type {
  ExerciseResult,
  InteractionSnapshot,
  InteractionStep,
  WidgetInventory,
  WidgetNode,
} from "../contract/contract-types.js";
import { ROVING_ROLES } from "./traverse.js";

// Container roles whose owned items are what the user moves between, and the
// item roles each one owns. Keep in sync with the APG patterns we have
// contracts for; adding a role here without a contract is harmless (nothing
// matches it), adding a contract without its role here inventories nothing.
const CONTAINER_ITEMS: Record<string, string[]> = {
  tablist: ["tab"],
  menu: ["menuitem", "menuitemcheckbox", "menuitemradio"],
  menubar: ["menuitem", "menuitemcheckbox", "menuitemradio"],
};

const DEFAULT_MAX_STEPS = 40;
const DEFAULT_MAX_MS = 20_000;
// After a step, wait up to this long for ANY observable effect (focus moving,
// a watched element's state or visibility changing) before concluding the
// step did nothing. Real widgets act asynchronously: apple.com's bag button
// sets aria-expanded after a fetch (~800 ms), its gallery tabs move focus
// after a slide animation. Two animation frames — the old wait — reported
// both as keys that do nothing. A step that works returns as soon as the
// effect appears, so only genuinely inert keys pay the full wait.
const EFFECT_WAIT_MS = 1_200;
// Once something changed, let it finish (no further change for this long).
const SETTLE_QUIET_MS = 150;
const SETTLE_CAP_MS = 1_000;
const POLL_MS = 50;
const IDLE_PROBE_MS = 500;
// Per-step ceiling. A key whose handler spins (or a focus() that never
// settles) is cut off here rather than holding the worker until the RPC
// timeout kills the whole call.
const STEP_TIMEOUT_MS = 2_000;

export interface ExerciseOptions {
  steps: InteractionStep[];
  watch: string[];
  maxSteps?: number;
  maxMs?: number;
}

export async function inventoryWidgets(page: Page): Promise<WidgetInventory> {
  return page.evaluate(inventoryInPage, { containerItems: CONTAINER_ITEMS, rovingRoles: ROVING_ROLES });
}

export async function exerciseWidget(page: Page, options: ExerciseOptions): Promise<ExerciseResult> {
  const maxSteps = Math.max(1, Math.floor(options.maxSteps ?? DEFAULT_MAX_STEPS));
  const maxMs = Math.max(1, Math.floor(options.maxMs ?? DEFAULT_MAX_MS));
  const { steps, watch } = options;
  const started = Date.now();
  const startUrl = page.url();

  // Idle probe: does the widget change with nobody touching it? An
  // autoplaying gallery rotates its selected tab on a timer, and any effect
  // seen after a key could be the timer's.
  const idleBefore = await signature(page, watch);
  await page.waitForTimeout(IDLE_PROBE_MS);
  const selfChanging = (await signature(page, watch)) !== idleBefore;

  const snapshots: InteractionSnapshot[] = [await snapshot(page, -1, watch)];
  let stepsRun = 0;
  let incompleteReason: string | null = null;

  for (let i = 0; i < steps.length; i++) {
    if (stepsRun >= maxSteps) {
      incompleteReason = `interaction budget exhausted: ${maxSteps} steps`;
      break;
    }
    if (Date.now() - started > maxMs) {
      incompleteReason = `interaction budget exhausted: ${maxMs} ms`;
      break;
    }

    const step = steps[i];
    const sig = (pg: Page) => (step.expect === "focus" ? focusSignature(pg) : signature(pg, watch));
    const before = await sig(page);
    const ok = await withTimeout(runStep(page, step), STEP_TIMEOUT_MS);
    if (ok === "timeout") {
      incompleteReason = `step ${i} (${describeStep(step)}) did not settle within ${STEP_TIMEOUT_MS} ms`;
      break;
    }
    if (ok === false) {
      incompleteReason = `step ${i} (${describeStep(step)}) could not run: target not focusable or absent`;
      break;
    }
    stepsRun++;

    // Loop guard: a step that navigated took us off the page the widget was
    // on. Anything observed after that describes a different document.
    if (page.url() !== startUrl) {
      incompleteReason = `step ${i} (${describeStep(step)}) navigated away from the page`;
      break;
    }
    await awaitEffect(page, sig, before);
    if (page.url() !== startUrl) {
      incompleteReason = `step ${i} (${describeStep(step)}) navigated away from the page`;
      break;
    }
    snapshots.push(await snapshot(page, i, watch));
  }

  return {
    snapshots,
    steps_requested: steps.length,
    steps_run: stepsRun,
    complete: incompleteReason === null,
    incomplete_reason: incompleteReason,
    self_changing: selfChanging,
  };
}

function describeStep(step: InteractionStep): string {
  return step.action === "press" ? `press ${JSON.stringify(step.key)}` : `${step.action} ${step.target}`;
}

/** Run one step. Resolves false when the step could not be performed at all. */
async function runStep(page: Page, step: InteractionStep): Promise<boolean> {
  try {
    if (step.action === "focus") {
      if (!step.target) return false;
      const focused = await page.evaluate((sel) => {
        const el = document.querySelector(sel) as HTMLElement | null;
        if (!el || typeof el.focus !== "function") return false;
        el.focus();
        return document.activeElement === el;
      }, step.target);
      if (!focused) return false;
    } else if (step.action === "click") {
      if (!step.target) return false;
      await page.locator(step.target).first().click({ timeout: STEP_TIMEOUT_MS });
    } else {
      if (!step.key) return false;
      await page.keyboard.press(step.key);
    }
    // Let handlers, attribute changes, and one paint land before reading.
    await page.evaluate(
      () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r()))),
    );
    return true;
  } catch {
    return false;
  }
}

/** Everything a check could observe, as one comparable string. */
async function signature(page: Page, watch: string[]): Promise<string> {
  return page
    .evaluate(snapshotInPage, watch)
    .then((s) => JSON.stringify(s))
    .catch(() => "");
}

/** Just where focus is — for steps whose expected effect is moving it. */
async function focusSignature(page: Page): Promise<string> {
  return page
    .evaluate(() => {
      const a = document.activeElement;
      if (!a || a === document.body) return "";
      const path: string[] = [];
      for (let n: Element | null = a; n && n !== document.documentElement; n = n.parentElement) {
        path.unshift(n.id ? `#${n.id}` : `${n.tagName}:${Array.from(n.parentElement?.children ?? []).indexOf(n)}`);
        if (n.id) break;
      }
      return path.join(">");
    })
    .catch(() => "");
}

/**
 * Wait for the step's effect: poll until the observable state differs from
 * `before` (up to EFFECT_WAIT_MS), then until it stops changing (quiet for
 * SETTLE_QUIET_MS, capped). Returns early in the common case.
 */
async function awaitEffect(page: Page, sig: (p: Page) => Promise<string>, before: string): Promise<void> {
  const start = Date.now();
  let current = await sig(page);
  while (current === before && Date.now() - start < EFFECT_WAIT_MS) {
    await page.waitForTimeout(POLL_MS);
    current = await sig(page);
  }
  if (current === before) return;
  const settleStart = Date.now();
  let quietSince = Date.now();
  while (Date.now() - quietSince < SETTLE_QUIET_MS && Date.now() - settleStart < SETTLE_CAP_MS) {
    await page.waitForTimeout(POLL_MS);
    const next = await sig(page);
    if (next !== current) {
      current = next;
      quietSince = Date.now();
    }
  }
}

async function withTimeout<T>(p: Promise<T>, ms: number): Promise<T | "timeout"> {
  let timer: NodeJS.Timeout | undefined;
  const t = new Promise<"timeout">((resolve) => {
    timer = setTimeout(() => resolve("timeout"), ms);
  });
  try {
    return await Promise.race([p, t]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function snapshot(page: Page, stepIndex: number, watch: string[]): Promise<InteractionSnapshot> {
  const read = await page
    .evaluate(snapshotInPage, watch)
    .catch(() => ({ active: null, states: [] as WidgetNode[], missing: watch }));
  return { step_index: stepIndex, ...read };
}

/* ----------------------------------------------------------------------- *
 * In-page functions. Serialised into the browser, so they may only use
 * browser globals and their own arguments. `describe` and `cssPath` are
 * repeated in each for that reason, same as traverse.ts.
 * ----------------------------------------------------------------------- */

function snapshotInPage(watch: string[]): {
  active: string | null;
  states: WidgetNode[];
  missing: string[];
} {
  function cssPath(node: Element): string {
    if (node.id) return `#${CSS.escape(node.id)}`;
    const parts: string[] = [];
    let cur: Element | null = node;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
      if (cur.id) {
        parts.unshift(`#${CSS.escape(cur.id)}`);
        break;
      }
      const tag = cur.tagName.toLowerCase();
      const parent: Element | null = cur.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const sameTag = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName);
      if (sameTag.length === 1) parts.unshift(tag);
      else parts.unshift(`${tag}:nth-of-type(${sameTag.indexOf(cur) + 1})`);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function describe(el: Element): WidgetNode {
    const attributes: Record<string, string> = {};
    for (const a of Array.from(el.attributes)) {
      if (a.name.startsWith("aria-") || a.name === "id") attributes[a.name] = a.value;
    }
    const roleAttr = (el.getAttribute("role") ?? "").trim().split(/\s+/)[0] || null;
    const tag = el.tagName.toLowerCase();
    const implicit = tag === "button" ? "button" : tag === "a" && el.hasAttribute("href") ? "link" : null;
    const tiAttr = el.getAttribute("tabindex");
    const ti = tiAttr === null ? null : parseInt(tiAttr, 10);
    const h = el as HTMLElement;
    const hidden =
      !h.checkVisibility({ visibilityProperty: true } as CheckVisibilityOptions) ||
      el.closest("[hidden]") !== null ||
      el.closest('[aria-hidden="true"]') !== null;

    let name: string | null = null;
    const label = el.getAttribute("aria-label");
    if (label && label.trim()) name = label.trim();
    else {
      const by = el.getAttribute("aria-labelledby");
      if (by) {
        const t = by
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent ?? "")
          .join(" ")
          .trim();
        if (t) name = t;
      }
      if (!name) {
        const t = (el.textContent ?? "").trim().replace(/\s+/g, " ");
        if (t) name = t.slice(0, 120);
      }
    }

    return {
      selector: cssPath(el),
      tag,
      role: roleAttr ?? implicit,
      accessible_name: name,
      tabindex: ti === null || Number.isNaN(ti) ? null : ti,
      attributes,
      hidden,
      disabled: (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true",
    };
  }

  const states: WidgetNode[] = [];
  const missing: string[] = [];
  for (const sel of watch) {
    const el = document.querySelector(sel);
    if (el) states.push(describe(el));
    else missing.push(sel);
  }
  const a = document.activeElement;
  const active = !a || a === document.body || a === document.documentElement ? null : cssPath(a);
  return { active, states, missing };
}

function inventoryInPage(args: {
  containerItems: Record<string, string[]>;
  rovingRoles: string[];
}): WidgetInventory {
  const { containerItems, rovingRoles } = args;
  function cssPath(node: Element): string {
    if (node.id) return `#${CSS.escape(node.id)}`;
    const parts: string[] = [];
    let cur: Element | null = node;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
      if (cur.id) {
        parts.unshift(`#${CSS.escape(cur.id)}`);
        break;
      }
      const tag = cur.tagName.toLowerCase();
      const parent: Element | null = cur.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const sameTag = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName);
      if (sameTag.length === 1) parts.unshift(tag);
      else parts.unshift(`${tag}:nth-of-type(${sameTag.indexOf(cur) + 1})`);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function roleOf(el: Element): string | null {
    const r = (el.getAttribute("role") ?? "").trim().split(/\s+/)[0];
    if (r) return r;
    const tag = el.tagName.toLowerCase();
    if (tag === "button") return "button";
    if (tag === "a" && el.hasAttribute("href")) return "link";
    return null;
  }

  function describe(el: Element): WidgetNode {
    const attributes: Record<string, string> = {};
    for (const a of Array.from(el.attributes)) {
      if (a.name.startsWith("aria-") || a.name === "id") attributes[a.name] = a.value;
    }
    const tiAttr = el.getAttribute("tabindex");
    const ti = tiAttr === null ? null : parseInt(tiAttr, 10);
    const h = el as HTMLElement;
    const hidden =
      !h.checkVisibility({ visibilityProperty: true } as CheckVisibilityOptions) ||
      el.closest("[hidden]") !== null ||
      el.closest('[aria-hidden="true"]') !== null;

    let name: string | null = null;
    const label = el.getAttribute("aria-label");
    if (label && label.trim()) name = label.trim();
    else {
      const by = el.getAttribute("aria-labelledby");
      if (by) {
        const t = by
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent ?? "")
          .join(" ")
          .trim();
        if (t) name = t;
      }
      if (!name) {
        const t = (el.textContent ?? "").trim().replace(/\s+/g, " ");
        if (t) name = t.slice(0, 120);
      }
    }

    return {
      selector: cssPath(el),
      tag: el.tagName.toLowerCase(),
      role: roleOf(el),
      accessible_name: name,
      tabindex: ti === null || Number.isNaN(ti) ? null : ti,
      attributes,
      hidden,
      disabled: (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true",
    };
  }

  /** Items a container owns: descendants whose nearest same-role container is it, plus aria-owns. */
  function ownedItems(container: Element, role: string): Element[] {
    const itemRoles = containerItems[role] ?? [];
    const out: Element[] = [];
    for (const el of Array.from(container.querySelectorAll("[role]"))) {
      const r = roleOf(el);
      if (!r || !itemRoles.includes(r)) continue;
      let owner: Element | null = el.parentElement;
      while (owner && roleOf(owner) !== role) owner = owner.parentElement;
      if (owner === container) out.push(el);
    }
    for (const id of (container.getAttribute("aria-owns") ?? "").split(/\s+/).filter(Boolean)) {
      const el = document.getElementById(id);
      const r = el ? roleOf(el) : null;
      if (el && r && itemRoles.includes(r) && !out.includes(el)) out.push(el);
    }
    return out;
  }

  function referencedIds(el: Element): string[] {
    return ["aria-controls", "aria-labelledby", "aria-owns"]
      .flatMap((a) => (el.getAttribute(a) ?? "").split(/\s+/))
      .filter(Boolean);
  }

  const widgets: WidgetInventory["widgets"] = [];
  for (const el of Array.from(document.querySelectorAll("*"))) {
    const role = roleOf(el);
    if (!role) continue;

    let items: Element[];
    if (role in containerItems) {
      items = ownedItems(el, role);
    } else if (role === "button" && (el.hasAttribute("aria-expanded") || el.hasAttribute("aria-haspopup"))) {
      // A trigger: its items are those of the container it controls, if any.
      const target = document.getElementById((el.getAttribute("aria-controls") ?? "").split(/\s+/)[0] ?? "");
      const tRole = target ? roleOf(target) : null;
      items = target && tRole && tRole in containerItems ? ownedItems(target, tRole) : [];
    } else {
      continue;
    }

    const related = new Map<string, Element>();
    for (const node of [el, ...items]) {
      for (const id of referencedIds(node)) {
        const ref = document.getElementById(id);
        if (ref) related.set(id, ref);
      }
    }
    // Exactly one hop is followed, so a reference cycle cannot loop.

    const positive = Array.from(el.querySelectorAll("[tabindex]"))
      .filter((d) => parseInt(d.getAttribute("tabindex") ?? "", 10) > 0)
      .map(cssPath);

    // A trigger inside a roving-tabindex widget (the APG "tabs with action
    // buttons" example) carries tabindex=-1 by design and is reached with the
    // arrow keys — the same ARROW_NAVIGABLE rule traverse.ts applies.
    let rovingAncestor: string | null = null;
    for (let a = el.parentElement; a; a = a.parentElement) {
      const r = roleOf(a);
      if (r && rovingRoles.includes(r)) {
        rovingAncestor = cssPath(a);
        break;
      }
    }

    widgets.push({
      root: describe(el),
      roving_ancestor: rovingAncestor,
      items: items.map(describe),
      related: [...related.values()].map(describe),
      positive_tabindex_descendants: positive,
    });
  }

  const all = Array.from(document.querySelectorAll("*"));
  return {
    widgets,
    shadow_roots_skipped: all.filter((e) => (e as Element & { shadowRoot?: ShadowRoot }).shadowRoot).length,
    iframes_skipped: document.querySelectorAll("iframe").length,
  };
}
