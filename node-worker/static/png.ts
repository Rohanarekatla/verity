/**
 * Minimal PNG decoder for our own screenshots.
 *
 * Profiling showed the contrast sampler spent ~85% of its time not taking
 * screenshots but shipping them: each PNG was decoded inside the page and its
 * RGBA array returned to Node as JSON (~900 KB per element, ~590 ms). Decoding
 * here instead removes the round trip. Chromium's screenshots are 8-bit,
 * non-interlaced, truecolour (type 2) or truecolour+alpha (type 6), so that is
 * all this handles — anything else throws, and callers treat a throw as "could
 * not sample", never as a measurement. Dependency-free, like the rest of the
 * worker.
 */

import { inflateSync } from "node:zlib";

export interface Rgba {
  width: number;
  height: number;
  /** RGBA, 4 bytes per pixel, row-major. */
  data: Uint8Array;
}

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

export function decodePng(buf: Buffer): Rgba {
  if (buf.length < 8 || !buf.subarray(0, 8).equals(SIGNATURE)) throw new Error("not a PNG");
  let width = 0;
  let height = 0;
  let colourType = -1;
  const idat: Buffer[] = [];
  for (let off = 8; off < buf.length; ) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString("latin1", off + 4, off + 8);
    const body = buf.subarray(off + 8, off + 8 + len);
    if (type === "IHDR") {
      width = body.readUInt32BE(0);
      height = body.readUInt32BE(4);
      const bitDepth = body[8];
      colourType = body[9];
      const interlace = body[12];
      if (bitDepth !== 8 || interlace !== 0 || (colourType !== 2 && colourType !== 6)) {
        throw new Error(`unsupported PNG (depth ${bitDepth}, colour ${colourType}, interlace ${interlace})`);
      }
    } else if (type === "IDAT") {
      idat.push(body);
    } else if (type === "IEND") {
      break;
    }
    off += 12 + len;
  }
  const bpp = colourType === 6 ? 4 : 3;
  const stride = width * bpp;
  const raw = inflateSync(Buffer.concat(idat));
  const rows = new Uint8Array(height * stride);
  let prev = new Uint8Array(stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const out = rows.subarray(y * stride, (y + 1) * stride);
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? out[i - bpp] : 0;
      const b = prev[i];
      const c = i >= bpp ? prev[i - bpp] : 0;
      let v = line[i];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a);
        const pb = Math.abs(p - b);
        const pc = Math.abs(p - c);
        v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      } else if (filter !== 0) {
        throw new Error(`bad PNG filter ${filter}`);
      }
      out[i] = v & 0xff;
    }
    prev = out;
  }
  if (bpp === 4) return { width, height, data: rows };
  const data = new Uint8Array(width * height * 4);
  for (let p = 0, q = 0; p < width * height; p++, q += 3) {
    data[p * 4] = rows[q];
    data[p * 4 + 1] = rows[q + 1];
    data[p * 4 + 2] = rows[q + 2];
    data[p * 4 + 3] = 255;
  }
  return { width, height, data };
}
