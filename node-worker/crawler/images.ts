/**
 * A10.1 — image inventory.
 *
 * Every way an image reaches the screen, with its box and the facts a later
 * stage needs to decide what (if anything) to do with it:
 *
 *   img             <img>, including inside <picture>, and <input type=image>
 *   svg             inline <svg> (outermost only — nested <svg> is part of it)
 *   canvas          <canvas>
 *   css-background  any element whose computed background-image has a url()
 *   role-img        any other element with role="img" (icon fonts, div sprites)
 *
 * Doctrine as everywhere in the worker: this MEASURES. It does not decide
 * that an image is decorative, a logo, or worth OCR — that triage (A10.3) is
 * Python-side in verity/agents/image_triage.py, where its rules are unit
 * tested and their reasons are recorded. Text-alternative facts are reported
 * as authored and three-valued: an absent alt attribute (`alt: null`) is a
 * different fact from `alt=""` (the author's explicit "decorative"), and
 * collapsing them is how a checker blames the wrong images.
 *
 * Shape mirrors ImageInventory in verity/models/schemas.py.
 */

import type { Page } from "playwright";
import type { ImageInventory } from "../contract/contract-types.js";

export async function inventoryImages(page: Page): Promise<ImageInventory> {
  return page.evaluate(inventoryInPage);
}

function inventoryInPage(): ImageInventory {
  function cssPath(node: Element): string {
    if (node.id && document.querySelectorAll(`#${CSS.escape(node.id)}`).length === 1) {
      return `#${CSS.escape(node.id)}`;
    }
    const parts: string[] = [];
    let cur: Element | null = node;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
      if (cur.id && document.querySelectorAll(`#${CSS.escape(cur.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(cur.id)}`);
        break;
      }
      const tag = cur.tagName.toLowerCase();
      const parent: Element | null = cur.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const sameTag = Array.from(parent.children).filter((c) => c.tagName === cur!.tagName);
      if (sameTag.length === 1) parts.unshift(tag);
      else parts.unshift(`${tag}:nth-of-type(${sameTag.indexOf(cur) + 1})`);
      cur = parent;
    }
    return parts.join(" > ");
  }

  function urlsOf(bg: string): string[] {
    const out: string[] = [];
    const re = /url\(\s*(['"]?)(.*?)\1\s*\)/g;
    for (let m = re.exec(bg); m; m = re.exec(bg)) out.push(m[2]);
    return out;
  }

  function visible(el: Element, r: DOMRect): boolean {
    if (r.width <= 0 || r.height <= 0) return false;
    let o = 1;
    for (let a: Element | null = el; a; a = a.parentElement) {
      const cs = getComputedStyle(a);
      if (cs.display === "none" || cs.visibility === "hidden") return false;
      o *= parseFloat(cs.opacity);
    }
    return o > 0.01;
  }

  function labelledByText(el: Element): string | null {
    const ids = (el.getAttribute("aria-labelledby") ?? "").split(/\s+/).filter(Boolean);
    const t = ids.map((id) => document.getElementById(id)?.textContent ?? "").join(" ").trim();
    return t || null;
  }

  const seen = new Set<Element>();
  type Kind = "img" | "svg" | "canvas" | "css-background" | "role-img";
  const images: NonNullable<ImageInventory["images"]> = [];

  function add(el: Element, kind: Kind, sources: string[]) {
    if (seen.has(el)) return;
    seen.add(el);
    const r = el.getBoundingClientRect();
    const isImg = el instanceof HTMLImageElement;
    const link = el.closest("a[href]");
    const control = el.closest('button, [role="button"], a[href], input[type="image"]');
    const landmark = el.closest('header, nav, footer, [role="banner"], [role="navigation"], [role="contentinfo"]');
    const fig = el.closest("figure");
    images.push({
      selector: cssPath(el),
      kind,
      tag: el.tagName.toLowerCase(),
      box_css: { x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height },
      visible: visible(el, r),
      sources,
      natural_width: isImg ? (el as HTMLImageElement).naturalWidth || null : null,
      natural_height: isImg ? (el as HTMLImageElement).naturalHeight || null : null,
      alt: el.hasAttribute("alt") ? el.getAttribute("alt") : null,
      aria_label: el.getAttribute("aria-label"),
      aria_labelledby_text: labelledByText(el),
      title: el.getAttribute("title"),
      role: el.getAttribute("role"),
      aria_hidden: el.closest('[aria-hidden="true"]') !== null,
      in_control: control !== null,
      link_href: link ? link.getAttribute("href") : null,
      in_landmark: landmark ? (landmark.getAttribute("role") ?? landmark.tagName.toLowerCase()) : null,
      figure_caption: fig?.querySelector("figcaption")?.textContent?.trim() || null,
      id_class_text: `${el.id} ${typeof el.className === "string" ? el.className : el.getAttribute("class") ?? ""}`.trim() || null,
      has_text_content: !!(el.textContent && el.textContent.trim()) && kind === "css-background",
    });
  }

  for (const el of Array.from(document.querySelectorAll("img"))) {
    const img = el as HTMLImageElement;
    add(el, "img", [img.currentSrc || img.src].filter(Boolean));
  }
  for (const el of Array.from(document.querySelectorAll('input[type="image"]'))) {
    add(el, "img", [(el as HTMLInputElement).src].filter(Boolean));
  }
  for (const el of Array.from(document.querySelectorAll("svg"))) {
    if (el.parentElement?.closest("svg")) continue; // nested: part of the outer one
    add(el, "svg", []);
  }
  for (const el of Array.from(document.querySelectorAll("canvas"))) add(el, "canvas", []);
  const all = Array.from(document.querySelectorAll("*"));
  for (const el of all) {
    const bg = getComputedStyle(el).backgroundImage;
    if (bg && bg !== "none" && bg.includes("url(")) add(el, "css-background", urlsOf(bg));
  }
  for (const el of Array.from(document.querySelectorAll('[role="img"]'))) add(el, "role-img", []);

  return {
    images,
    shadow_roots_skipped: all.filter((e) => (e as Element & { shadowRoot?: ShadowRoot }).shadowRoot).length,
    iframes_skipped: document.querySelectorAll("iframe").length,
  };
}
