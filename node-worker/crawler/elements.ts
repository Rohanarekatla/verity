/**
 * A2.1 — element-level screenshot capture.
 *
 * Given a selector, produce a cropped PNG of that element plus its bounding
 * box in *both* coordinate systems:
 *
 *   - **CSS pixels** — what the DOM, `getBoundingClientRect()`, and every
 *     CSS selector talk in. Layout-relative and device-independent.
 *   - **Device pixels** — what the screenshot is actually made of. On a 2×
 *     display a 100×20 CSS-pixel element occupies 200×40 real pixels.
 *
 * Keeping both matters because the two consumers disagree. The Vision agent
 * is handed a PNG and reasons in device pixels; the contrast math (Week 3)
 * samples that PNG but must map results back to a CSS selector. Recording
 * only one and multiplying later is where off-by-a-scale-factor bugs come
 * from — so we record what we measured, alongside the factor we measured it
 * at, and never re-derive.
 *
 * The model never receives coordinates it did not get from here, and never
 * produces them. See ADR-0001 and the Bible's "the model localises, the math
 * decides".
 */

import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { Page } from "playwright";
import { log } from "../rpc/log.js";

/** A box in CSS pixels, relative to the top-left of the full page. */
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ElementCapture {
  selector: string;
  /** Path to the cropped PNG on disk. */
  path: string;
  /** Bounding box in CSS pixels — the coordinate system selectors live in. */
  box_css: Box;
  /** The same box in device pixels — the coordinate system the PNG lives in. */
  box_device: Box;
  /** The scale factor the two are related by, recorded rather than assumed. */
  device_pixel_ratio: number;
}

/** Elements smaller than this in either axis cannot be screenshotted. */
const MIN_DIMENSION_PX = 1;

/**
 * Measure an element's page-relative box in CSS pixels.
 *
 * `getBoundingClientRect()` is viewport-relative, so scroll offsets are added
 * back to make the box page-relative — matching the full-page screenshot the
 * crop is compared against. Returns null when the element is absent or has
 * no rendered area (`display:none`, zero-size, detached).
 */
async function measure(page: Page, selector: string): Promise<{ box: Box; dpr: number } | null> {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return {
      box: {
        x: r.left + window.scrollX,
        y: r.top + window.scrollY,
        width: r.width,
        height: r.height,
      },
      dpr: window.devicePixelRatio,
    };
  }, selector);
}

/** Stable, filesystem-safe filename for a selector of arbitrary shape. */
function fileNameFor(selector: string): string {
  const digest = createHash("sha256").update(selector).digest("hex").slice(0, 16);
  return `el-${digest}.png`;
}

/**
 * Capture one element. Returns null rather than throwing when the element
 * cannot be captured — a missing or invisible element is an ordinary
 * outcome on a real page, not an error worth failing a whole render over.
 */
export async function captureElement(
  page: Page,
  selector: string,
  outDir: string,
): Promise<ElementCapture | null> {
  let measured: { box: Box; dpr: number } | null;
  try {
    measured = await measure(page, selector);
  } catch {
    // Invalid selector syntax — axe emits selectors we cannot always re-parse.
    return null;
  }
  if (!measured) return null;

  const { box, dpr } = measured;
  if (box.width < MIN_DIMENSION_PX || box.height < MIN_DIMENSION_PX) return null;

  const path = join(outDir, fileNameFor(selector));
  try {
    const png = await page.locator(selector).first().screenshot({ type: "png" });
    await writeFile(path, png);
  } catch {
    // Off-screen, covered, or detached between measuring and shooting.
    return null;
  }

  return {
    selector,
    path,
    box_css: box,
    box_device: {
      x: box.x * dpr,
      y: box.y * dpr,
      width: box.width * dpr,
      height: box.height * dpr,
    },
    device_pixel_ratio: dpr,
  };
}

/**
 * Capture many elements, skipping the ones that cannot be captured.
 *
 * Sequential on purpose: each screenshot is a round trip to the browser, and
 * firing them concurrently on a page with hundreds of images produces
 * contention and flaky crops rather than speed.
 */
export async function captureElements(
  page: Page,
  selectors: string[],
  outDir: string,
): Promise<Record<string, ElementCapture>> {
  const out: Record<string, ElementCapture> = {};
  let skipped = 0;

  for (const selector of new Set(selectors)) {
    const capture = await captureElement(page, selector, outDir);
    if (capture) out[selector] = capture;
    else skipped += 1;
  }

  if (skipped > 0) {
    log.debug("element captures skipped", { skipped, captured: Object.keys(out).length });
  }
  return out;
}

/**
 * Every image-bearing element on the page, as selectors.
 *
 * Covers the four ways an image reaches the screen: `<img>`, `<canvas>`,
 * inline `<svg>`, and CSS `background-image`. The last is easy to forget and
 * is exactly where text-over-image contrast failures hide.
 */
export async function imageInventory(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    /** Shortest stable selector we can build for an element. */
    function selectorFor(el: Element): string | null {
      if (el.id) {
        const byId = `#${CSS.escape(el.id)}`;
        if (document.querySelectorAll(byId).length === 1) return byId;
      }
      // Fall back to a positional path — verbose, but unique and re-queryable.
      const parts: string[] = [];
      let node: Element | null = el;
      while (node && node.nodeType === 1 && parts.length < 8) {
        const parent: Element | null = node.parentElement;
        if (!parent) {
          parts.unshift(node.tagName.toLowerCase());
          break;
        }
        const siblings = Array.from(parent.children).filter(
          (c) => c.tagName === node!.tagName,
        );
        const idx = siblings.indexOf(node) + 1;
        parts.unshift(
          siblings.length > 1
            ? `${node.tagName.toLowerCase()}:nth-of-type(${idx})`
            : node.tagName.toLowerCase(),
        );
        node = parent;
      }
      const sel = parts.join(" > ");
      try {
        return document.querySelector(sel) === el ? sel : null;
      } catch {
        return null;
      }
    }

    const found = new Set<Element>();
    for (const el of Array.from(document.querySelectorAll("img, canvas, svg"))) {
      found.add(el);
    }
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const bg = window.getComputedStyle(el).backgroundImage;
      if (bg && bg !== "none" && bg.includes("url(")) found.add(el);
    }

    const selectors: string[] = [];
    for (const el of found) {
      const sel = selectorFor(el);
      if (sel) selectors.push(sel);
    }
    return selectors;
  });
}
