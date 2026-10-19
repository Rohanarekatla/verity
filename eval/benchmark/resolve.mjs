// Map tool-reported selectors / XPaths to the ids of the element and its ancestors.
import { createRequire } from "node:module";
const require = createRequire(new URL("../../node-worker/package.json", import.meta.url));
const { chromium } = require("playwright");
import fs from "node:fs";
const req = JSON.parse(fs.readFileSync(process.argv[2], "utf8")); // {url: [ref,...]}
const b = await chromium.launch(); const out = {};
for (const [url, refs] of Object.entries(req)) {
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } }); await p.goto(url, { waitUntil: "load" });
  out[url] = await p.evaluate((refs) => refs.map((ref) => {
    let el = null;
    try { el = ref.startsWith("/") ? document.evaluate(ref, document, null, 9, null).singleNodeValue : document.querySelector(ref); } catch {}
    const ids = []; for (let n = el; n && n.nodeType === 1; n = n.parentElement) if (n.id) ids.push(n.id);
    return ids;
  }), refs);
  await p.close();
}
await b.close(); fs.writeFileSync(process.argv[3], JSON.stringify(out));
