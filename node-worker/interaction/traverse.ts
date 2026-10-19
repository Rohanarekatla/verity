/**
 * Keyboard tab-order traversal (A4.1), multi-cycle trap detection (A4.2),
 * and the focus-visible capture hook (A4.3).
 *
 * This is the half of the keyboard wedge that has to touch a real browser:
 * it presses Tab and records where focus actually lands. The verdicts —
 * SC 2.1.1/2.1.2/2.4.3/2.4.7 — live on the Python side in agents/keyboard.py.
 * Nothing here decides conformance; it reports what happened when we pressed
 * Tab, and the four fields keyboard.py depends on are documented at each
 * point because getting one wrong is a specific, named false positive.
 *
 * The return shape mirrors `TraversalResult` in verity/models/schemas.py
 * exactly (exported into verity-schema.json). snake_case on the wire because
 * that is the contract Python validates against.
 *
 * The one rule to read twice: an element skipped by Tab because it lives in a
 * roving-tabindex widget (a correct APG tablist exposes ONE Tab stop for six
 * tabs; the rest carry tabindex="-1" and move under the arrow keys) is
 * `ARROW_NAVIGABLE`, never `NOT_FOCUSABLE`. Week 4's gate is zero false
 * alarms on clean APG widgets, and that misclassification fails it on the
 * first example.
 */

import type { Page } from "playwright";
import { decodePng } from "../static/png.js";

/** Mirrors verity/models/schemas.py:UnreachedReason (the string values). */
export type UnreachedReason =
  | "shadow-dom"
  | "iframe"
  | "not-focusable"
  | "obscured"
  | "arrow-navigable"
  | "unknown";

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TabStop {
  order: number;
  selector: string;
  cycle: number;
  bbox: BoundingBox | null;
  role: string | null;
  accessible_name: string | null;
  /** The AUTHORED tabindex attribute, null when absent — never the computed one. */
  tabindex: number | null;
  /** A4.3 fills this; null = not measured, false = measured and absent. */
  focus_visible: boolean | null;
  dom_order: number | null;
}

export interface UnreachedRegion {
  selector: string;
  reason: UnreachedReason;
  detail: string | null;
}

export interface TraversalResult {
  stops: TabStop[];
  cycles_requested: number;
  cycles_completed: number;
  returned_to_origin: boolean;
  trap_detected: boolean;
  trap_selector: string | null;
  unreached: UnreachedRegion[];
  complete: boolean;
  incomplete_reason: string | null;
}

export interface TraverseOptions {
  /**
   * How many full cycles (origin → … → back to origin) to run. A trap that
   * only manifests on a later cycle is invisible to a shorter run, which is
   * why keyboard.py returns `indeterminate` rather than `pass` when fewer
   * cycles completed than were requested. N is pinned by measurement in
   * docs/measurements/keyboard-trap-cycles.md.
   */
  cyclesRequested?: number;
  /**
   * Hard cap on Tab presses, so a trap or a pathological page cannot spin the
   * worker forever. Exceeding it is reported as `complete: false`, never as a
   * finished traversal.
   */
  maxPresses?: number;
  /** A4.3: measure focus-visible on each stop (style diff vs baseline). Off by default. */
  measureFocusVisible?: boolean;
}

// Computed-style properties that a visible focus indicator changes. An
// outline or box-shadow covers the overwhelming majority of real indicators;
// border/background/text-decoration catch the rest. Compared focused-vs-not.
const FOCUS_STYLE_PROPS = [
  "outline-style",
  "outline-width",
  "outline-color",
  "outline-offset",
  "box-shadow",
  "border-top-width",
  "border-top-color",
  "border-right-width",
  "border-bottom-width",
  "border-left-width",
  "border-top-style",
  "background-color",
  "color",
  "text-decoration-line",
];

// Roles that drive their children with arrow keys rather than Tab (roving
// tabindex). A `tabindex="-1"` element under one of these is reachable by
// design — correct authoring, not a barrier. Keep in sync with the APG.
export const ROVING_ROLES = [
  "tablist",
  "menu",
  "menubar",
  "radiogroup",
  "tree",
  "treegrid",
  "grid",
  "listbox",
  "toolbar",
];

const DEFAULT_CYCLES = 2;
const DEFAULT_MAX_PRESSES = 600;
// Focus landing on the same selector this many presses in a row with no
// progress is a keyboard trap: the page is swallowing Tab.
const TRAP_REPEAT_THRESHOLD = 4;
// While focus is inside an <iframe>, the outer document's activeElement stays
// the frame element no matter how many controls Tab moves through inside it
// (a YouTube embed has a dozen). That is not a trap — it is focus we cannot
// see. Allow this many presses inside one frame before giving up on it as a
// blind spot (reported as an incomplete traversal, never as a trap).
const IFRAME_PRESS_CAP = 60;

/** Shape returned by the in-page describe of document.activeElement. */
interface ActiveDescriptor {
  /** True when focus left the page content (body, documentElement, or null). */
  leftPage: boolean;
  /** True when focus entered an <iframe> (activeElement is the frame element). */
  isIframe: boolean;
  selector: string;
  bbox: BoundingBox | null;
  role: string | null;
  accessible_name: string | null;
  tabindex: number | null;
  dom_order: number | null;
  /** Computed-style signature while focused; null unless measureStyle asked. */
  style_sig: string | null;
}

export async function traverseTabOrder(
  page: Page,
  options: TraverseOptions = {},
): Promise<TraversalResult> {
  const cyclesRequested = Math.max(1, Math.floor(options.cyclesRequested ?? DEFAULT_CYCLES));
  const maxPresses = Math.max(1, Math.floor(options.maxPresses ?? DEFAULT_MAX_PRESSES));

  const measureStyle = options.measureFocusVisible === true;

  // Start from a clean slate: blur whatever holds focus so the first Tab lands
  // on the document's first focusable element deterministically.
  await page.evaluate(() => {
    const a = document.activeElement as HTMLElement | null;
    if (a && typeof a.blur === "function") a.blur();
  });

  // A4.3 baseline: with nothing focused, capture each focusable element's
  // computed-style signature. During the loop we read the signature again
  // while the element is KEYBOARD-focused (so :focus-visible is active) and
  // compare. A difference is a visible focus indicator; identical styles mean
  // none. Captured up front because once traversal starts, something is always
  // focused and there is no unfocused reading left to take.
  const baseline = new Map<string, string>();
  if (measureStyle) {
    const entries: Array<{ selector: string; sig: string }> = await page.evaluate(
      captureBaselineStyles,
      FOCUS_STYLE_PROPS,
    );
    for (const e of entries) baseline.set(e.selector, e.sig);
  }

  // What was focusable when the traversal began. A control that becomes
  // focusable only later (stripe.com's carousel enables "Previous" once it
  // advances) was legitimately skipped by Tab while disabled; judging it
  // unreachable afterwards would be a false SC 2.1.1 barrier.
  const initiallyFocusable: string[] = await page.evaluate(focusableNow);

  const stops: TabStop[] = [];
  const visited = new Set<string>();
  let prevSelector: string | null = null;
  let repeatRun = 0;
  let cyclesCompleted = 0;
  let returnedToOrigin = false;
  let trapDetected = false;
  let trapSelector: string | null = null;
  let complete = true;
  let incompleteReason: string | null = null;
  let iframeSeen = false;
  let iframeRun = 0;

  let presses = 0;
  for (; presses < maxPresses; presses++) {
    await page.keyboard.press("Tab");
    const d: ActiveDescriptor = await page.evaluate(describeActiveElement, {
      rovingRoles: ROVING_ROLES,
      styleProps: measureStyle ? FOCUS_STYLE_PROPS : null,
    });

    if (d.isIframe) {
      // We do not traverse into frame content — focus is somewhere we cannot
      // observe. Record the frame as a blind spot and keep going; blaming the
      // site for our own limitation would be a false positive.
      iframeSeen = true;
    }

    if (d.leftPage) {
      // Focus returned to the document body. Headless has no browser chrome,
      // so Tab past the last control lands on body rather than a URL bar —
      // this is the end of one full pass through the page.
      if (stops.length === 0) {
        // Nothing focusable at all: the first Tab went straight to body. There
        // is no tab order to traverse; that is complete, not a trap.
        break;
      }
      cyclesCompleted++;
      returnedToOrigin = true;
      if (cyclesCompleted >= cyclesRequested) break;
      // The next Tab re-enters at the first focusable element, beginning the
      // next cycle. Reset the repeat tracker so the boundary isn't mistaken
      // for a stuck focus.
      prevSelector = null;
      repeatRun = 0;
      continue;
    }

    // Focus still inside the same iframe: it is moving through the frame's own
    // controls, which we cannot observe. Keep pressing; it is not a trap.
    if (d.isIframe && d.selector === prevSelector) {
      iframeRun++;
      if (iframeRun >= IFRAME_PRESS_CAP) {
        complete = false;
        incompleteReason = `focus did not leave iframe ${d.selector} within ${IFRAME_PRESS_CAP} presses; frame content is not traversed`;
        break;
      }
      continue;
    }
    iframeRun = 0;

    // Trap: the same element keeps catching focus and Tab never advances.
    if (d.selector === prevSelector) {
      repeatRun++;
      if (repeatRun >= TRAP_REPEAT_THRESHOLD) {
        trapDetected = true;
        trapSelector = d.selector;
        break;
      }
      continue;
    }
    repeatRun = 0;
    prevSelector = d.selector;

    visited.add(d.selector);
    let focusVisible = resolveFocusVisible(measureStyle, baseline, d.selector, d.style_sig);
    if (focusVisible === false) {
      // The element's own style did not change — but the indicator may be
      // drawn elsewhere: a wrapper's :focus-within ring (github.com's email
      // field), a ::after outline, an offset box-shadow. Only pixels can say
      // there is nothing. A false here becomes an SC 2.4.7 failure.
      focusVisible = await confirmNoIndicatorByPixels(page, d.selector);
    }
    stops.push({
      order: stops.length,
      selector: d.selector,
      cycle: cyclesCompleted,
      bbox: d.bbox,
      role: d.role,
      accessible_name: d.accessible_name,
      tabindex: d.tabindex,
      focus_visible: focusVisible,
      dom_order: d.dom_order,
    });
  }

  if (trapDetected) {
    // The trap is a finding in its own right, but the traversal stopped at it:
    // everything after the trap was never visited, so the unreached list below
    // is not evidence that those elements are unreachable.
    complete = false;
    incompleteReason = `traversal stopped at a keyboard trap on ${trapSelector}`;
  } else if (presses >= maxPresses) {
    // We stopped because we hit the cap, not because the traversal finished.
    // That is a partial observation and must be reported as one.
    complete = false;
    incompleteReason = `exceeded ${maxPresses} Tab presses without returning to origin`;
  }

  // Classify everything focusable that Tab never landed on. This is where the
  // roving-tabindex distinction is made.
  const unreached: UnreachedRegion[] = await page.evaluate(
    classifyUnreached,
    { visited: [...visited], rovingRoles: ROVING_ROLES, initiallyFocusable },
  );
  if (iframeSeen && !unreached.some((u) => u.reason === "iframe")) {
    unreached.push({
      selector: "iframe",
      reason: "iframe",
      detail: "focus entered an iframe; frame content was not traversed",
    });
  }

  return {
    stops,
    cycles_requested: cyclesRequested,
    cycles_completed: cyclesCompleted,
    returned_to_origin: returnedToOrigin,
    trap_detected: trapDetected,
    trap_selector: trapSelector,
    unreached,
    complete,
    incomplete_reason: incompleteReason,
  };
}

/** Margin (CSS px) around the element scanned for a focus indicator. */
const INDICATOR_MARGIN_PX = 8;
/** Per-channel difference that counts as a changed pixel. */
const INDICATOR_TOLERANCE = 16;
/** Changed pixels needed to call it a visible indicator (not noise). */
const INDICATOR_MIN_PIXELS = 4;

/**
 * A4.3 confirmation — is there really no visible change when this element
 * has keyboard focus? Screenshot the element plus a margin while focused,
 * blur, screenshot again, and restore focus (sequential navigation continues
 * from the focused element, so the traversal is unaffected).
 *
 * true  = pixels changed: an indicator exists somewhere around the element
 * false = identical: there is genuinely nothing to see
 * null  = could not measure (offscreen, detached) — never a failure
 */
async function confirmNoIndicatorByPixels(page: Page, selector: string): Promise<boolean | null> {
  try {
    const box = await page.evaluate(
      ({ sel, m }) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        // "instant": with scroll-behavior:smooth (github.com) a plain
        // scrollIntoView animates, the box below is measured mid-scroll, and
        // both shots photograph the wrong part of the page — identical, so
        // "no indicator". That was a false SC 2.4.7 failure.
        // "center", not "nearest": nearest parks it at the viewport edge,
        // under a sticky header (github.com), and both shots photograph the
        // header.
        el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" as ScrollBehavior });
        const r = el.getBoundingClientRect();
        // Something else on top at its centre (a fixed bar, an overlay):
        // whatever we photograph is not this element.
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        if (!top || !(top === el || el.contains(top) || top.contains(el))) return null;
        const x = Math.max(0, Math.floor(r.left - m));
        const y = Math.max(0, Math.floor(r.top - m));
        const right = Math.min(window.innerWidth, Math.ceil(r.right + m));
        const bottom = Math.min(window.innerHeight, Math.ceil(r.bottom + m));
        return right > x && bottom > y ? { x, y, width: right - x, height: bottom - y } : null;
      },
      { sel: selector, m: INDICATOR_MARGIN_PX },
    );
    if (!box) return null;
    // Scroll-reveal animations (github.com's lower sections fade in from
    // opacity 0 once scrolled to): wait until the element is actually shown.
    // Two identical shots of an invisible element mean "could not see", not
    // "no indicator".
    if (!(await waitUntilOpaque(page, selector))) return null;
    // Let a focus-ring transition finish before reading it.
    await page.waitForTimeout(200);
    // The box must not have moved since it was measured (late scroll, layout
    // shift) — otherwise the shots are of somewhere else, and "identical"
    // would mean nothing.
    const still = await page.evaluate(
      ({ sel, b, m }) => {
        const r = document.querySelector(sel)?.getBoundingClientRect();
        return !!r && Math.abs(Math.max(0, Math.floor(r.left - m)) - b.x) <= 1 && Math.abs(Math.max(0, Math.floor(r.top - m)) - b.y) <= 1;
      },
      { sel: selector, b: box, m: INDICATOR_MARGIN_PX },
    );
    if (!still) return null;
    const focused = await page.screenshot({ clip: box, animations: "disabled" });
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.waitForTimeout(200);
    const unfocused = await page.screenshot({ clip: box, animations: "disabled" });
    await page.evaluate((sel) => (document.querySelector(sel) as HTMLElement | null)?.focus({ preventScroll: true }), selector);

    // Decode and compare in Node: shipping pixel arrays out of the page as
    // JSON was most of the cost.
    const a = decodePng(focused);
    const b = decodePng(unfocused);
    let changed = -1;
    if (a.data.length === b.data.length) {
      changed = 0;
      for (let i = 0; i < a.data.length; i += 4) {
        if (Math.abs(a.data[i] - b.data[i]) > INDICATOR_TOLERANCE ||
            Math.abs(a.data[i + 1] - b.data[i + 1]) > INDICATOR_TOLERANCE ||
            Math.abs(a.data[i + 2] - b.data[i + 2]) > INDICATOR_TOLERANCE) changed++;
      }
    }
    if (changed < 0) return null;
    return changed >= INDICATOR_MIN_PIXELS;
  } catch {
    return null;
  }
}

/** Effective opacity (product over ancestors) the element must reach. */
const OPAQUE_ENOUGH = 0.95;
const OPAQUE_WAIT_MS = 1_500;

/** Wait until the element and its ancestors are effectively opaque; false if never. */
export async function waitUntilOpaque(page: Page, selector: string): Promise<boolean> {
  const started = Date.now();
  for (;;) {
    const opacity = await page
      .evaluate((sel) => {
        let o = 1;
        for (let a = document.querySelector(sel); a; a = a.parentElement) {
          const cs = getComputedStyle(a);
          if (cs.visibility !== "visible") return 0;
          o *= parseFloat(cs.opacity);
        }
        return o;
      }, selector)
      .catch(() => 0);
    if (opacity >= OPAQUE_ENOUGH) return true;
    if (Date.now() - started > OPAQUE_WAIT_MS) return false;
    await page.waitForTimeout(100);
  }
}

/**
 * A4.3 — resolve focus-visible for one stop from the style diff.
 *
 * `null` whenever we did not measure or cannot compare (no baseline for this
 * selector, or the focused signature is missing). Only a real difference
 * between the keyboard-focused style and the unfocused baseline yields
 * `true`; equal styles yield `false`. We never guess: keyboard.py turns a
 * stray `false` into a fabricated SC 2.4.7 failure, and the gate forbids it.
 */
function resolveFocusVisible(
  measureStyle: boolean,
  baseline: Map<string, string>,
  selector: string,
  focusedSig: string | null,
): boolean | null {
  if (!measureStyle) return null;
  if (focusedSig === null) return null;
  const base = baseline.get(selector);
  if (base === undefined) return null;
  return base !== focusedSig;
}

/* ----------------------------------------------------------------------- *
 * In-page functions. These are serialised and run inside the browser, so
 * they may only use browser globals and their own arguments — no closures
 * over module scope.
 * ----------------------------------------------------------------------- */

/** Describe document.activeElement. Runs in the page. */
function describeActiveElement(args: {
  rovingRoles: string[];
  styleProps: string[] | null;
}): ActiveDescriptor {
  const { styleProps } = args;
  const el = document.activeElement as HTMLElement | null;
  const leftPage =
    el === null || el === document.body || el === document.documentElement;
  if (leftPage) {
    return {
      leftPage: true,
      isIframe: false,
      selector: "",
      bbox: null,
      role: null,
      accessible_name: null,
      tabindex: null,
      dom_order: null,
      style_sig: null,
    };
  }

  const isIframe = el.tagName === "IFRAME";

  // A stable-ish CSS selector: prefer id, else a nth-of-type path from the
  // nearest id'd ancestor. Good enough to re-query and to read in a report.
  const selector = cssPath(el);

  const rect = el.getBoundingClientRect();
  const bbox =
    rect.width === 0 && rect.height === 0
      ? null
      : { x: rect.x, y: rect.y, width: rect.width, height: rect.height };

  const roleAttr = el.getAttribute("role");
  const role = roleAttr && roleAttr.trim() ? roleAttr.trim() : null;

  // accessible_name: best-effort, not a full accName computation. aria-label,
  // then aria-labelledby target text, then trimmed text content. Python treats
  // this as advisory; it keys judgments off the selector.
  let accessibleName: string | null = null;
  const ariaLabel = el.getAttribute("aria-label");
  if (ariaLabel && ariaLabel.trim()) {
    accessibleName = ariaLabel.trim();
  } else {
    const labelledby = el.getAttribute("aria-labelledby");
    if (labelledby) {
      const text = labelledby
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent ?? "")
        .join(" ")
        .trim();
      if (text) accessibleName = text;
    }
    if (!accessibleName) {
      const t = (el.textContent ?? "").trim().replace(/\s+/g, " ");
      if (t) accessibleName = t.slice(0, 120);
    }
  }

  // The AUTHORED tabindex attribute, parsed. null when the attribute is
  // absent — never the computed .tabIndex, which is 0 for a plain <button>
  // and would make every control look like an authored tab-order override.
  const tiAttr = el.getAttribute("tabindex");
  let tabindex: number | null = null;
  if (tiAttr !== null) {
    const n = parseInt(tiAttr, 10);
    tabindex = Number.isNaN(n) ? null : n;
  }

  // dom_order: index among all elements in document order.
  const all = Array.from(document.querySelectorAll("*"));
  const domOrder = all.indexOf(el);

  // A4.3: computed-style signature while this element is keyboard-focused.
  let styleSig: string | null = null;
  if (styleProps) {
    const cs = getComputedStyle(el);
    styleSig = styleProps.map((p) => cs.getPropertyValue(p)).join("|");
  }

  return {
    leftPage: false,
    isIframe,
    selector,
    bbox,
    role,
    accessible_name: accessibleName,
    tabindex,
    dom_order: domOrder < 0 ? null : domOrder,
    style_sig: styleSig,
  };

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
      const sameTag = Array.from(parent.children).filter(
        (c) => c.tagName === cur!.tagName,
      );
      if (sameTag.length === 1) {
        parts.unshift(tag);
      } else {
        const idx = sameTag.indexOf(cur) + 1;
        parts.unshift(`${tag}:nth-of-type(${idx})`);
      }
      cur = parent;
    }
    return parts.join(" > ");
  }
}

/**
 * A4.3 baseline: computed-style signatures of every focusable element while
 * nothing is focused. Keyed by the same cssPath describeActiveElement uses,
 * so the focused reading taken later lines up by selector. Runs in the page.
 */
function captureBaselineStyles(styleProps: string[]): Array<{ selector: string; sig: string }> {
  const FOCUSABLE =
    'a[href], button, input:not([type="hidden"]), select, textarea, [tabindex], [contenteditable="true"]';

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
      const sameTag = Array.from(parent.children).filter(
        (c) => c.tagName === cur!.tagName,
      );
      if (sameTag.length === 1) parts.unshift(tag);
      else parts.unshift(`${tag}:nth-of-type(${sameTag.indexOf(cur) + 1})`);
      cur = parent;
    }
    return parts.join(" > ");
  }

  // Make sure nothing is focused while we read the baseline.
  const active = document.activeElement as HTMLElement | null;
  if (active && typeof active.blur === "function") active.blur();

  const out: Array<{ selector: string; sig: string }> = [];
  const seen = new Set<string>();
  for (const el of Array.from(document.querySelectorAll(FOCUSABLE)) as HTMLElement[]) {
    const selector = cssPath(el);
    if (seen.has(selector)) continue;
    seen.add(selector);
    const cs = getComputedStyle(el);
    out.push({ selector, sig: styleProps.map((p) => cs.getPropertyValue(p)).join("|") });
  }
  return out;
}

/** Selectors of enabled, visible, Tab-focusable elements right now. Runs in the page. */
function focusableNow(): string[] {
  const FOCUSABLE =
    'a[href], button, input:not([type="hidden"]), select, textarea, [tabindex], [contenteditable="true"]';
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
  const out: string[] = [];
  for (const el of Array.from(document.querySelectorAll(FOCUSABLE)) as HTMLElement[]) {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if ((r.width === 0 && r.height === 0) || cs.visibility === "hidden" || cs.display === "none") continue;
    if ((el as HTMLButtonElement).disabled) continue;
    out.push(cssPath(el));
  }
  return out;
}

/** Classify focusable elements Tab never reached. Runs in the page. */
function classifyUnreached(args: {
  visited: string[];
  rovingRoles: string[];
  initiallyFocusable: string[];
}): UnreachedRegion[] {
  const { visited, rovingRoles } = args;
  const visitedSet = new Set(visited);
  const initially = new Set(args.initiallyFocusable);
  const FOCUSABLE =
    'a[href], button, input:not([type="hidden"]), select, textarea, [tabindex], [contenteditable="true"]';
  const NATIVE_INTERACTIVE = new Set(["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"]);
  const out: UnreachedRegion[] = [];

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
      const sameTag = Array.from(parent.children).filter(
        (c) => c.tagName === cur!.tagName,
      );
      if (sameTag.length === 1) parts.unshift(tag);
      else parts.unshift(`${tag}:nth-of-type(${sameTag.indexOf(cur) + 1})`);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function isVisible(el: HTMLElement): boolean {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (parseFloat(style.opacity) === 0) return false;
    return true;
  }

  function rovingAncestor(el: Element): Element | null {
    let cur: Element | null = el.parentElement;
    while (cur) {
      const role = cur.getAttribute("role");
      if (role && rovingRoles.includes(role.trim())) return cur;
      cur = cur.parentElement;
    }
    return null;
  }

  function isObscured(el: HTMLElement): boolean {
    const rect = el.getBoundingClientRect();
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) {
      return false; // off-screen is not the same as covered; don't guess
    }
    const top = document.elementFromPoint(cx, cy);
    if (!top) return false;
    return top !== el && !el.contains(top) && !top.contains(el);
  }

  // Note any open shadow roots as a blind spot: we cannot enumerate their
  // focusable content from the top document, so we must not claim the page is
  // fully covered.
  const shadowHosts = Array.from(document.querySelectorAll("*")).filter(
    (e) => (e as Element & { shadowRoot?: ShadowRoot }).shadowRoot,
  );
  for (const host of shadowHosts) {
    out.push({
      selector: cssPath(host),
      reason: "shadow-dom",
      detail: "open shadow root; its focusable content was not traversed",
    });
  }

  const candidates = Array.from(document.querySelectorAll(FOCUSABLE)) as HTMLElement[];
  for (const el of candidates) {
    const selector = cssPath(el);
    if (visitedSet.has(selector)) continue;
    if (!isVisible(el)) continue; // hidden things are not reachable by anyone
    if ((el as HTMLButtonElement | HTMLInputElement).disabled) continue;

    const tiAttr = el.getAttribute("tabindex");
    const ti = tiAttr === null ? null : parseInt(tiAttr, 10);

    // tabindex="-1": programmatically focusable, deliberately out of Tab order.
    if (ti !== null && ti < 0) {
      if (rovingAncestor(el)) {
        // Correct authoring — reachable with arrow keys. Never a failure.
        out.push({
          selector,
          reason: "arrow-navigable",
          detail: "tabindex=-1 inside a roving-tabindex widget",
        });
      } else {
        // Author removed it from Tab order outside a known pattern. Could be
        // intentional (skip-link target) or a bug; we cannot tell, so cantTell.
        out.push({
          selector,
          reason: "unknown",
          detail: "tabindex=-1 with no roving-tabindex ancestor",
        });
      }
      continue;
    }

    // Not focusable when the traversal started (disabled, hidden, not yet
    // rendered): Tab skipping it then proves nothing about it now.
    if (!initially.has(selector)) {
      out.push({ selector, reason: "unknown", detail: "became focusable during the traversal (dynamic state)" });
      continue;
    }

    // A natively-interactive, visible, enabled control with no negative
    // tabindex that Tab never reached is a genuine barrier.
    if (NATIVE_INTERACTIVE.has(el.tagName)) {
      if (isObscured(el)) {
        out.push({ selector, reason: "obscured", detail: "covered by another element at its centre" });
      } else {
        out.push({ selector, reason: "not-focusable", detail: "visible interactive control not reachable by Tab" });
      }
      continue;
    }

    // A [tabindex="0"] div etc. that wasn't reached: can't attribute safely.
    out.push({ selector, reason: "unknown", detail: "focusable element not reached by Tab" });
  }

  return out;
}
