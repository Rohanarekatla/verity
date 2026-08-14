/**
 * JSON-RPC 2.0 wire types.
 *
 * Spec: https://www.jsonrpc.org/specification
 *
 * We implement a deliberately small subset:
 *   - requests only (no batching, no notifications from us)
 *   - line-delimited framing (one JSON object per line, "\n" terminated)
 *
 * These types are the ONLY contract between the Python orchestrator and this
 * worker. If you change them, you change the contract, and the Python side
 * breaks. Treat this file as an interface definition, not as an implementation
 * detail.
 */

/** An id may be a string or a number. `null` is reserved for errors where we
 *  could not parse an id out of the request at all. */
export type RpcId = string | number | null;

export interface RpcRequest {
  jsonrpc: "2.0";
  id?: RpcId; // absent => notification (fire and forget, no response)
  method: string;
  params?: unknown;
}

export interface RpcSuccess {
  jsonrpc: "2.0";
  id: RpcId;
  result: unknown;
}

export interface RpcErrorBody {
  code: number;
  message: string;
  data?: unknown;
}

export interface RpcFailure {
  jsonrpc: "2.0";
  id: RpcId;
  error: RpcErrorBody;
}

export type RpcResponse = RpcSuccess | RpcFailure;

/**
 * Standard JSON-RPC error codes, plus our reserved application range.
 *
 * -32768..-32000 is reserved by the spec. Anything outside that is ours to
 * define. We start application errors at -32000 downward-safe territory:
 * conventionally, application errors live in -32099..-32000 or outside the
 * reserved block entirely. We use positive-free negatives above -32000.
 */
export const ErrorCode = {
  PARSE_ERROR: -32700, // invalid JSON received
  INVALID_REQUEST: -32600, // JSON is valid but not a valid Request object
  METHOD_NOT_FOUND: -32601, // method does not exist
  INVALID_PARAMS: -32602, // params are wrong for this method
  INTERNAL_ERROR: -32603, // handler threw unexpectedly

  // --- application-defined, Verity-specific ---
  NOT_IMPLEMENTED: -31001, // method is declared but not built yet
  HANDLER_TIMEOUT: -31002, // handler exceeded its budget
  RENDER_FAILED: -31003, // navigation or capture failed
  AXE_FAILED: -31004, // axe injection failed, or no live page for that artifactId
} as const;

export function makeSuccess(id: RpcId, result: unknown): RpcSuccess {
  return { jsonrpc: "2.0", id, result };
}

export function makeFailure(
  id: RpcId,
  code: number,
  message: string,
  data?: unknown,
): RpcFailure {
  const error: RpcErrorBody = { code, message };
  if (data !== undefined) error.data = data;
  return { jsonrpc: "2.0", id, error };
}

/**
 * Structural validation of an incoming object.
 *
 * Returns null if valid, or an error message if not. We are strict here on
 * purpose: a request that is subtly malformed should fail loudly at the
 * boundary rather than half-execute inside a handler.
 */
export function validateRequest(value: unknown): string | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return "request must be a JSON object";
  }
  const obj = value as Record<string, unknown>;

  if (obj.jsonrpc !== "2.0") {
    return 'missing or invalid "jsonrpc" field, expected "2.0"';
  }
  if (typeof obj.method !== "string" || obj.method.length === 0) {
    return 'missing or invalid "method" field, expected non-empty string';
  }
  if (
    "id" in obj &&
    obj.id !== null &&
    typeof obj.id !== "string" &&
    typeof obj.id !== "number"
  ) {
    return '"id" must be a string, number, or null';
  }
  if (
    "params" in obj &&
    obj.params !== undefined &&
    (typeof obj.params !== "object" || obj.params === null)
  ) {
    return '"params" must be an object or array when present';
  }
  return null;
}

/**
 * Best-effort id extraction from a possibly-malformed payload.
 *
 * When a request fails validation we still want to answer with the caller's id
 * so the client can settle the right promise. Only if we cannot find an id at
 * all do we answer with null.
 */
export function extractId(value: unknown): RpcId {
  if (typeof value !== "object" || value === null) return null;
  const id = (value as Record<string, unknown>).id;
  if (typeof id === "string" || typeof id === "number") return id;
  return null;
}
