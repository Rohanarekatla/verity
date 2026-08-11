/**
 * Week 1 method surface.
 *
 * `ping`    — fully implemented. This is today's acceptance criterion.
 * `render`  — declared, stubbed. Built in A1.2 / A1.3 (Wed–Thu).
 * `runAxe`  — declared, stubbed. Built in A1.4.
 *
 * The stubs exist on purpose. Declaring the full method surface now means the
 * Python client can be written against the real contract immediately and can
 * even test its error paths, while the browser work is still in progress.
 * A stub that returns a specific NOT_IMPLEMENTED code is far more useful to the
 * other engineer than a method that simply does not exist, because
 * METHOD_NOT_FOUND is ambiguous: it could mean "not built yet" or "you typo'd".
 */

import { Dispatcher, RpcHandlerError } from "../rpc/dispatcher.js";
import { ErrorCode } from "../rpc/protocol.js";

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
   * render — reserved for A1.2 / A1.3.
   *
   * Params are validated now even though the body is a stub, so the contract is
   * exercised from day one and the Python side can write its request-building
   * code against something that actually rejects bad input.
   */
  dispatcher.register(
    "render",
    (params: unknown) => {
      const url = requireStringParam(params, "url");
      throw new RpcHandlerError(
        ErrorCode.NOT_IMPLEMENTED,
        "render is not implemented yet (scheduled: A1.2/A1.3)",
        { url, plannedTask: "A1.2/A1.3" },
      );
    },
    120_000,
  );

  /**
   * runAxe — reserved for A1.4.
   */
  dispatcher.register(
    "runAxe",
    (params: unknown) => {
      const artifactId = requireStringParam(params, "artifactId");
      throw new RpcHandlerError(
        ErrorCode.NOT_IMPLEMENTED,
        "runAxe is not implemented yet (scheduled: A1.4)",
        { artifactId, plannedTask: "A1.4" },
      );
    },
    60_000,
  );
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
