/**
 * runAxe — inject axe-core into a live page and bucket its results.
 *
 * axe-core is in-page JavaScript; it has to run inside a real browser page,
 * which is why this takes a live Playwright Page (handed off by render via
 * pages.ts) rather than operating on a saved DOM dump.
 *
 * axe's native output already groups results into four buckets — violations,
 * passes, incomplete, inapplicable — and `incomplete` exists because some
 * checks (contrast chief among them) can't be resolved by static analysis
 * alone and need a human or a further deterministic pass to adjudicate. We
 * preserve that bucketing rather than flattening it away, and expand each
 * result to one entry per affected node with its selector pulled to the top
 * level, since a rule can fire on many nodes and "which element" is usually
 * the first thing you need.
 */

import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import type { Page } from "playwright";
import { captureElements, type ElementCapture } from "../crawler/elements.js";

let axeSourceCache: string | null = null;

async function loadAxeSource(): Promise<string> {
  if (axeSourceCache) return axeSourceCache;
  const axePath = fileURLToPath(import.meta.resolve("axe-core/axe.min.js"));
  axeSourceCache = await readFile(axePath, "utf8");
  return axeSourceCache;
}

export interface AxeNodeResult {
  id: string;
  impact: string | null;
  tags: string[];
  description: string;
  help: string;
  helpUrl: string;
  selector: string;
  html: string;
  failureSummary: string | null;
}

export interface AxeRunResult {
  url: string;
  timestamp: string;
  violations: AxeNodeResult[];
  passes: AxeNodeResult[];
  incomplete: AxeNodeResult[];
  inapplicable: AxeNodeResult[];
  /**
   * A2.2 — crops for the nodes axe marked `incomplete`, keyed by selector.
   *
   * These are captured here rather than during render because nothing knows
   * which nodes are incomplete until axe has run, and this is the last moment
   * the page is still live. They are the Week 3 contrast-adjudication queue:
   * the pixels a deterministic pass needs in order to resolve what axe
   * explicitly declined to judge.
   */
  element_screenshots: Record<string, ElementCapture>;
}

function expandToNodes(bucket: unknown): AxeNodeResult[] {
  const rules = Array.isArray(bucket) ? bucket : [];
  const out: AxeNodeResult[] = [];
  for (const rule of rules as any[]) {
    const nodes = Array.isArray(rule.nodes) ? rule.nodes : [{ target: [], html: "", failureSummary: null }];
    for (const node of nodes) {
      out.push({
        id: rule.id,
        impact: rule.impact ?? null,
        tags: rule.tags ?? [],
        description: rule.description ?? "",
        help: rule.help ?? "",
        helpUrl: rule.helpUrl ?? "",
        selector: Array.isArray(node.target) ? node.target.join(" ") : "",
        html: node.html ?? "",
        failureSummary: node.failureSummary ?? null,
      });
    }
  }
  return out;
}

export async function runAxeOnPage(page: Page, elementDir?: string): Promise<AxeRunResult> {
  const axeSource = await loadAxeSource();
  await page.addScriptTag({ content: axeSource });

  const raw = await page.evaluate(() => (window as any).axe.run());

  const incomplete = expandToNodes(raw.incomplete);

  // Crop only the incomplete nodes. Capturing every pass and violation would
  // mean hundreds of screenshots per page for pixels nothing will ever read.
  const elementShots = elementDir
    ? await captureElements(
        page,
        incomplete.map((n) => n.selector).filter(Boolean),
        elementDir,
      )
    : {};

  return {
    url: page.url(),
    timestamp: new Date().toISOString(),
    violations: expandToNodes(raw.violations),
    passes: expandToNodes(raw.passes),
    incomplete,
    inapplicable: expandToNodes(raw.inapplicable),
    element_screenshots: elementShots,
  };
}
