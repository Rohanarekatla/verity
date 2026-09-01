/**
 * Contrast pixel sampling (A3.1–A3.4).
 *
 * The load-bearing acceptance: on a solid background, the estimated
 * background colour must equal the CSS background *exactly* — a wrong sample
 * makes an authoritative contrast finding wrong. The rest guards the honest
 * failure modes: a near-foreground background is flagged ambiguous rather
 * than silently dropped, and an unsampleable element returns cleanly.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = path.join(HERE, "..", "dist", "rpc", "server.js");
const FIXTURES = path.join(HERE, "..", "..", "data", "fixtures");

function session() {
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
  const send = (id, method, params) =>
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  const waitFor = (id) =>
    new Promise((resolve, reject) => {
      const start = Date.now();
      const t = setInterval(() => {
        const f = frames.find((f) => f.id === id);
        if (f) { clearInterval(t); resolve(f); }
        else if (Date.now() - start > 30_000) { clearInterval(t); reject(new Error(`timeout id=${id}`)); }
      }, 40);
    });
  return { child, send, waitFor, close: () => { child.stdin.end(); child.kill(); } };
}

async function render(s, fixture) {
  s.send(1, "render", { url: "file://" + path.join(FIXTURES, fixture) });
  const r = await s.waitFor(1);
  assert.ok(r.result, `render failed: ${JSON.stringify(r.error)}`);
  return r.result.artifactId;
}

test("solid background is estimated exactly (A3.1/A3.2)", async () => {
  const s = session();
  try {
    const aid = await render(s, "contrast-sampling.html");
    s.send(2, "sampleRegion", { artifactId: aid, selector: "#solid-grey" });
    const r = (await s.waitFor(2)).result;

    assert.ok(r.sampled, "region should be sampleable");
    assert.deepEqual(r.foreground, { r: 255, g: 255, b: 255 }, "white text");

    // CSS background is #808080 = rgb(128,128,128). The most common background
    // sample must be exactly that — the whole point of A3.2.
    const top = r.background_samples[0];
    assert.deepEqual(
      { r: top.r, g: top.g, b: top.b },
      { r: 128, g: 128, b: 128 },
      "top background sample must equal the CSS background exactly",
    );
    assert.ok(top.count > 0, "sample carries a pixel count (A3.3)");
    assert.equal(r.ambiguous, false, "a solid background is not ambiguous");
  } finally {
    s.close();
  }
});

test("background samples are a set with counts, most common first (A3.3)", async () => {
  const s = session();
  try {
    const aid = await render(s, "contrast-sampling.html");
    s.send(2, "sampleRegion", { artifactId: aid, selector: "#solid-white" });
    const r = (await s.waitFor(2)).result;

    assert.ok(Array.isArray(r.background_samples));
    assert.deepEqual(
      { r: r.background_samples[0].r, g: r.background_samples[0].g, b: r.background_samples[0].b },
      { r: 255, g: 255, b: 255 },
      "black-on-white: dominant background is white",
    );
    // sorted by count, descending
    for (let i = 1; i < r.background_samples.length; i++) {
      assert.ok(r.background_samples[i - 1].count >= r.background_samples[i].count, "sorted by count");
    }
  } finally {
    s.close();
  }
});

test("text over a busy image is flagged ambiguous, not falsely passed", async () => {
  const s = session();
  try {
    const aid = await render(s, "contrast-sampling.html");
    s.send(2, "sampleRegion", { artifactId: aid, selector: "#over-image" });
    const r = (await s.waitFor(2)).result;

    // Light patches of the image are near-white, get swallowed into the text
    // class, and would otherwise hide a white-on-light failure. The flag keeps
    // the adjudicator honest (needs_review, never a silent pass).
    assert.equal(r.ambiguous, true, "near-foreground background must flag ambiguous");
    assert.ok(r.text_pixel_count > r.background_pixel_count, "text pixels dominate → the signal");
  } finally {
    s.close();
  }
});

test("an absent element returns sampled:false, not an error", async () => {
  const s = session();
  try {
    const aid = await render(s, "contrast-sampling.html");
    s.send(2, "sampleRegion", { artifactId: aid, selector: "#does-not-exist" });
    const frame = await s.waitFor(2);
    assert.ok(frame.result, "should return a result, not an error");
    assert.equal(frame.result.sampled, false);
    assert.deepEqual(frame.result.background_samples, []);
  } finally {
    s.close();
  }
});

test("sampleRegion on an unknown artifact fails cleanly", async () => {
  const s = session();
  try {
    s.send(1, "sampleRegion", { artifactId: "nope", selector: "#x" });
    const frame = await s.waitFor(1);
    assert.ok(frame.error, "unknown artifact must error");
    assert.match(frame.error.message, /no live page/i);
  } finally {
    s.close();
  }
});

test("the page survives runAxe so sampleRegion can use it; release closes it", async () => {
  const s = session();
  try {
    const aid = await render(s, "contrast-sampling.html");

    // runAxe no longer consumes the page...
    s.send(2, "runAxe", { artifactId: aid });
    assert.ok((await s.waitFor(2)).result, "runAxe works");

    // ...so sampleRegion still finds it.
    s.send(3, "sampleRegion", { artifactId: aid, selector: "#solid-grey" });
    assert.ok((await s.waitFor(3)).result.sampled, "sampleRegion works after runAxe");

    // release closes it; a second release is a no-op.
    s.send(4, "releaseArtifact", { artifactId: aid });
    assert.equal((await s.waitFor(4)).result.released, true);
    s.send(5, "releaseArtifact", { artifactId: aid });
    assert.equal((await s.waitFor(5)).result.released, false, "release is idempotent");

    // after release the page is gone.
    s.send(6, "sampleRegion", { artifactId: aid, selector: "#solid-grey" });
    assert.ok((await s.waitFor(6)).error, "sampling a released artifact errors");
  } finally {
    s.close();
  }
});
