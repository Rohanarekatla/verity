/**
 * Registry of live Pages keyed by artifactId.
 *
 * `render` captures a static artifact to disk (for Python to read), but axe-core
 * has to run inside a live browser page — it's in-page JavaScript, not something
 * you can run over a saved DOM dump. So we keep the Page open after render and
 * hand later calls the same page by id, rather than re-navigating.
 *
 * A page outlives a single call now: render → runAxe → sampleRegion(s) all
 * work the same live page, so the pixels sampled for contrast are exactly the
 * pixels axe judged. Callers `peekPage` to use it without consuming it, and
 * `releaseArtifact` (takePage + close) once done. closeAllPages() at shutdown
 * sweeps any page never released, so a crashed or forgetful caller can't leak
 * browser pages across a long-running worker.
 *
 * The entry carries the artifact's element directory alongside the page: runAxe
 * captures crops for the nodes it marks `incomplete` (A2.2), and those must
 * land in the same content-addressed directory render wrote to.
 */

import type { Page } from "playwright";

export interface LivePage {
  page: Page;
  /** Directory for element crops, inside this artifact's cache dir. */
  elementDir: string;
}

const pages = new Map<string, LivePage>();

export function registerPage(artifactId: string, page: Page, elementDir: string): void {
  pages.set(artifactId, { page, elementDir });
}

/** Get the live page without consuming it — for runAxe and sampleRegion. */
export function peekPage(artifactId: string): LivePage | undefined {
  return pages.get(artifactId);
}

/** Get the live page and remove it from the registry — the caller then closes it. */
export function takePage(artifactId: string): LivePage | undefined {
  const entry = pages.get(artifactId);
  if (entry) pages.delete(artifactId);
  return entry;
}

export async function closeAllPages(): Promise<void> {
  const all = [...pages.values()];
  pages.clear();
  await Promise.all(all.map((p) => p.page.close().catch(() => {})));
}
