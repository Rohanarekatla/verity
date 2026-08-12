/**
 * Line-delimited JSON framing.
 *
 * The problem this solves: stdin is a byte stream, not a message stream. A
 * single 'data' event may contain
 *   - half a request
 *   - exactly one request
 *   - three requests and a fragment of a fourth
 *
 * Naively doing JSON.parse(chunk.toString()) works on your machine with small
 * payloads and then fails in production the first time a request exceeds the
 * pipe buffer (commonly 64KB). Since `render` will eventually carry full DOM
 * payloads, that is a certainty here, not a risk.
 *
 * So we buffer, split on newline, and only parse complete lines.
 */

export class LineDecoder {
  private buffer = "";
  private readonly maxLineBytes: number;

  constructor(maxLineBytes = 64 * 1024 * 1024) {
    this.maxLineBytes = maxLineBytes;
  }

  /**
   * Feed a chunk. Returns zero or more complete lines, with the trailing
   * partial line retained internally for the next call.
   */
  push(chunk: string): string[] {
    this.buffer += chunk;

    if (this.buffer.length > this.maxLineBytes) {
      // A line this long means the peer is not sending newline-delimited JSON,
      // or is sending something pathological. Fail loudly rather than growing
      // memory without bound.
      this.buffer = "";
      throw new Error(
        `incoming line exceeded ${this.maxLineBytes} bytes without a newline; framing lost`,
      );
    }

    const lines: string[] = [];
    let newlineIndex: number;

    while ((newlineIndex = this.buffer.indexOf("\n")) !== -1) {
      const line = this.buffer.slice(0, newlineIndex);
      this.buffer = this.buffer.slice(newlineIndex + 1);
      // Tolerate CRLF from Windows peers, and skip blank keep-alive lines.
      const trimmed = line.replace(/\r$/, "").trim();
      if (trimmed.length > 0) lines.push(trimmed);
    }

    return lines;
  }

  /** Anything left unterminated when the stream closes. */
  flush(): string | null {
    const rest = this.buffer.trim();
    this.buffer = "";
    return rest.length > 0 ? rest : null;
  }
}

/**
 * Serialise a response as exactly one frame.
 *
 * JSON.stringify never emits a raw newline inside a string (it escapes them as
 * \n), so a single trailing newline is unambiguous framing.
 */
export function encodeFrame(value: unknown): string {
  return JSON.stringify(value) + "\n";
}
