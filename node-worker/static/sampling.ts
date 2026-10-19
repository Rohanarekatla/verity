/**
 * Contrast pixel sampling (A3.1–A3.3).
 *
 * When axe marks a text element's contrast `incomplete` — text over an image,
 * gradient, or translucent layer — static analysis cannot know the colour
 * behind the glyphs. So we look at the actual rendered pixels.
 *
 * The doctrine, from the Bible: **the model localises, the maths decides.**
 * Nothing here computes a contrast ratio or a verdict. It reports, from real
 * pixels, the foreground colour and the set of background colours behind the
 * text. The deterministic WCAG maths on the Python side
 * (verity/agents/contrast.py) turns those into a worst-case ratio. A wrong
 * sample would make an authoritative finding wrong, so this stays purely
 * mechanical: measure, don't judge.
 *
 * How the glyphs are found — screenshots, not a colour guess.
 *
 *   A3.1 — screenshot the element's box as rendered ("with text").
 *   A3.2 — make ITS text transparent (color, -webkit-text-fill-color, SVG
 *          fill; transitions off) and shoot again. The pixels that differ ARE
 *          its glyphs, anti-aliased edges included.
 *   A3.3 — make EVERY text on the page transparent and shoot again: that is
 *          what sits behind the glyphs, without a neighbour's text (a
 *          ticker's incoming line, the next table cell) passing for
 *          background. Background colours are read there, directly under the
 *          glyphs, and returned as a per-colour SET with counts so worst-case
 *          contrast is taken over what is really behind the letters.
 *
 *   Two repeat shots guard the measurement: the all-hidden shot is taken
 *   twice and the with-text shot is retaken at the end. If either pair
 *   disagrees, the page moved (image loading, carousel, video, animation) and
 *   the region is flagged ambiguous rather than measured.
 *
 * This replaced an earlier colour-distance split (pixel near the CSS colour =
 * text, else background). End-to-end testing on real sites showed why it was
 * wrong: thin anti-aliased strokes are mostly *blended* pixels, far from the
 * CSS colour, so they were counted as "background" and worst-case landed on
 * them — apple.com's blue-on-grey "Buy" links (5.3:1) were failed at 1.8:1.
 *
 * Pixels are read via a throwaway canvas inside the page, loading each
 * screenshot as a same-origin data URL. That avoids both a PNG-decode
 * dependency and the cross-origin canvas taint that a live background image
 * would otherwise cause — the screenshot is raster we own.
 */

import type { Page } from "playwright";
import { waitUntilOpaque } from "../interaction/traverse.js";
import { decodePng } from "./png.js";

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

export interface BackgroundSample extends Rgb {
  /** Number of background pixels of exactly this colour. */
  count: number;
}

export interface RegionSample {
  selector: string;
  /** Computed foreground (text) colour from CSS (SVG: fill). */
  foreground: Rgb;
  device_pixel_ratio: number;
  /** Distinct background colours behind the text, most common first. */
  background_samples: BackgroundSample[];
  /**
   * Glyph pixels whose rendered colour is close to `foreground` — the solid
   * cores of the letters. Zero means the CSS colour is not what the text is
   * painted in (translucency, opacity, gradient or clipped text), and the
   * adjudicator must not compute a ratio from it.
   */
  text_pixel_count: number;
  background_pixel_count: number;
  /** False when the element could not be sampled (absent, zero-size, offscreen). */
  sampled: boolean;
  /**
   * True when the measurement cannot be trusted: the background moved between
   * two captures (animation, video, carousel), or no glyph pixel matched the
   * foreground colour. The adjudicator keeps an ambiguous region
   * `needs_review` — a pass or a fail from it would describe pixels that are
   * not reliably on screen.
   */
  ambiguous: boolean;
  /**
   * BC-A2 — computed font size (CSS px) of the text inside the element, or
   * null when it could not be read. SC 1.4.3's threshold depends on it: 3:1
   * for large text (>= 24px, or >= 18.66px at weight >= 700), 4.5:1 otherwise.
   * Measured only — which threshold applies is decided on the Python side.
   */
  font_size_px: number | null;
  /** BC-A2 — computed numeric font weight (100–900), or null when unread. */
  font_weight: number | null;
  /**
   * BC-A2 — true only when every text node inside the element renders at the
   * same size and weight. A heading with a small inline `<span>` is one region
   * with two thresholds; reporting a single size for it would misapply one of
   * them, so a mixed region is reported as such and stays `cantTell`.
   */
  font_uniform: boolean;
  /**
   * The text is inside aria-hidden="true" (itself or an ancestor). Hidden
   * from assistive technology usually means decorative — a background
   * pattern, a duplicate of visible text — and pure decoration is exempt
   * from SC 1.4.3. Measured only; the adjudicator decides what it means.
   */
  aria_hidden: boolean;
}

/** A glyph pixel within this RGB distance of the foreground counts as a solid core. */
const TEXT_DISTANCE = 60;

/**
 * Two captures' pixels are "the same" within this per-channel tolerance. PNG
 * screenshots are lossless, but GPU compositing can wobble a unit or two.
 */
const SAME_PIXEL_TOLERANCE = 6;

/**
 * A "without text" shot that differs from a second one in more than this
 * fraction of pixels means the background is moving.
 */
const MAX_MOVING_FRACTION = 0.002;

/** Growth of each text line box (CSS px) when bounding where glyphs can be. */
const TEXT_BOX_SLACK_CSS_PX = 2;

/** Minimum glyph pixels in the text colour, absolute and as a share of all glyph pixels. */
const MIN_CORE_PIXELS = 6;
const MIN_CORE_FRACTION = 0.03;

/** How many top background colours to return. */
const MAX_SAMPLES = 32;

/**
 * Background is read directly under the glyphs, grown by this much (CSS px,
 * scaled by devicePixelRatio) to cover the anti-aliased edge. Not further: a
 * dark border or icon a few pixels from the letters is not what the text is
 * read against, and the element's far corners (a pill button's rounded
 * corners showing the page) even less so.
 */
const NEIGHBOURHOOD_CSS_PX = 1;

/**
 * Marker attributes + stylesheet used to hide text for a shot: one element's
 * (to find its glyphs) or the whole page's (to see what is behind them
 * without a neighbour's text — a ticker's incoming line, the next table
 * cell — being mistaken for background).
 */
const HIDE_ATTR = "data-verity-hide-text";
const FREEZE_ATTR = "data-verity-freeze";
const HIDE_ALL_ATTR = "data-verity-hide-all-text";
const HIDE_STYLE_ID = "verity-hide-text-style";
const HIDE_CSS = `
html[${FREEZE_ATTR}] *, html[${FREEZE_ATTR}] *::before, html[${FREEZE_ATTR}] *::after {
  transition: none !important;
}
[${HIDE_ATTR}], [${HIDE_ATTR}] *,
html[${HIDE_ALL_ATTR}] *, html[${HIDE_ALL_ATTR}] *::before, html[${HIDE_ALL_ATTR}] *::after {
  color: transparent !important;
  -webkit-text-fill-color: transparent !important;
  text-shadow: none !important;
  text-decoration-color: transparent !important;
  caret-color: transparent !important;
  transition: none !important;
}
[${HIDE_ATTR}]:is(text, tspan, textPath), [${HIDE_ATTR}] :is(text, tspan, textPath),
html[${HIDE_ALL_ATTR}] :is(text, tspan, textPath) {
  fill: transparent !important;
  stroke: transparent !important;
}`;

function parseCssColor(value: string): { rgb: Rgb; alpha: number } | null {
  // Computed styles come back as "rgb(r, g, b)" or "rgba(r, g, b, a)".
  const m = value.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(/[,\s/]+/).filter(Boolean).map((s) => parseFloat(s.trim()));
  if (parts.length < 3 || parts.slice(0, 3).some((n) => Number.isNaN(n))) return null;
  return {
    rgb: { r: Math.round(parts[0]), g: Math.round(parts[1]), b: Math.round(parts[2]) },
    alpha: parts.length >= 4 && !Number.isNaN(parts[3]) ? parts[3] : 1,
  };
}

function distance(a: Rgb, b: Rgb): number {
  const dr = a.r - b.r;
  const dg = a.g - b.g;
  const db = a.b - b.b;
  return Math.sqrt(dr * dr + dg * dg + db * db);
}

interface Raster {
  width: number;
  height: number;
  data: ArrayLike<number>;
}

interface Clip {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * The element's box, measured ONCE and rounded outward to whole CSS pixels.
 * Every shot uses this same clip: re-measuring per shot lets the box drift
 * (an SVG <text> with a transparent fill reports a different box), and
 * rasters that do not line up cannot be diffed.
 *
 * Viewport coordinates when the box fits on screen after scrolling to it —
 * the fast path, and one that never resizes the viewport (full-page capture
 * can, which reflows anything sized in vh). Page coordinates with full-page
 * capture otherwise.
 */
interface TextBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

async function measureClip(
  page: Page,
  selector: string,
): Promise<(Clip & { fullPage: boolean; textBoxes: TextBox[] }) | null> {
  try {
    // Instant, not smooth: with scroll-behavior:smooth an animated scroll
    // leaves the box measured below somewhere the shots are not.
    const placed = await page.evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" as ScrollBehavior });
      return true;
    }, selector);
    if (!placed) return null;
  } catch {
    return null;
  }
  return page
    .evaluate(async (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      // Stable position: two readings a frame apart must agree.
      const first = el.getBoundingClientRect();
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const r = el.getBoundingClientRect();
      if (Math.abs(first.left - r.left) > 0.5 || Math.abs(first.top - r.top) > 0.5) return null;
      // Covered (a sticky header, an overlay): the pixels would be the
      // cover's, not the text's background.
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (hit && !(hit === el || el.contains(hit) || hit.contains(el))) return null;
      const fits = r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight;
      const ox = fits ? 0 : window.scrollX;
      const oy = fits ? 0 : window.scrollY;
      const x = Math.floor(r.left + ox);
      const y = Math.floor(r.top + oy);
      const width = Math.ceil(r.right + ox) - x;
      const height = Math.ceil(r.bottom + oy) - y;
      if (width <= 0 || height <= 0) return null;

      // The text's own line boxes, relative to the clip. Glyph differences are
      // only accepted inside these (grown slightly for overhang): anything
      // that changes outside them — a pill's anti-aliased corners rastered a
      // hair differently between shots — is not text, and once counted as
      // "glyphs" it made the page colour behind the corners the background.
      const textBoxes: Array<{ x: number; y: number; width: number; height: number }> = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.textContent || !n.textContent.trim()) continue;
        range.selectNodeContents(n);
        for (const b of Array.from(range.getClientRects())) {
          if (b.width <= 0 || b.height <= 0) continue;
          textBoxes.push({ x: b.left + ox - x, y: b.top + oy - y, width: b.width, height: b.height });
        }
      }
      return { x, y, width, height, fullPage: !fits, textBoxes };
    }, selector)
    .catch(() => null);
}

/** Screenshot a fixed region and decode its RGBA pixels (in Node — see png.ts). */
async function shoot(page: Page, clip: Clip & { fullPage: boolean }): Promise<Raster | null> {
  try {
    const { fullPage, x, y, width, height } = clip;
    // Animations are NOT disabled: Playwright's "disabled" fast-forwards or
    // cancels them per shot, which hides real motion from the moving-page
    // guard (stripe.com's number ticker measured as if it stood still).
    const buf = await page.screenshot({ type: "png", fullPage, clip: { x, y, width, height } });
    return decodePng(buf);
  } catch {
    return null;
  }
}

/**
 * Toggle a hide-text marker (installing the stylesheet once): on one element,
 * or — with `selector` null — on the whole page.
 */
async function setTextHidden(
  page: Page,
  selector: string | null,
  hidden: boolean,
  rootAttr: string = HIDE_ALL_ATTR,
): Promise<boolean> {
  return page
    .evaluate(
      ({ sel, hidden, attr, styleId, css }) => {
        const el = sel === null ? document.documentElement : document.querySelector(sel);
        if (!el) return false;
        if (!document.getElementById(styleId)) {
          const style = document.createElement("style");
          style.id = styleId;
          style.textContent = css;
          document.head.appendChild(style);
        }
        if (hidden) el.setAttribute(attr, "");
        else el.removeAttribute(attr);
        // No frame wait: a screenshot always renders the current style, and
        // two animation frames per toggle (six toggles) were a third of the
        // sampler's time.
        return true;
      },
      {
        sel: selector,
        hidden,
        attr: selector === null ? rootAttr : HIDE_ATTR,
        styleId: HIDE_STYLE_ID,
        css: HIDE_CSS,
      },
    )
    .catch(() => false);
}

/** Read foreground, DPR and fonts from the live element. */
async function readMeta(
  page: Page,
  selector: string,
): Promise<{ color: string; dpr: number; fonts: string[]; paintMismatch: boolean; ariaHidden: boolean } | null> {
  return page
    .evaluate((sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return null;

      // BC-A2: the font of every non-blank text node in the element, read from
      // its parent's computed style (text nodes have no style of their own).
      const fonts = new Set<string>();
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.textContent || !n.textContent.trim() || !n.parentElement) continue;
        const cs = window.getComputedStyle(n.parentElement);
        fonts.add(`${parseFloat(cs.fontSize)}|${parseInt(cs.fontWeight, 10)}`);
      }
      // No text node at all (e.g. text drawn by CSS content) — fall back to the
      // element's own style, which is what that text inherits.
      if (fonts.size === 0) {
        const cs = window.getComputedStyle(el);
        fonts.add(`${parseFloat(cs.fontSize)}|${parseInt(cs.fontWeight, 10)}`);
      }

      // SVG text is painted with `fill`, not `color` — reading `color` there
      // returns the inherited CSS colour (often black) for white glyphs, and the
      // ratio is then computed against a colour that is not on screen. A fill
      // that is not a plain colour (none, url(#gradient)) yields no foreground.
      const cs = window.getComputedStyle(el);
      const color = el instanceof SVGElement ? cs.fill : cs.color;

      // Text painted by something other than `color`: background-clip:text
      // (the glyphs show the background image — apple.com's tiles) or a
      // -webkit-text-fill-color that differs from color. The CSS colour is
      // then not what is on screen.
      let paintMismatch = false;
      const painted = [el, ...Array.from(el.querySelectorAll("*"))];
      for (const node of painted) {
        const s = window.getComputedStyle(node);
        const clip = `${s.backgroundClip} ${(s as CSSStyleDeclaration & { webkitBackgroundClip?: string }).webkitBackgroundClip ?? ""}`;
        const fill = s.getPropertyValue("-webkit-text-fill-color");
        if (clip.includes("text") || (fill && fill !== s.color)) {
          paintMismatch = true;
          break;
        }
      }
      for (let a: Element | null = el; a && !paintMismatch; a = a.parentElement) {
        const s = window.getComputedStyle(a);
        const clip = `${s.backgroundClip} ${(s as CSSStyleDeclaration & { webkitBackgroundClip?: string }).webkitBackgroundClip ?? ""}`;
        if (clip.includes("text")) paintMismatch = true;
      }

      return {
        color,
        dpr: window.devicePixelRatio,
        fonts: [...fonts],
        paintMismatch: el instanceof SVGElement ? false : paintMismatch,
        ariaHidden: el.closest('[aria-hidden="true"]') !== null,
      };
    }, selector)
    .catch(() => null);
}

/**
 * Collapse the per-text-node fonts to one size/weight pair. When they differ,
 * the smallest size (and its weight) is reported for the record, but
 * `uniform` is false so the adjudicator does not pick a threshold from it.
 */
function smallestFont(fonts: string[]): { size: number | null; weight: number | null; uniform: boolean } {
  const parsed = fonts
    .map((f) => f.split("|").map(Number))
    .filter(([s, w]) => Number.isFinite(s) && s > 0 && Number.isFinite(w))
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (parsed.length === 0) return { size: null, weight: null, uniform: false };
  return { size: parsed[0][0], weight: parsed[0][1], uniform: parsed.length === 1 && fonts.length === 1 };
}

function differs(a: ArrayLike<number>, b: ArrayLike<number>, i: number): boolean {
  return (
    Math.abs(a[i] - b[i]) > SAME_PIXEL_TOLERANCE ||
    Math.abs(a[i + 1] - b[i + 1]) > SAME_PIXEL_TOLERANCE ||
    Math.abs(a[i + 2] - b[i + 2]) > SAME_PIXEL_TOLERANCE
  );
}

/**
 * Sample the pixels behind a text element (A3.1–A3.3).
 *
 * Returns `sampled: false` (with an empty sample set) rather than throwing
 * when the element cannot be read — a missing or invisible element is an
 * ordinary outcome on a real page, and the adjudicator treats an unsampleable
 * region as `needs_review`, not as a pass.
 */
export async function sampleRegion(page: Page, selector: string): Promise<RegionSample> {
  const empty: RegionSample = {
    selector,
    foreground: { r: 0, g: 0, b: 0 },
    device_pixel_ratio: 1,
    background_samples: [],
    text_pixel_count: 0,
    background_pixel_count: 0,
    sampled: false,
    ambiguous: false,
    font_size_px: null,
    font_weight: null,
    font_uniform: false,
    aria_hidden: false,
  };

  const meta = await readMeta(page, selector);
  if (!meta) return empty;
  const parsed = parseCssColor(meta.color);
  if (!parsed) return empty;
  const foreground = parsed.rgb;
  const font = smallestFont(meta.fonts);
  const base = { ...empty, foreground, device_pixel_ratio: meta.dpr, font_size_px: font.size,
                 font_weight: font.weight, font_uniform: font.uniform, aria_hidden: meta.ariaHidden };

  // Translucent text is painted as a blend with whatever is behind it, so the
  // CSS colour is not the on-screen colour. Measured honestly: not sampleable.
  if (parsed.alpha < 1 || meta.paintMismatch) return { ...base, ambiguous: true };

  // A region fading in (scroll-reveal) or out is painted in colours that are
  // not its own; measure it only once it is fully shown.
  // Scroll to it first (that is what triggers a reveal), then wait, then
  // measure the final box — a slide-in moves it while it fades.
  if (!(await measureClip(page, selector)) || !(await waitUntilOpaque(page, selector))) return base;
  const clip = await measureClip(page, selector);
  if (!clip) return base;
  // Five shots of one fixed clip:
  //   withText      — as rendered
  //   withoutSelf   — this element's text hidden   -> diff = its glyphs
  //   withoutAll    — every text on the page hidden -> what is behind them
  //   withoutAll2   — again                          -> background still?
  //   withText2     — restored                       -> page still?
  // Transitions are frozen for the whole hide/restore cycle. Without this,
  // restoring the page's text colours animated every `transition: all`
  // element back in from transparent, and the NEXT element sampled was
  // captured mid-fade (apple.com's "Buy" links: 1 glyph pixel, ratio 1.9).
  if (!(await setTextHidden(page, null, true, FREEZE_ATTR))) return base;
  let withText: Raster | null = null;
  let withoutSelf: Raster | null = null;
  let withoutAll: Raster | null = null;
  let withoutAll2: Raster | null = null;
  let withText2: Raster | null = null;
  try {
    withText = await shoot(page, clip);
    if (!withText || !(await setTextHidden(page, selector, true))) return base;
    withoutSelf = await shoot(page, clip);
    if (!(await setTextHidden(page, null, true))) return base;
    withoutAll = await shoot(page, clip);
    withoutAll2 = await shoot(page, clip);
    await setTextHidden(page, null, false);
    await setTextHidden(page, selector, false);
    withText2 = await shoot(page, clip);
  } finally {
    await setTextHidden(page, null, false);
    await setTextHidden(page, selector, false);
    await setTextHidden(page, null, false, FREEZE_ATTR);
  }
  if (!withText || !withoutSelf || !withoutAll || !withoutAll2 || !withText2) return base;

  const { width, height } = withText;
  const sameSize = (r: Raster) => r.width === width && r.height === height;
  if (![withoutSelf, withoutAll, withoutAll2, withText2].every(sameSize)) return { ...base, ambiguous: true };

  const n = width * height;
  const a = withText.data;
  const b = withoutSelf.data;
  const bg = withoutAll.data;

  // Moving page: an image finishing loading, a carousel advancing, video. If
  // either pair of identical-state shots disagrees, nothing measured between
  // them can be trusted.
  const changed = (x: ArrayLike<number>, y: ArrayLike<number>) => {
    let k = 0;
    for (let p = 0; p < n; p++) if (differs(x, y, p * 4)) k++;
    return k > n * MAX_MOVING_FRACTION;
  };
  const isMoving = changed(bg, withoutAll2.data) || changed(a, withText2.data);

  // Where text can be: its line boxes grown by TEXT_BOX_SLACK_CSS_PX for
  // italic overhang and anti-aliasing. With no boxes (text drawn some other
  // way), the whole clip is allowed, as before.
  const inText = new Uint8Array(n);
  if (clip.textBoxes.length === 0) inText.fill(1);
  const slack = TEXT_BOX_SLACK_CSS_PX;
  for (const t of clip.textBoxes) {
    const x0 = Math.max(0, Math.floor((t.x - slack) * meta.dpr));
    const y0 = Math.max(0, Math.floor((t.y - slack) * meta.dpr));
    const x1 = Math.min(width - 1, Math.ceil((t.x + t.width + slack) * meta.dpr));
    const y1 = Math.min(height - 1, Math.ceil((t.y + t.height + slack) * meta.dpr));
    for (let yy = y0; yy <= y1; yy++) inText.fill(1, yy * width + x0, yy * width + x1 + 1);
  }

  // A3.2: glyph pixels are exactly where hiding the text changed the raster,
  // inside the text's own boxes.
  const glyph = new Uint8Array(n);
  let glyphPixels = 0;
  let corePixels = 0;
  for (let p = 0; p < n; p++) {
    const i = p * 4;
    if (!inText[p] || !differs(a, b, i)) continue;
    glyph[p] = 1;
    glyphPixels++;
    if (distance({ r: a[i], g: a[i + 1], b: a[i + 2] }, foreground) < TEXT_DISTANCE) corePixels++;
  }

  // A3.3: background colours under the glyphs (plus the anti-aliased edge),
  // read from the shot with ALL text hidden.
  const reach = Math.max(1, Math.round(NEIGHBOURHOOD_CSS_PX * meta.dpr));
  const near = new Uint8Array(n);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!glyph[y * width + x]) continue;
      for (let yy = Math.max(0, y - reach); yy <= Math.min(height - 1, y + reach); yy++) {
        near.fill(1, yy * width + Math.max(0, x - reach), yy * width + Math.min(width - 1, x + reach) + 1);
      }
    }
  }
  const counts = new Map<number, number>(); // packed rgb -> count
  let bgPixels = 0;
  for (let p = 0; p < n; p++) {
    const i = p * 4;
    if (!near[p] || bg[i + 3] === 0) continue;
    bgPixels++;
    const key = (bg[i] << 16) | (bg[i + 1] << 8) | bg[i + 2];
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const samples: BackgroundSample[] = [...counts.entries()]
    .map(([key, count]) => ({ r: (key >> 16) & 0xff, g: (key >> 8) & 0xff, b: key & 0xff, count }))
    .sort((x, y) => y.count - x.count)
    .slice(0, MAX_SAMPLES);

  return {
    ...base,
    background_samples: samples,
    text_pixel_count: corePixels,
    background_pixel_count: bgPixels,
    sampled: glyphPixels > 0 && samples.length > 0,
    // Too few glyph pixels in the text colour: what is on screen is mostly
    // not that colour (a fade, a filter, a blend) — no verdict from it.
    ambiguous: isMoving || corePixels < Math.max(MIN_CORE_PIXELS, glyphPixels * MIN_CORE_FRACTION),
  };
}
