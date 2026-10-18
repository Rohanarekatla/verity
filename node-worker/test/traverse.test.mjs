/**
 * Keyboard tab-order traversal (A4.1), trap detection (A4.2), focus-visible
 * (A4.3).
 *
 * The load-bearing acceptance is Week 4's gate: a clean APG tablist must
 * produce ZERO false alarms — the five roving-tabindex tabs are reachable by
 * design and must come back `arrow-navigable`, never `not-focusable`. The
 * rest pins the honest signals keyboard.py reads: a real trap is detected, an
 * authored positive tabindex is reported verbatim, and a genuinely stranded
 * control is a barrier.
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

async function traverse(s, aid, params = {}) {
  s.send(2, "traverseTabOrder", { artifactId: aid, ...params });
  const r = await s.waitFor(2);
  assert.ok(r.result, `traverse failed: ${JSON.stringify(r.error)}`);
  return r.result;
}

test("clean APG tablist produces zero false alarms (the gate)", async () => {
  const s = session();
  try {
    const aid = await render(s, "keyboard-tablist.html");
    const r = await traverse(s, aid);

    assert.equal(r.trap_detected, false, "a clean tablist is not a trap");
    assert.equal(r.complete, true, "traversal should run to completion");

    // The five inactive tabs carry tabindex=-1 under role=tablist. They are
    // reachable with arrow keys — correct authoring — and must be classified
    // arrow-navigable, never as a barrier.
    const barriers = r.unreached.filter(
      (u) => u.reason === "not-focusable" || u.reason === "obscured",
    );
    assert.deepEqual(barriers, [], `no barrier on a clean widget, got ${JSON.stringify(barriers)}`);

    const arrow = r.unreached.filter((u) => u.reason === "arrow-navigable");
    assert.equal(arrow.length, 5, `the 5 roving tabs are arrow-navigable, got ${arrow.length}`);
  } finally {
    s.close();
  }
});

test("the single Tab stop of a tablist is the active tab, reported correctly", async () => {
  const s = session();
  try {
    const aid = await render(s, "keyboard-tablist.html");
    // One cycle: the roving tablist exposes one Tab stop per pass, so a single
    // cycle shows the shape without the per-cycle repetition.
    const r = await traverse(s, aid, { cyclesRequested: 1 });

    const selectors = r.stops.map((st) => st.selector);
    // Exactly one of the six tabs is in the Tab order (the tabindex=0 one).
    const tabStops = selectors.filter((sel) => /#tab-\d$/.test(sel));
    assert.deepEqual(tabStops, ["#tab-1"], `only the active tab is a Tab stop, got ${JSON.stringify(tabStops)}`);
    assert.ok(selectors.includes("#before") && selectors.includes("#after"));
  } finally {
    s.close();
  }
});

test("a clean page completes every requested cycle and returns to origin (A4.2)", async () => {
  // keyboard.py turns cycles_completed < cycles_requested into `indeterminate`.
  // A clean page must therefore actually complete its cycles, or every clean
  // page is reported cantTell on keyboard-trap — defeating the check.
  const s = session();
  try {
    const aid = await render(s, "keyboard-tablist.html");
    const r = await traverse(s, aid, { cyclesRequested: 2 });
    assert.equal(r.trap_detected, false);
    assert.equal(r.cycles_completed, 2, "both requested cycles complete on a clean page");
    assert.equal(r.returned_to_origin, true, "focus returns to the top of the page each pass");
    assert.equal(r.complete, true);
  } finally {
    s.close();
  }
});

test("a keyboard trap is detected and the trapping element named (A4.2)", async () => {
  const s = session();
  try {
    const aid = await render(s, "keyboard-trap.html");
    const r = await traverse(s, aid);

    assert.equal(r.trap_detected, true, "Tab is swallowed — this is a trap");
    assert.equal(r.trap_selector, "#trap", "the trapping element is named");
  } finally {
    s.close();
  }
});

test("an authored positive tabindex is reported as the authored value (A4.1)", async () => {
  const s = session();
  try {
    const aid = await render(s, "keyboard-positive-tabindex.html");
    const r = await traverse(s, aid);

    const jumped = r.stops.find((st) => st.selector === "#jumped");
    assert.ok(jumped, "the tabindex=5 button is a stop");
    assert.equal(jumped.tabindex, 5, "authored tabindex reported verbatim, not computed");

    // A plain button must report null, not its computed tabIndex of 0 — else
    // every control looks like an authored override and 2.4.3 is unusable.
    const natural = r.stops.find((st) => st.selector === "#natural-a");
    assert.equal(natural.tabindex, null, "absent tabindex attribute is null, not 0");
  } finally {
    s.close();
  }
});

test("a visible control stranded in an inert subtree is a barrier (SC 2.1.1)", async () => {
  const s = session();
  try {
    const aid = await render(s, "keyboard-unreachable.html");
    const r = await traverse(s, aid);

    const stranded = r.unreached.find((u) => u.selector === "#stranded");
    assert.ok(stranded, "the stranded button is reported unreached");
    assert.equal(stranded.reason, "not-focusable", "a real, reachable-nowhere control is a barrier");
  } finally {
    s.close();
  }
});

test("focus_visible stays null when not measured, becomes a boolean when asked (A4.3)", async () => {
  const s = session();
  try {
    const aid = await render(s, "keyboard-positive-tabindex.html");

    const unmeasured = await traverse(s, aid);
    assert.ok(
      unmeasured.stops.every((st) => st.focus_visible === null),
      "unmeasured stops report null, never a guessed boolean",
    );

    // Re-render (the first traverse left focus state on the page) and measure.
    s.send(3, "render", { url: "file://" + path.join(FIXTURES, "keyboard-positive-tabindex.html") });
    const aid2 = (await s.waitFor(3)).result.artifactId;
    s.send(4, "traverseTabOrder", { artifactId: aid2, measureFocusVisible: true });
    const measured = (await s.waitFor(4)).result;
    assert.ok(
      measured.stops.every((st) => typeof st.focus_visible === "boolean"),
      "measured stops carry a real boolean",
    );
    // A default Chromium button shows a focus ring, so at least one stop is true.
    assert.ok(
      measured.stops.some((st) => st.focus_visible === true),
      "the default focus ring is detected on at least one control",
    );
  } finally {
    s.close();
  }
});
