/**
 * Boundary tests for the JSON-RPC worker.
 *
 * These test the PROTOCOL, not the handlers. Every case here is a real failure
 * mode that produces a hung orchestrator or a corrupted stream if unhandled.
 *
 * Run: node --test test/
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

/**
 * Send raw bytes to a fresh worker, collect stdout and stderr separately.
 * Returns parsed stdout frames plus the raw streams.
 */
function exchange(rawInput, { chunkDelayMs = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn("node", [SERVER], { stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.on("error", reject);

    child.on("close", () => {
      const frames = stdout
        .split("\n")
        .filter((l) => l.trim())
        .map((l) => {
          try {
            return JSON.parse(l);
          } catch (e) {
            throw new Error(`stdout contained a non-JSON line: ${l.slice(0, 120)}`);
          }
        });
      resolve({ frames, stdout, stderr });
    });

    const chunks = Array.isArray(rawInput) ? rawInput : [rawInput];
    let i = 0;
    const writeNext = () => {
      if (i >= chunks.length) {
        child.stdin.end();
        return;
      }
      child.stdin.write(chunks[i++]);
      setTimeout(writeNext, chunkDelayMs);
    };
    writeNext();
  });
}

test("ping returns a valid JSON-RPC success with matching id", async () => {
  const { frames } = await exchange('{"jsonrpc":"2.0","id":1,"method":"ping"}\n');
  assert.equal(frames.length, 1);
  assert.equal(frames[0].jsonrpc, "2.0");
  assert.equal(frames[0].id, 1);
  assert.equal(frames[0].result.pong, true);
  assert.ok(frames[0].error === undefined);
});

test("string ids are preserved with their exact type", async () => {
  const { frames } = await exchange('{"jsonrpc":"2.0","id":"abc-7","method":"ping"}\n');
  assert.equal(frames[0].id, "abc-7");
  assert.equal(typeof frames[0].id, "string");
});

test("malformed JSON yields a parse error, not a crash or silence", async () => {
  const { frames } = await exchange("{not json at all\n");
  assert.equal(frames.length, 1);
  assert.equal(frames[0].error.code, -32700);
  assert.equal(frames[0].id, null);
});

test("a malformed line does not poison the requests after it", async () => {
  const { frames } = await exchange(
    '{"jsonrpc":"2.0","id":1,"method":"ping"}\n' +
      "GARBAGE\n" +
      '{"jsonrpc":"2.0","id":2,"method":"ping"}\n',
  );
  assert.equal(frames.length, 3);
  const byId = Object.fromEntries(frames.map((f) => [String(f.id), f]));
  assert.ok(byId["1"].result.pong);
  assert.ok(byId["2"].result.pong);
  assert.equal(byId["null"].error.code, -32700);
});

test("missing jsonrpc field is an invalid request, and the id still comes back", async () => {
  const { frames } = await exchange('{"id":9,"method":"ping"}\n');
  assert.equal(frames[0].error.code, -32600);
  assert.equal(frames[0].id, 9, "client must be able to settle the right promise");
});

test("unknown method returns METHOD_NOT_FOUND and lists what exists", async () => {
  const { frames } = await exchange('{"jsonrpc":"2.0","id":3,"method":"nope"}\n');
  assert.equal(frames[0].error.code, -32601);
  assert.deepEqual(frames[0].error.data.available.sort(), ["ping", "render", "runAxe"]);
});

test("runAxe against an unknown artifactId fails cleanly, not a hang", async () => {
  // Exercises the AXE_FAILED path without needing a real browser or network
  // access: an unregistered artifactId is rejected before any page work
  // happens, which is exactly the boundary this suite is meant to cover.
  const { frames } = await exchange(
    '{"jsonrpc":"2.0","id":4,"method":"runAxe","params":{"artifactId":"does-not-exist"}}\n',
  );
  assert.equal(frames[0].error.code, -31004, "AXE_FAILED");
  assert.match(frames[0].error.message, /no live page/i);
});

test("render validates its params before touching the browser", async () => {
  const { frames } = await exchange('{"jsonrpc":"2.0","id":5,"method":"render","params":{}}\n');
  assert.equal(frames[0].error.code, -32602, "INVALID_PARAMS");
});

test("a request split across TCP-style chunks is reassembled", async () => {
  const { frames } = await exchange(
    ['{"jsonrpc":"2.0",', '"id":6,"method"', ':"ping"}\n'],
    { chunkDelayMs: 15 },
  );
  assert.equal(frames.length, 1);
  assert.equal(frames[0].id, 6);
});

test("several requests arriving in one chunk are all answered", async () => {
  const input =
    Array.from({ length: 50 }, (_, i) => `{"jsonrpc":"2.0","id":${i},"method":"ping"}`).join("\n") +
    "\n";
  const { frames } = await exchange(input);
  assert.equal(frames.length, 50);
  const ids = new Set(frames.map((f) => f.id));
  assert.equal(ids.size, 50, "every id answered exactly once");
});

test("a large payload spanning the pipe buffer survives framing", async () => {
  const big = "x".repeat(300_000);
  const { frames } = await exchange(
    `{"jsonrpc":"2.0","id":7,"method":"render","params":{"url":"${big}"}}\n`,
  );
  assert.equal(frames.length, 1);
  assert.equal(frames[0].id, 7);
});

test("notifications (no id) produce no response", async () => {
  const { frames } = await exchange(
    '{"jsonrpc":"2.0","method":"ping"}\n{"jsonrpc":"2.0","id":8,"method":"ping"}\n',
  );
  assert.equal(frames.length, 1, "only the id-bearing request is answered");
  assert.equal(frames[0].id, 8);
});

test("stdout carries protocol frames only; diagnostics go to stderr", async () => {
  const { stdout, stderr } = await exchange('{"jsonrpc":"2.0","id":1,"method":"ping"}\n');
  for (const line of stdout.split("\n").filter((l) => l.trim())) {
    JSON.parse(line); // throws if anything non-protocol leaked into stdout
    assert.ok(JSON.parse(line).jsonrpc === "2.0", "every stdout line is a JSON-RPC frame");
  }
  assert.match(stderr, /worker ready/, "startup logging went to stderr");
});

test("CRLF line endings are tolerated", async () => {
  const { frames } = await exchange('{"jsonrpc":"2.0","id":11,"method":"ping"}\r\n');
  assert.equal(frames[0].id, 11);
});

test("blank lines are ignored rather than treated as parse errors", async () => {
  const { frames } = await exchange('\n\n{"jsonrpc":"2.0","id":12,"method":"ping"}\n\n');
  assert.equal(frames.length, 1);
  assert.equal(frames[0].id, 12);
});
