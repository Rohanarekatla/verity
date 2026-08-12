/**
 * Registry of live Pages keyed by artifactId.
 *
 * `render` captures a static artifact to disk (for Python to read), but axe-core
 * has to run inside a live browser page — it's in-page JavaScript, not something
 * you can run over a saved DOM dump. So we keep the Page open after render and
 * hand `runAxe` the same page by id, rather than re-navigating. The page is
 * closed after runAxe consumes it, or by closeAllPages() at shutdown, so we
 * never leak browser pages across a long-running worker.
 */

import type { Page } from "playwright";

const pages = new Map<string, Page>();

export function registerPage(artifactId: string, page: Page): void {
  pages.set(artifactId, page);
}

export function takePage(artifactId: string): Page | undefined {
  const page = pages.get(artifactId);
  if (page) pages.delete(artifactId);
  return page;
}

export async function closeAllPages(): Promise<void> {
  const all = [...pages.values()];
  pages.clear();
  await Promise.all(all.map((p) => p.close().catch(() => {})));
}
