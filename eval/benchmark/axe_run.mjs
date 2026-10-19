// Standalone axe-core (same version Verity embeds), all rules, as a CI user would run it.
import { createRequire } from "node:module";
const require = createRequire(new URL("../../node-worker/package.json", import.meta.url));
const { chromium } = require("playwright");
import fs from "node:fs";
const axeSrc = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const b = await chromium.launch(); const out = {};
for (const url of process.argv.slice(2)) {
  const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
  const t0 = Date.now(); await p.goto(url, { waitUntil: "load" }); await p.addScriptTag({ content: axeSrc });
  const r = await p.evaluate(() => axe.run());
  const items = [];
  for (const [bucket, level] of [["violations", "fail"], ["incomplete", "review"]])
    for (const rule of r[bucket]) for (const n of rule.nodes) items.push({ sel: n.target.flat().join(" "), level, rule: rule.id });
  out[url] = { secs: (Date.now() - t0) / 1000, items }; await p.close();
}
await b.close(); console.log(JSON.stringify(out));
