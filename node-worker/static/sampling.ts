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
): Promise<{ foreground: Rgb; width: number; height: number; data: number[]; dpr: number } | null> {
  // Foreground from computed style, plus a presence/size check.
  const meta = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return {
      color: window.getComputedStyle(el).color,
      dpr: window.devicePixelRatio,
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

  return { foreground, width: pixels.width, height: pixels.height, data: pixels.data, dpr: meta.dpr };
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
  };

  const read = await readElement(page, selector);
  if (!read) return empty;

  const { foreground, data, dpr } = read;
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
  };
}
