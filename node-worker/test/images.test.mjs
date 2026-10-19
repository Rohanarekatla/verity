/**
 * A10.1 inventory and A10.2 content-addressed crops.
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
  let nextId = 1;
  const call = (method, params) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
      const start = Date.now();
      const t = setInterval(() => {
        const f = frames.find((f) => f.id === id);
        if (f) { clearInterval(t); resolve(f); }
        else if (Date.now() - start > 60_000) { clearInterval(t); reject(new Error(`timeout id=${id}`)); }
      }, 40);
    });
  return { call, close: () => { child.stdin.end(); child.kill(); } };
}

test("inventory finds every kind, with boxes and three-valued alt (A10.1)", async () => {
  const s = session();
  try {
    const aid = (await s.call("render", { url: "file://" + path.join(FIXTURES, "images.html") })).result.artifactId;
    const inv = (await s.call("inventoryImages", { artifactId: aid })).result;
    const by = Object.fromEntries(inv.images.map((i) => [i.selector, i]));
    assert.equal(by["#content-photo"].kind, "img");
    assert.equal(by["#content-photo"].box_css.width, 320);
    assert.equal(by["#content-noalt"].alt, null, "absent alt is null");
    assert.equal(by["#decorative-empty-alt"].alt, "", 'alt="" is kept distinct');
    assert.equal(by["#decorative-hidden"].aria_hidden, true);
    assert.equal(by["#hidden-img"].visible, false);
    assert.equal(by["#svg-chart"].kind, "svg");
    assert.equal(by["#content-canvas"].kind, "canvas");
    assert.equal(by["#notext-hero"].kind, "css-background");
    assert.equal(by["#notext-hero"].has_text_content, true);
    assert.equal(by["#roleimg-stars"].kind, "role-img");
    assert.equal(by["#logo-home"].in_landmark, "header");
    assert.equal(by["#logo-home"].link_href, "/");
    assert.equal(by["#icon-in-button"].in_control, true);
  } finally {
    s.close();
  }
});

test("identical images are cropped to one content-addressed file (A10.2)", async () => {
  const s = session();
  try {
    const aid = (await s.call("render", { url: "file://" + path.join(FIXTURES, "images.html") })).result.artifactId;
    const r = (await s.call("captureImages", {
      artifactId: aid,
      selectors: ["#content-photo", "#content-photo-dup", "#icon-in-button", "#icon-in-button-dup"],
    })).result;
    const c = r.captures;
    assert.equal(c["#content-photo"].path, c["#content-photo-dup"].path, "same pixels, same file");
    assert.equal(c["#icon-in-button"].content_hash, c["#icon-in-button-dup"].content_hash);
    assert.notEqual(c["#content-photo"].path, c["#icon-in-button"].path);
    assert.equal(r.distinct_files, 2);
    assert.match(c["#content-photo"].path, /img-[0-9a-f]{32}\.png$/);
  } finally {
    s.close();
  }
});
