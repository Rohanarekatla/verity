# 3-minute demo — recording script (Week 18)

Run: `uv run python -m eval.demo --model <spec> --headed` (record the terminal
and the browser side by side). Everything on screen is a live call.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | `data/demo/checkout/index.html` in the browser | "A checkout page. It looks fine — and a mouse user can buy." |
| 0:20–0:50 | Step 1: the agent reads the tree and fails | "An AI agent reads the page the way Playwright MCP and Atlas do — through the accessibility tree. The Place order button has no accessible name. The agent cannot find it." |
| 0:50–1:20 | Verity's finding: SC 4.1.2, **AUTHORITATIVE** | "Verity doesn't guess why. It pinned the failure to the button and confirmed it from the live page — an unnamed control. A confirmed defect, not an agent hunch." |
| 1:20–2:10 | Step 2: fix loop, diff shown | "A model proposes a minimal patch in a sandbox. Verity re-scans: the defect must be gone and nothing new may break — otherwise it's refused and retried." |
| 2:10–2:40 | Step 3: the agent succeeds | "Same agent, same task, fixed page: done." |
| 2:40–3:00 | README headline | "Verity — the accessibility engine that refuses to lie. Built for the people WCAG protects, and now for the agents that read the web the same way." |

Retake rule: if a model variant happens to succeed on the broken page, the
script stops and says so — do not edit the recording to hide it.
