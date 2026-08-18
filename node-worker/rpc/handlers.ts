/**
 * Method surface.
 *
 * `ping`    — fully implemented since Week 1 day one.
 * `render`  — implemented (A1.2/A1.3): navigates, captures a RenderArtifact,
 *             keeps the page alive for a following runAxe call.
 * `runAxe`  — implemented (A1.4): injects axe-core into the page render
 *             produced and returns its bucketed results.
 */

import { Dispatcher, RpcHandlerError } from "./dispatcher.js";
import { ErrorCode } from "./protocol.js";
import { render } from "../crawler/render.js";
import { runAxeOnPage } from "../static/axe.js";
import { takePage } from "../crawler/pages.js";

const WORKER_VERSION = "0.1.0";
const PROTOCOL_VERSION = 1;

export function registerHandlers(dispatcher: Dispatcher): void {
  /**
   * ping — liveness and handshake.
   *
   * Returns more than a bare "pong" because this doubles as the handshake the
   * Python client uses to confirm it is talking to a compatible worker. A
   * protocol version mismatch should be caught at startup, not on the first
   * render call.
   */
  dispatcher.register(
    "ping",
    () => ({
      pong: true,
      workerVersion: WORKER_VERSION,
      protocolVersion: PROTOCOL_VERSION,
      node: process.version,
      pid: process.pid,
      uptimeSeconds: Number(process.uptime().toFixed(3)),
    }),
    5_000,
  );

  /**
   * render — navigate to a URL and capture a RenderArtifact.
   *
   * Returns paths to the captured DOM, AX tree, styles, screenshot, and
   * network log rather than the content itself — see render.ts for why. The
   * live page stays open, keyed by the returned artifactId, so a following
   * runAxe call can inject axe-core into the same page instead of
   * re-navigating.
   */
  dispatcher.register(
    "render",
    async (params: unknown) => {
      const url = requireStringParam(params, "url");
      const dpr = optionalNumberParam(params, "deviceScaleFactor");
      try {
        return await render(url, dpr === undefined ? {} : { deviceScaleFactor: dpr });
      } catch (err) {
        throw new RpcHandlerError(
          ErrorCode.RENDER_FAILED,
          err instanceof Error ? err.message : String(err),
          { url },
        );
      }
    },
    120_000,
  );

  /**
   * runAxe — run axe-core against the page a prior render() produced.
   *
   * Consumes the page: it's closed after this call whether it succeeds or
   * fails, since each artifactId is single-use. Calling runAxe twice on the
   * same artifactId is a caller error, not a retryable one — re-render if you
   * need to re-analyze.
   */
  dispatcher.register(
    "runAxe",
    async (params: unknown) => {
      const artifactId = requireStringParam(params, "artifactId");
      const live = takePage(artifactId);
      if (!live) {
        throw new RpcHandlerError(
          ErrorCode.AXE_FAILED,
          `no live page for artifactId "${artifactId}" (already consumed, or render did not produce it)`,
          { artifactId },
        );
      }
      try {
        return await runAxeOnPage(live.page, live.elementDir);
      } catch (err) {
        throw new RpcHandlerError(
          ErrorCode.AXE_FAILED,
          err instanceof Error ? err.message : String(err),
          { artifactId },
        );
      } finally {
        await live.page.close().catch(() => {});
      }
    },
    60_000,
  );
}

/**
 * Read an optional numeric param, rejecting a present-but-wrong value.
 *
 * Absent is fine — it means "use the default". Present and not a positive
 * finite number is a caller error and must fail loudly rather than being
 * silently coerced into a default that hides the mistake.
 */
function optionalNumberParam(params: unknown, key: string): number | undefined {
  if (typeof params !== "object" || params === null || Array.isArray(params)) return undefined;
  const value = (params as Record<string, unknown>)[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    throw new RpcHandlerError(
      ErrorCode.INVALID_PARAMS,
      `"${key}" must be a positive finite number when provided`,
    );
  }
  return value;
}

function requireStringParam(params: unknown, key: string): string {
  if (typeof params !== "object" || params === null || Array.isArray(params)) {
    throw new RpcHandlerError(
      ErrorCode.INVALID_PARAMS,
      `params must be an object containing "${key}"`,
    );
  }
  const value = (params as Record<string, unknown>)[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new RpcHandlerError(
      ErrorCode.INVALID_PARAMS,
      `"${key}" is required and must be a non-empty string`,
    );
  }
  return value;
}
