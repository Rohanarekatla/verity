/**
 * Logging for the worker.
 *
 * THE RULE: stdout carries protocol frames and nothing else. Every diagnostic
 * byte goes to stderr.
 *
 * This module exists so that rule is enforced in one place instead of relying
 * on discipline at every call site. `console.log` writes to stdout and will
 * silently corrupt the protocol stream, so we shadow it below to make the
 * mistake impossible rather than merely discouraged.
 */

type Level = "debug" | "info" | "warn" | "error";

const LEVELS: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };

const threshold: number =
  LEVELS[(process.env.VERITY_LOG_LEVEL as Level) ?? "info"] ?? LEVELS.info;

function emit(level: Level, message: string, fields?: Record<string, unknown>) {
  if (LEVELS[level] < threshold) return;
  const record = {
    ts: new Date().toISOString(),
    level,
    component: "node-worker",
    message,
    ...fields,
  };
  // Structured logs on stderr: greppable by us, ignorable by the orchestrator.
  process.stderr.write(JSON.stringify(record) + "\n");
}

export const log = {
  debug: (m: string, f?: Record<string, unknown>) => emit("debug", m, f),
  info: (m: string, f?: Record<string, unknown>) => emit("info", m, f),
  warn: (m: string, f?: Record<string, unknown>) => emit("warn", m, f),
  error: (m: string, f?: Record<string, unknown>) => emit("error", m, f),
};

/**
 * Make stdout writes from careless code impossible to do by accident.
 *
 * If some dependency (or a future you at 1am) calls console.log, we redirect it
 * to stderr with a loud warning instead of letting it corrupt a frame. This has
 * caught real bugs: Playwright and several of its transitive deps print to
 * stdout under certain failure modes.
 */
export function guardStdout(): void {
  const redirect =
    (level: Level) =>
    (...args: unknown[]) => {
      emit(level, "console call redirected away from stdout", {
        args: args.map((a) => (typeof a === "string" ? a : safeStringify(a))),
      });
    };

  console.log = redirect("info");
  console.info = redirect("info");
  console.debug = redirect("debug");
  console.warn = redirect("warn");
  console.error = redirect("error");
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
