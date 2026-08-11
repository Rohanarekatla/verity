/**
 * Method registry and dispatch.
 *
 * Responsibilities:
 *   1. Map a method name to a handler.
 *   2. Enforce a per-call timeout so a hung handler cannot wedge the worker.
 *   3. Contain every throw, so that a handler bug becomes an error RESPONSE
 *      rather than a crashed process or, worse, silence.
 *
 * Point 3 is the one that matters most. If the worker dies or simply never
 * answers, the Python client is left awaiting a future that will never settle,
 * and the failure surfaces minutes later as an unexplained hang. An error
 * response with a code and a message surfaces in one second with a cause.
 */

import { ErrorCode, RpcErrorBody } from "./protocol.js";
import { log } from "./log.js";

export type Handler = (params: unknown) => Promise<unknown> | unknown;

export interface MethodSpec {
  handler: Handler;
  /** Milliseconds before the call is abandoned. */
  timeoutMs: number;
}

/** Thrown by handlers to produce a specific error response. */
export class RpcHandlerError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly data?: unknown,
  ) {
    super(message);
    this.name = "RpcHandlerError";
  }
}

export class Dispatcher {
  private readonly methods = new Map<string, MethodSpec>();

  register(name: string, handler: Handler, timeoutMs = 30_000): void {
    if (this.methods.has(name)) {
      throw new Error(`method already registered: ${name}`);
    }
    this.methods.set(name, { handler, timeoutMs });
  }

  has(name: string): boolean {
    return this.methods.has(name);
  }

  names(): string[] {
    return [...this.methods.keys()].sort();
  }

  /**
   * Invoke a method. Never throws — always resolves to either a result or a
   * structured error body.
   */
  async invoke(
    method: string,
    params: unknown,
  ): Promise<{ ok: true; result: unknown } | { ok: false; error: RpcErrorBody }> {
    const spec = this.methods.get(method);
    if (!spec) {
      return {
        ok: false,
        error: {
          code: ErrorCode.METHOD_NOT_FOUND,
          message: `unknown method: ${method}`,
          data: { available: this.names() },
        },
      };
    }

    const startedAt = Date.now();
    try {
      const result = await withTimeout(
        Promise.resolve(spec.handler(params)),
        spec.timeoutMs,
        method,
      );
      log.debug("method completed", { method, durationMs: Date.now() - startedAt });
      return { ok: true, result };
    } catch (err) {
      const error = toErrorBody(err);
      log.warn("method failed", {
        method,
        durationMs: Date.now() - startedAt,
        code: error.code,
        error: error.message,
      });
      return { ok: false, error };
    }
  }
}

function toErrorBody(err: unknown): RpcErrorBody {
  if (err instanceof RpcHandlerError) {
    return { code: err.code, message: err.message, data: err.data };
  }
  if (err instanceof Error) {
    return {
      code: ErrorCode.INTERNAL_ERROR,
      message: err.message,
      // The stack is genuinely useful during development and harmless here,
      // since this worker only ever talks to our own orchestrator on a pipe.
      data: { name: err.name, stack: err.stack?.split("\n").slice(0, 6) },
    };
  }
  return { code: ErrorCode.INTERNAL_ERROR, message: String(err) };
}

function withTimeout<T>(p: Promise<T>, ms: number, method: string): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () =>
        reject(
          new RpcHandlerError(
            ErrorCode.HANDLER_TIMEOUT,
            `method '${method}' exceeded ${ms}ms`,
            { method, timeoutMs: ms },
          ),
        ),
      ms,
    );
    // Do not let a pending timer hold the event loop open at shutdown.
    if (typeof timer.unref === "function") timer.unref();
  });

  return Promise.race([p, timeout]).finally(() => clearTimeout(timer)) as Promise<T>;
}
