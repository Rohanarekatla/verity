/**
 * render — navigate, capture, and persist a RenderArtifact.
 *
 * Field names in the returned object are snake_case on purpose: they mirror
 * verity.models.schemas.RenderArtifact / PageState exactly, because that
 * Pydantic model is the single source of truth for this shape (see
 * docs/adr/0001-polyglot-json-rpc-over-stdio.md). Large captures (DOM, AX
 * tree, styles, screenshot, network log) are written to disk and only their
 * paths cross the RPC boundary — stuffing hundreds of KB of DOM into a
 * JSON-RPC response is exactly the payload-size problem the framing layer
 * had to be hardened against.
 */

import { randomUUID, createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { getBrowser } from "./instance.js";
import { registerPage } from "./pages.js";
import { log } from "../rpc/log.js";

const VIEWPORT = { width: 1280, height: 800 } as const;

/** Settle window after networkidle to catch late DOM mutations (SPAs, lazy content). */
const SETTLE_MS = 500;

export interface RenderResult {
  artifactId: string;
  page_state: {
    url: string;
    state_label: string;
    viewport: [number, number];
    media_emulation: Record<string, never>;
    content_hash: string;
  };
  dom_path: string;
  ax_tree_path: string;
  styles_path: string;
  screenshot_full: string;
  element_screenshots: Record<string, never>;
  network_log_path: string;
}

interface NetworkEntry {
  url: string;
  method: string;
  resourceType: string;
  status: number | null;
}

export async function render(url: string): Promise<RenderResult> {
  const browser = await getBrowser();
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();

  const networkLog: NetworkEntry[] = [];
  page.on("request", (req) => {
    networkLog.push({ url: req.url(), method: req.method(), resourceType: req.resourceType(), status: null });
  });
  page.on("requestfinished", (req) => {
    const entry = networkLog.find((e) => e.url === req.url() && e.status === null);
    if (!entry) return;
    void req.response().then((res) => {
      entry.status = res?.status() ?? null;
    });
  });

  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 60_000 });
  } catch (err) {
    await context.close();
    throw new Error(`navigation to ${url} failed: ${err instanceof Error ? err.message : String(err)}`);
  }

  // networkidle alone is not enough for SPAs that mutate the DOM after their
  // last network request settles (e.g. a client-side render pass). A short
  // settle window catches that without the cost of a fixed long sleep.
  await page.waitForTimeout(SETTLE_MS);

  const finalUrl = page.url();

  const dom = await page.content();

  // page.accessibility.snapshot() is removed from Playwright; the CDP session
  // is the supported way to get the full accessibility tree.
  const cdp = await context.newCDPSession(page);
  const axTree = await cdp.send("Accessibility.getFullAXTree");
  await cdp.detach().catch(() => {});

  const styles = await page.evaluate(() => {
    const chunks: string[] = [];
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        for (const rule of Array.from(sheet.cssRules)) chunks.push(rule.cssText);
      } catch {
        // Cross-origin stylesheets throw on .cssRules access; skip them.
      }
    }
    return chunks.join("\n");
  });

  const screenshot = await page.screenshot({ fullPage: true, type: "png" });

  const artifactId = randomUUID();
  const dir = join(tmpdir(), "verity-artifacts", artifactId);
  await mkdir(dir, { recursive: true });

  const domPath = join(dir, "dom.html");
  const axTreePath = join(dir, "ax-tree.json");
  const stylesPath = join(dir, "styles.css");
  const screenshotPath = join(dir, "screenshot.png");
  const networkLogPath = join(dir, "network-log.json");

  await Promise.all([
    writeFile(domPath, dom, "utf8"),
    writeFile(axTreePath, JSON.stringify(axTree, null, 2), "utf8"),
    writeFile(stylesPath, styles, "utf8"),
    writeFile(screenshotPath, screenshot),
    writeFile(networkLogPath, JSON.stringify(networkLog, null, 2), "utf8"),
  ]);

  const contentHash = createHash("sha256").update(dom).digest("hex");

  // Page stays open — runAxe needs a live page to inject axe-core into, not a
  // saved DOM dump. It's handed off by artifactId and closed after runAxe
  // consumes it (see pages.ts).
  registerPage(artifactId, page);

  log.info("render complete", { artifactId, url: finalUrl });

  return {
    artifactId,
    page_state: {
      url: finalUrl,
      state_label: "default",
      viewport: [VIEWPORT.width, VIEWPORT.height],
      media_emulation: {},
      content_hash: contentHash,
    },
    dom_path: domPath,
    ax_tree_path: axTreePath,
    styles_path: stylesPath,
    screenshot_full: screenshotPath,
    element_screenshots: {},
    network_log_path: networkLogPath,
  };
}
