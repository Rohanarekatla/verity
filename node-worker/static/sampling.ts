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
 * Three steps:
 *   A3.1 — screenshot the element and read its pixels at device scale.
 *   A3.2 — glyph-region estimation: split probable text pixels from probable
 *          background pixels using the element's computed foreground colour.
 *   A3.3 — return a per-colour background sample SET with counts, not a single
 *          average, so worst-case contrast can be taken across the footprint.
 *
 * Pixels are read via a throwaway canvas inside the page, loading the
 * element screenshot as a same-origin data URL. That avoids both a PNG-decode
 * dependency and the cross-origin canvas taint that a live background image
 * would otherwise cause — the screenshot is raster we own.
 */

import type { Page } from "playwright";

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
  /** Computed foreground (text) colour from CSS. */
  foreground: Rgb;
  device_pixel_ratio: number;
  /** Distinct background colours behind the text, most common first. */
  background_samples: BackgroundSample[];
  text_pixel_count: number;
  background_pixel_count: number;
  /** False when the element could not be sampled (absent, zero-size, offscreen). */
  sampled: boolean;
  /**
   * True when the glyph/background split is unreliable — specifically when
   * "text" pixels outnumber background pixels. Real text is a thin minority of
   * an element's area, so this means background regions coloured near the
   * foreground (e.g. white text over a light patch of a busy image) were
   * swallowed into the text class and are missing from the samples. The
   * adjudicator must keep an ambiguous region `needs_review`, never pass it —
   * a missing worst-case background would otherwise hide a real failure. This
   * is the case the vision-localisation path (Week 10) is meant to resolve by
   * placing the text box precisely instead of guessing it by colour.
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
}

/**
 * A pixel is classified "text" when it sits within this Euclidean RGB distance
 * of the foreground colour, "background" otherwise. Anti-aliased glyph edges
 * blend the two; a moderate threshold keeps the glyph core and most of its
 * halo out of the background set without swallowing genuine background colour.
 * On a solid background the true colour still dominates by count, which is
 * what A3.2's exact-match acceptance turns on.
 */
const TEXT_DISTANCE = 60;

/** How many top background colours to return. */
const MAX_SAMPLES = 32;

function parseCssColor(value: string): Rgb | null {
  // Computed styles come back as "rgb(r, g, b)" or "rgba(r, g, b, a)".
  const m = value.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(",").map((s) => parseFloat(s.trim()));
  if (parts.length < 3 || parts.some((n) => Number.isNaN(n))) return null;
  return { r: Math.round(parts[0]), g: Math.round(parts[1]), b: Math.round(parts[2]) };
}

function distance(a: Rgb, b: Rgb): number {
  const dr = a.r - b.r;
  const dg = a.g - b.g;
  const db = a.b - b.b;
  return Math.sqrt(dr * dr + dg * dg + db * db);
}

/** Read an element's foreground colour and RGBA pixel data at device scale. */
async function readElement(
  page: Page,
  selector: string,
): Promise<{
  foreground: Rgb;
  width: number;
  height: number;
  data: number[];
  dpr: number;
  font: { size: number | null; weight: number | null; uniform: boolean };
} | null> {
  // Foreground from computed style, plus a presence/size check.
  const meta = await page.evaluate((sel) => {
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

    return {
      color: window.getComputedStyle(el).color,
      dpr: window.devicePixelRatio,
      fonts: [...fonts],
    };
  }, selector).catch(() => null);
  if (!meta) return null;

  const foreground = parseCssColor(meta.color);
  if (!foreground) return null;

  // Screenshot the element (device-scale raster we own), then read its pixels
  // via a scratch canvas in the page. A same-origin data URL is never tainted.
  let pngBase64: string;
  try {
    const buf = await page.locator(selector).first().screenshot({ type: "png" });
    pngBase64 = buf.toString("base64");
  } catch {
    return null;
  }

  const pixels = await page.evaluate(async (b64) => {
    const img = new Image();
    img.src = "data:image/png;base64," + b64;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, canvas.width, canvas.height);
    return { width: canvas.width, height: canvas.height, data: Array.from(d.data) };
  }, pngBase64).catch(() => null);
  if (!pixels) return null;

  return {
    foreground,
    width: pixels.width,
    height: pixels.height,
    data: pixels.data,
    dpr: meta.dpr,
    font: smallestFont(meta.fonts),
  };
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
  };

  const read = await readElement(page, selector);
  if (!read) return empty;

  const { foreground, data, dpr, font } = read;
  const counts = new Map<number, number>(); // packed rgb -> count
  let textPixels = 0;
  let bgPixels = 0;

  for (let i = 0; i < data.length; i += 4) {
    const alpha = data[i + 3];
    if (alpha === 0) continue; // fully transparent — not part of the rendered element
    const px: Rgb = { r: data[i], g: data[i + 1], b: data[i + 2] };
    if (distance(px, foreground) < TEXT_DISTANCE) {
      textPixels += 1; // A3.2: probable glyph pixel
      continue;
    }
    bgPixels += 1;
    const key = (px.r << 16) | (px.g << 8) | px.b;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  // A3.3: distinct background colours with counts, most common first.
  const samples: BackgroundSample[] = [...counts.entries()]
    .map(([key, count]) => ({
      r: (key >> 16) & 0xff,
      g: (key >> 8) & 0xff,
      b: key & 0xff,
      count,
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, MAX_SAMPLES);

  return {
    selector,
    foreground,
    device_pixel_ratio: dpr,
    background_samples: samples,
    text_pixel_count: textPixels,
    background_pixel_count: bgPixels,
    sampled: samples.length > 0,
    ambiguous: textPixels > bgPixels,
    font_size_px: font.size,
    font_weight: font.weight,
    font_uniform: font.uniform,
  };
}
