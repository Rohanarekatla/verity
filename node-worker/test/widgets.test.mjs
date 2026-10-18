/**
 * Widget inventory (A9.2) and exerciseWidget (A9.1, A9.3).
 *
 * The inventory must be explicit-semantics-only; exerciseWidget must record a
 * snapshot per step and, when a guard trips — step budget, a key handler that
 * hangs, a step that navigates away — stop and say so with complete:false.
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
        else if (Date.now() - start > 30_000) { clearInterval(t); reject(new Error(`timeout id=${id}`)); }
      }, 40);
    });
  return { call, close: () => { child.stdin.end(); child.kill(); } };
}

async function render(s, fixture) {
  const r = await s.call("render", { url: "file://" + path.join(FIXTURES, fixture) });
  assert.ok(r.result, `render failed: ${JSON.stringify(r.error)}`);
  return r.result.artifactId;
}

test("inventory lists explicit widgets only (A9.2)", async () => {
  const s = session();
  try {
    const aid = await render(s, "apg/menu-button-pass.html");
    const inv = (await s.call("inventoryWidgets", { artifactId: aid })).result;
    const roots = inv.widgets.map((w) => w.root.selector);
    // The trigger and the menu it controls; NOT the plain #after button.
    assert.deepEqual(roots.sort(), ["#actions", "#actions-menu"]);
    const trigger = inv.widgets.find((w) => w.root.selector === "#actions");
    assert.equal(trigger.root.role, "button", "native <button> has the implicit button role");
    assert.deepEqual(trigger.items.map((i) => i.selector), ["#mi-1", "#mi-2", "#mi-3"]);
    assert.ok(trigger.related.some((r) => r.selector === "#actions-menu" && r.hidden), "closed menu is hidden");
  } finally {
    s.close();
  }
});

test("exerciseWidget snapshots after every step (A9.1)", async () => {
  const s = session();
  try {
    const aid = await render(s, "apg/disclosure-pass.html");
    const r = (await s.call("exerciseWidget", {
      artifactId: aid,
      steps: [{ action: "focus", target: "#faq-1" }, { action: "press", key: "Enter" }],
      watch: ["#faq-1", "#faq-1-answer", "#does-not-exist"],
    })).result;
    assert.equal(r.complete, true);
    assert.deepEqual(r.snapshots.map((x) => x.step_index), [-1, 0, 1]);
    const after = r.snapshots[2];
    assert.equal(after.active, "#faq-1");
    assert.equal(after.states.find((n) => n.selector === "#faq-1").attributes["aria-expanded"], "true");
    assert.equal(after.states.find((n) => n.selector === "#faq-1-answer").hidden, false);
    assert.deepEqual(after.missing, ["#does-not-exist"]);
  } finally {
    s.close();
  }
});

test("the step budget truncates the run and says so (A9.3)", async () => {
  const s = session();
  try {
    const aid = await render(s, "apg/disclosure-pass.html");
    const r = (await s.call("exerciseWidget", {
      artifactId: aid,
      steps: [{ action: "focus", target: "#faq-1" }, { action: "press", key: "Enter" }, { action: "press", key: " " }],
      watch: ["#faq-1"],
      maxSteps: 1,
    })).result;
    assert.equal(r.complete, false);
    assert.equal(r.steps_run, 1);
    assert.match(r.incomplete_reason, /budget exhausted: 1 steps/);
  } finally {
    s.close();
  }
});

test("a key handler that hangs is cut off by the step timeout (A9.3)", async () => {
  const s = session();
  try {
    const aid = await render(s, "interaction-guards.html");
    const r = (await s.call("exerciseWidget", {
      artifactId: aid,
      steps: [{ action: "focus", target: "#spin" }, { action: "press", key: "Enter" }, { action: "press", key: "Tab" }],
      watch: ["#spin"],
    })).result;
    assert.equal(r.complete, false);
    assert.equal(r.steps_run, 1, "the hung step is not counted as run");
    assert.match(r.incomplete_reason, /did not settle/);
  } finally {
    s.close();
  }
});

test("a step that navigates away stops the run (A9.3 loop guard)", async () => {
  const s = session();
  try {
    const aid = await render(s, "interaction-guards.html");
    const r = (await s.call("exerciseWidget", {
      artifactId: aid,
      steps: [{ action: "focus", target: "#leave" }, { action: "press", key: "Enter" }, { action: "press", key: "Tab" }],
      watch: ["#leave"],
    })).result;
    assert.equal(r.complete, false);
    assert.match(r.incomplete_reason, /navigated away/);
    assert.equal(r.snapshots.length, 2, "no snapshot is taken of the page we left");
  } finally {
    s.close();
  }
});

test("a focus target that does not exist stops the run, not the worker", async () => {
  const s = session();
  try {
    const aid = await render(s, "interaction-guards.html");
    const r = (await s.call("exerciseWidget", {
      artifactId: aid, steps: [{ action: "focus", target: "#nope" }], watch: [],
    })).result;
    assert.equal(r.complete, false);
    assert.match(r.incomplete_reason, /could not run/);
  } finally {
    s.close();
  }
});

test("malformed steps are rejected as invalid params", async () => {
  const s = session();
  try {
    const aid = await render(s, "interaction-guards.html");
    const f = await s.call("exerciseWidget", { artifactId: aid, steps: [{ action: "click" }], watch: [] });
    assert.ok(f.error, "an unknown action must be an error");
    assert.match(f.error.message, /each step must be/);
  } finally {
    s.close();
  }
});
