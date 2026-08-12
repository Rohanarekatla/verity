/**
 * Singleton Chromium instance.
 *
 * The whole reason this worker is a long-lived subprocess instead of a
 * per-call spawn is that launching a browser is expensive (~500ms) and
 * launching it once lets us reuse it for every render in the audit. Launch
 * happens lazily on the first render call, not at worker startup, so `ping`
 * stays cheap and a worker that's never asked to render never pays the cost.
 */

import { chromium, type Browser } from "playwright";
import { log } from "../rpc/log.js";

let browserPromise: Promise<Browser> | null = null;

export function getBrowser(): Promise<Browser> {
  if (!browserPromise) {
    log.info("launching chromium");
    browserPromise = chromium.launch({ headless: true }).catch((err) => {
      // Launch failed: clear the cached promise so the next call retries
      // instead of permanently caching a rejection.
      browserPromise = null;
      throw err;
    });
  }
  return browserPromise;
}

export async function closeBrowser(): Promise<void> {
  if (!browserPromise) return;
  const browser = await browserPromise.catch(() => null);
  browserPromise = null;
  if (browser) {
    log.info("closing chromium");
    await browser.close();
  }
}
