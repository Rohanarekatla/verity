/**
 * Verity Node worker — JSON-RPC 2.0 over stdio.
 *
 * Lifecycle: the Python orchestrator spawns this process once and keeps it
 * alive for the duration of an audit, sending many requests over the same pipe.
 * It is not a one-shot CLI. That is why we launch a browser once (later) rather
 * than per call, and why clean shutdown matters.
 *
 * Concurrency note: requests are dispatched as they arrive and responses are
 * written when they resolve, so responses may be OUT OF ORDER relative to
 * requests. This is legal JSON-RPC and is why every response carries the
 * request's `id`. The client correlates by id, never by arrival order.
 */

import { Dispatcher } from "./dispatcher.js";
import { LineDecoder, encodeFrame } from "./framing.js";
import { log, guardStdout } from "./log.js";
import {
  ErrorCode,
  extractId,
  makeFailure,
  makeSuccess,
  validateRequest,
  RpcId,
  RpcRequest,
} from "./protocol.js";
import { registerHandlers } from "./handlers.js";
import { closeBrowser } from "../crawler/instance.js";
import { closeAllPages } from "../crawler/pages.js";

// Must run before anything else can print.
guardStdout();

const dispatcher = new Dispatcher();
registerHandlers(dispatcher);

const decoder = new LineDecoder();

/** Number of requests currently in flight, so shutdown can wait for them. */
let inFlight = 0;
let shuttingDown = false;

/** Frames written but not yet flushed to the pipe. */
let pendingWrites = 0;

/**
 * Write one frame to stdout.
 *
 * The callback is not decoration. When stdout is a PIPE (which it always is
 * here, because Python spawns us with stdio=PIPE), writes larger than the pipe
 * buffer are asynchronous, and `process.exit()` does NOT flush them — it
 * truncates mid-frame. The orchestrator then receives half a JSON object and
 * the whole stream is desynchronised.
 *
 * This is invisible in manual testing, because `echo ... | node server.js`
 * produces small responses that fit in the buffer and flush synchronously. It
 * only appears once `render` starts returning real DOM payloads. Counting
 * pending writes lets shutdown wait for the pipe to drain.
 */
function respond(response: unknown): void {
  pendingWrites += 1;
  process.stdout.write(encodeFrame(response), () => {
    pendingWrites -= 1;
  });
}

async function handleLine(line: string): Promise<void> {
  let parsed: unknown;

  try {
    parsed = JSON.parse(line);
  } catch (err) {
    // We cannot know the id, so per spec we answer with id: null.
    respond(
      makeFailure(null, ErrorCode.PARSE_ERROR, "invalid JSON", {
        detail: err instanceof Error ? err.message : String(err),
        // Truncated so a huge malformed payload does not echo back in full.
        received: line.slice(0, 200),
      }),
    );
    return;
  }

  const validationError = validateRequest(parsed);
  if (validationError) {
    respond(
      makeFailure(extractId(parsed), ErrorCode.INVALID_REQUEST, validationError),
    );
    return;
  }

  const request = parsed as RpcRequest;
  const id: RpcId | undefined = request.id;

  // A request without an id is a notification: execute it, answer nothing.
  const isNotification = !("id" in request) || id === undefined;

  inFlight += 1;
  try {
    const outcome = await dispatcher.invoke(request.method, request.params);
    if (isNotification) return;

    respond(
      outcome.ok
        ? makeSuccess(id as RpcId, outcome.result)
        : makeFailure(
            id as RpcId,
            outcome.error.code,
            outcome.error.message,
            outcome.error.data,
          ),
    );
  } finally {
    inFlight -= 1;
  }
}

process.stdin.setEncoding("utf8");

process.stdin.on("data", (chunk: string) => {
  let lines: string[];
  try {
    lines = decoder.push(chunk);
  } catch (err) {
    // Framing is unrecoverable: we no longer know where messages begin.
    log.error("framing error, terminating", {
      error: err instanceof Error ? err.message : String(err),
    });
    respond(
      makeFailure(null, ErrorCode.PARSE_ERROR, "framing lost, worker terminating"),
    );
    process.exit(1);
  }

  // Fire each line without awaiting, so a slow request does not block the ones
  // behind it. Errors are already contained inside handleLine.
  for (const line of lines) {
    void handleLine(line);
  }
});

process.stdin.on("end", () => {
  const remainder = decoder.flush();
  if (remainder) {
    log.warn("stream ended with an unterminated line", {
      bytes: remainder.length,
    });
  }
  void shutdown(0);
});

/** Wait briefly for in-flight work, then exit. */
async function shutdown(code: number): Promise<void> {
  if (shuttingDown) return;
  shuttingDown = true;
  log.info("shutting down", { inFlight });

  const deadline = Date.now() + 5_000;

  // Phase 1: let in-flight handlers finish and enqueue their responses.
  while (inFlight > 0 && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 25));
  }
  if (inFlight > 0) {
    log.warn("exiting with requests still in flight", { inFlight });
  }

  // Phase 2: let those responses actually reach the pipe before we exit.
  while (pendingWrites > 0 && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 5));
  }
  if (pendingWrites > 0) {
    log.error("exiting with unflushed frames; peer may see a truncated stream", {
      pendingWrites,
    });
  }

  // Phase 3: close the browser. Skipping this on a crash path is how you get
  // orphaned Chromium processes outliving the worker that spawned them.
  await closeAllPages();
  await closeBrowser().catch((err) => {
    log.error("error closing browser during shutdown", {
      error: err instanceof Error ? err.message : String(err),
    });
  });

  process.exit(code);
}

process.on("SIGTERM", () => void shutdown(0));
process.on("SIGINT", () => void shutdown(0));

/**
 * Last-resort guards. Without these, an unhandled rejection anywhere in the
 * process kills the worker silently and the orchestrator hangs. We log the
 * cause to stderr first so the failure is diagnosable. Routed through
 * shutdown() rather than a bare process.exit() so the browser still gets
 * closed on a crash path.
 */
process.on("uncaughtException", (err) => {
  log.error("uncaught exception", { error: err.message, stack: err.stack });
  void shutdown(1);
});

process.on("unhandledRejection", (reason) => {
  log.error("unhandled rejection", { reason: String(reason) });
  void shutdown(1);
});

log.info("worker ready", { methods: dispatcher.names(), pid: process.pid });
