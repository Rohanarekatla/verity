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
import { join } from "node:path";
import type { Page } from "playwright";
import { getBrowser } from "./instance.js";
import { registerPage } from "./pages.js";
import { log } from "../rpc/log.js";

/**
 * Artifacts are content-addressed: the directory name IS the cache key, so
 * re-rendering an unchanged page lands in the same place and downstream
 * stages can skip it. Relative to cwd so a repo-local run keeps its cache
 * beside the project rather than in a shared temp dir that gets swept.
 */
const CACHE_ROOT = join(process.cwd(), ".verity", "cache");

const VIEWPORT = { width: 1280, height: 800 } as const;

/**
 * DOM-mutation settle window, applied after networkidle.
 *
 * networkidle alone is not enough for SPAs: a client-side render pass can
 * mutate the DOM well after the last network request settles, and capturing
 * then gives you a loading spinner. We wait for a genuinely quiet period —
 * no mutations for QUIET_MS — rather than a fixed sleep, because a fixed
 * sleep is simultaneously too long for static pages and too short for slow
 * ones. CAP_MS bounds the wait so a page that mutates forever (carousels,
 * animated counters, polling widgets) still gets captured.
 */
const SETTLE_QUIET_MS = 500;
const SETTLE_CAP_MS = 10_000;

async function waitForDomSettle(page: Page, quietMs: number, capMs: number): Promise<void> {
  await page.evaluate(
    ({ quietMs, capMs }) =>
      new Promise<void>((resolve) => {
        let quietTimer: ReturnType<typeof setTimeout>;

        const finish = () => {
          clearTimeout(quietTimer);
          clearTimeout(capTimer);
          observer.disconnect();
          resolve();
        };

        const observer = new MutationObserver(() => {
          clearTimeout(quietTimer);
          quietTimer = setTimeout(finish, quietMs);
        });

        const capTimer = setTimeout(finish, capMs);

        observer.observe(document, {
          childList: true,
          subtree: true,
          attributes: true,
          characterData: true,
        });

        quietTimer = setTimeout(finish, quietMs);
      }),
    { quietMs, capMs },
  );
}

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

  await waitForDomSettle(page, SETTLE_QUIET_MS, SETTLE_CAP_MS);

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

  // The cache key covers DOM + styles + screenshot: a page can be
  // byte-identical in markup while rendering differently (a stylesheet
  // changed, a swapped image), and those are exactly the changes a
  // contrast or vision pass must not skip. The network log is deliberately
  // excluded — request ordering and timing vary run to run, and including
  // them would defeat caching entirely.
  const contentHash = createHash("sha256")
    .update(dom)
    .update(styles)
    .update(screenshot)
    .digest("hex");

  const dir = join(CACHE_ROOT, contentHash);
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

  // artifactId is a live-page handle, deliberately NOT the cache key: two
  // renders of an unchanged page share a cache directory but must still get
  // distinct handles, since each holds its own open browser tab.
  const artifactId = randomUUID();

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
