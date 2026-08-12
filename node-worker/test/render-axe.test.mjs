/**
 * End-to-end check of the Week 1 gate: a real page produces one correct
 * authoritative contrast finding through render() -> runAxe().
 *
 * Unlike protocol.test.mjs (which deliberately avoids the browser to stay
 * fast and network-independent), this suite exercises the real Playwright +
 * axe-core path against local fixtures in data/fixtures/. It's slower
 * (actually launches Chromium) and lives separately so `node --test` runs of
 * the protocol suite alone stay fast.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const SERVER = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "dist",
  "rpc",
  "server.js",
);

const FIXTURES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "data",
  "fixtures",
);

/** Spawn a worker, run render then runAxe against `fixtureFile`, return the parsed results. */
async function renderAndAnalyze(fixtureFile) {
  const child = spawn("node", [SERVER], { stdio: ["pipe", "pipe", "pipe"] });
  const frames = [];
  let buf = "";

  child.stdout.on("data", (d) => {
    buf += d.toString();
    let idx;
    while ((idx = buf.indexOf("\n")) !== -1) {
      const line = buf.slice(0, idx);
      buf = buf.slice(idx + 1);
      if (line.trim()) frames.push(JSON.parse(line));
    }
  });

  const send = (id, method, params) =>
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");

  const waitFor = (id) =>
    new Promise((resolve, reject) => {
      const start = Date.now();
      const check = setInterval(() => {
        const f = frames.find((f) => f.id === id);
        if (f) {
          clearInterval(check);
          resolve(f);
        } else if (Date.now() - start > 30_000) {
          clearInterval(check);
          reject(new Error(`timed out waiting for response id=${id}`));
        }
      }, 50);
    });

  try {
    const fixtureUrl = "file://" + path.join(FIXTURES, fixtureFile);

    send(1, "render", { url: fixtureUrl });
    const renderResp = await waitFor(1);
    assert.ok(renderResp.result, `render failed: ${JSON.stringify(renderResp.error)}`);

    send(2, "runAxe", { artifactId: renderResp.result.artifactId });
    const axeResp = await waitFor(2);
    assert.ok(axeResp.result, `runAxe failed: ${JSON.stringify(axeResp.error)}`);

    return { render: renderResp.result, axe: axeResp.result };
  } finally {
    child.stdin.end();
    child.kill();
  }
}

test(
  "a fixture with a deliberate contrast violation produces one authoritative color-contrast finding",
  async () => {
    const { render, axe } = await renderAndAnalyze("contrast-fail.html");

    assert.ok(render.page_state.content_hash, "render captured a content hash");
    assert.ok(render.dom_path && render.ax_tree_path && render.screenshot_full, "artifact paths present");

    const contrastFindings = axe.violations.filter((v) => v.id === "color-contrast");
    assert.equal(contrastFindings.length, 1, "exactly one color-contrast finding");
    assert.equal(contrastFindings[0].selector, "#low-contrast-text");
    assert.match(contrastFindings[0].failureSummary, /insufficient color contrast/i);
  },
);

test(
  "a fixture with ordinary contrast produces zero color-contrast findings",
  async () => {
    const { axe } = await renderAndAnalyze("contrast-pass.html");
    const contrastFindings = axe.violations.filter((v) => v.id === "color-contrast");
    assert.equal(contrastFindings.length, 0, "no false positive on a clean fixture");
  },
);
