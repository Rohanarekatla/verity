/**
 * Method surface.
 *
 * `ping`            — liveness/handshake (Week 1).
 * `render`          — navigate, capture a RenderArtifact, keep the page live (A1.2/A1.3).
 * `runAxe`          — inject axe-core, return its four buckets (A1.4).
 * `sampleRegion`    — read real pixels behind a text element for contrast (A3.1–A3.4).
 * `releaseArtifact` — close the live page when done with it.
 */

import { Dispatcher, RpcHandlerError } from "./dispatcher.js";
import { ErrorCode } from "./protocol.js";
import { render } from "../crawler/render.js";
import { runAxeOnPage } from "../static/axe.js";
import { sampleRegion } from "../static/sampling.js";
import { peekPage, takePage } from "../crawler/pages.js";

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
   * Peeks the page rather than consuming it: the same live page is needed
   * afterwards by sampleRegion, so the pixels sampled for contrast are the
   * pixels axe judged. The caller releases it with releaseArtifact when done;
   * shutdown sweeps anything left.
   */
  dispatcher.register(
    "runAxe",
    async (params: unknown) => {
      const artifactId = requireStringParam(params, "artifactId");
      const live = peekPage(artifactId);
      if (!live) {
        throw new RpcHandlerError(
          ErrorCode.AXE_FAILED,
          `no live page for artifactId "${artifactId}" (already released, or render did not produce it)`,
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
      }
    },
    60_000,
  );

  /**
   * sampleRegion — read the real pixels behind a text element (A3.1–A3.4).
   *
   * For adjudicating axe's `incomplete` contrast results: returns the
   * foreground colour and the set of background colours behind the glyphs,
   * from the rendered pixels. No ratio, no verdict — the model localises, the
   * maths decides (the WCAG computation lives in Python). Works on the live
   * page a prior render produced, so the pixels match what axe saw.
   */
  dispatcher.register(
    "sampleRegion",
    async (params: unknown) => {
      const artifactId = requireStringParam(params, "artifactId");
      const selector = requireStringParam(params, "selector");
      const live = peekPage(artifactId);
      if (!live) {
        throw new RpcHandlerError(
          ErrorCode.INVALID_PARAMS,
          `no live page for artifactId "${artifactId}" (already released, or render did not produce it)`,
          { artifactId },
        );
      }
      try {
        return await sampleRegion(live.page, selector);
      } catch (err) {
        throw new RpcHandlerError(
          ErrorCode.INTERNAL_ERROR,
          err instanceof Error ? err.message : String(err),
          { artifactId, selector },
        );
      }
    },
    30_000,
  );

  /**
   * releaseArtifact — close the live page and free its browser resources.
   *
   * Idempotent: releasing an unknown or already-released artifact is a no-op,
   * not an error, so a caller can release defensively in a finally block.
   */
  dispatcher.register(
    "releaseArtifact",
    async (params: unknown) => {
      const artifactId = requireStringParam(params, "artifactId");
      const live = takePage(artifactId);
      if (live) await live.page.close().catch(() => {});
      return { released: live !== undefined };
    },
    10_000,
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
