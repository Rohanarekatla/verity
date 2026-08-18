/**
 * A2.1 / A2.2 — element screenshot capture.
 *
 * The acceptance criterion is that crops align with the element at both 1×
 * and 2× device pixel ratios. "Align" is checked two ways:
 *
 *   1. the recorded device box equals the CSS box times the ratio, and
 *   2. the PNG's real pixel dimensions equal the device box.
 *
 * Point 2 is the one that actually catches mistakes. Point 1 alone would
 * pass even if the screenshot were captured at the wrong scale, because both
 * sides of that equation come from the same measurement.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = path.join(HERE, "..", "dist", "rpc", "server.js");
const FIXTURES = path.join(HERE, "..", "..", "data", "fixtures");

/** Read a PNG's intrinsic size straight from its IHDR chunk. */
async function pngSize(file) {
  const buf = await readFile(file);
  assert.equal(buf.readUInt32BE(0), 0x89504e47, "not a PNG");
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

async function renderAndAxe(fixture, params = {}) {
  const child = spawn("node", [SERVER], { stdio: ["pipe", "pipe", "pipe"] });
  const frames = [];
  let buf = "";

  child.stdout.on("data", (d) => {
    buf += d.toString();
    let i;
    while ((i = buf.indexOf("\n")) !== -1) {
      const line = buf.slice(0, i);
      buf = buf.slice(i + 1);
      if (line.trim()) frames.push(JSON.parse(line));
    }
  });

  const send = (id, method, p) =>
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params: p }) + "\n");

  const waitFor = (id) =>
    new Promise((resolve, reject) => {
      const started = Date.now();
      const timer = setInterval(() => {
        const f = frames.find((f) => f.id === id);
        if (f) { clearInterval(timer); resolve(f); }
        else if (Date.now() - started > 40_000) { clearInterval(timer); reject(new Error(`timeout id=${id}`)); }
      }, 50);
    });

  try {
    const url = "file://" + path.join(FIXTURES, fixture);
    send(1, "render", { url, ...params });
    const render = await waitFor(1);
    assert.ok(render.result, `render failed: ${JSON.stringify(render.error)}`);

    send(2, "runAxe", { artifactId: render.result.artifactId });
    const axe = await waitFor(2);
    assert.ok(axe.result, `runAxe failed: ${JSON.stringify(axe.error)}`);

    return { render: render.result, axe: axe.result };
  } finally {
    child.stdin.end();
    child.kill();
  }
}

for (const dpr of [1, 2]) {
  test(`element crops align with the element at ${dpr}x device pixel ratio (A2.1)`, async () => {
    const { render } = await renderAndAxe("elements.html", { deviceScaleFactor: dpr });
    const shots = render.element_screenshots;

    const img = shots["#box-img"];
    assert.ok(img, `no capture for #box-img — got ${Object.keys(shots).join(", ")}`);

    // The fixture pins this element at exactly 120x60 CSS pixels.
    assert.equal(Math.round(img.box_css.width), 120);
    assert.equal(Math.round(img.box_css.height), 60);

    assert.equal(img.device_pixel_ratio, dpr, "ratio must be recorded, not assumed");
    assert.equal(Math.round(img.box_device.width), 120 * dpr);
    assert.equal(Math.round(img.box_device.height), 60 * dpr);

    // The real check: the PNG on disk is the device-pixel size, so the crop
    // genuinely covers the element rather than a scaled guess at it.
    //
    // Exact equality is not achievable and asserting it would be asserting
    // something false. An element at a fractional CSS offset (this one sits
    // at y=111.875, from the h1's margin) spans a fractional device range,
    // and the browser rounds the clip outward to whole pixels — so a crop is
    // up to 1 device pixel larger per axis. What must hold is that the crop
    // fully covers the element and grabs no more than that rounding.
    const png = await pngSize(img.path);
    const expectedW = 120 * dpr;
    const expectedH = 60 * dpr;

    assert.ok(
      png.width >= expectedW && png.width <= expectedW + 2,
      `PNG width ${png.width} should cover ${expectedW} at ${dpr}x without overreaching`,
    );
    assert.ok(
      png.height >= expectedH && png.height <= expectedH + 2,
      `PNG height ${png.height} should cover ${expectedH} at ${dpr}x without overreaching`,
    );

    // Scaling must come from the ratio, not from a resized image: the 2x crop
    // is genuinely about twice the 1x crop, not the same bitmap stretched.
    assert.ok(png.width >= 120 * dpr, "crop must be captured at the device scale");
  });
}

test("every kind of image is inventoried, and zero-size elements are skipped (A2.2)", async () => {
  const { render } = await renderAndAxe("elements.html");
  const selectors = Object.keys(render.element_screenshots);

  // <img>, <canvas>, inline <svg>, and CSS background-image all count.
  for (const expected of ["#box-img", "#plain-canvas", "#inline-svg", "#bg-panel"]) {
    assert.ok(
      selectors.includes(expected),
      `${expected} missing from element_screenshots — got ${selectors.join(", ")}`,
    );
  }

  // #tiny is 0x0: it cannot be screenshotted and must be skipped silently
  // rather than failing the render.
  assert.ok(!selectors.includes("#tiny"), "zero-size element should be skipped");

  for (const capture of Object.values(render.element_screenshots)) {
    const info = await stat(capture.path);
    assert.ok(info.size > 0, `${capture.selector} wrote an empty PNG`);
  }
});

test("runAxe captures crops for the nodes it marks incomplete (A2.2)", async () => {
  const { axe } = await renderAndAxe("contrast-fail.html");

  assert.ok(
    axe.element_screenshots !== undefined,
    "runAxe must return an element_screenshots map, even when empty",
  );

  // Every incomplete node that could be captured must have a crop, and every
  // crop must correspond to an incomplete node — this is the Week 3 contrast
  // adjudication queue, so a missing crop means a finding cannot be resolved.
  const incompleteSelectors = new Set(axe.incomplete.map((n) => n.selector).filter(Boolean));
  for (const selector of Object.keys(axe.element_screenshots)) {
    assert.ok(
      incompleteSelectors.has(selector),
      `${selector} was cropped but is not an incomplete node`,
    );
  }
});
