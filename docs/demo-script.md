# 3-minute demo — recording script (Week 18)

Run: `uv run python -m eval.demo --model <spec> --headed` (record the terminal
and the browser side by side). Everything on screen is a live call.

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | `data/demo/checkout/index.html` in the browser | "A checkout page. It looks fine — and a mouse user can buy." |
| 0:20–0:50 | Step 1: the agent reads the tree and fails | "An AI agent reads the page the way Playwright MCP and Atlas do — through the accessibility tree. None of the three buttons — Remove, Apply coupon, Place order — has an accessible name. The agent sees three bare buttons and cannot tell which one orders." |
| 0:50–1:20 | Verity's finding: SC 4.1.2, **AUTHORITATIVE** | "Verity doesn't guess why. It pinned the failure to the button and confirmed it from the live page — an unnamed control. A confirmed defect, not an agent hunch." |
| 1:20–2:10 | Step 2: fix loop, diff shown | "A model proposes a minimal patch in a sandbox. Verity re-scans: the defect must be gone and nothing new may break — otherwise it's refused and retried." |
| 2:10–2:40 | Step 3: the agent succeeds | "Same agent, same task, fixed page: done." |
| 2:40–3:00 | README headline | "Verity — the accessibility engine that refuses to lie. Built for the people WCAG protects, and now for the agents that read the web the same way." |

**If the agent succeeds on the broken page** (observed 31 Oct with qwen3:4b:
it clicked the last of three nameless buttons, inferring from position), the
script says so and continues — that *is* the story then. Replace rows 2–3 with:

| Time | Screen | Say |
|---|---|---|
| 0:20–0:50 | Step 1: trace shows `click bid=11` on a nameless `button`; "succeeded by GUESSING" | "The agent got it right — by guessing. It saw three buttons with no names and bet on the last one. On a page with twenty buttons that bet fails, and a screen-reader user just hears 'button, button, button'." |
| 0:50–1:20 | Verity's scan: N × SC 4.1.2 failures | "Verity doesn't depend on whether the agent got lucky. The defect is real and Verity reports it." |

Step 3 then prints `clicked button "Place order" — by name, not by guess`.

Retake rule: never edit the recording or tune the page to force a failure.
Whatever the agent does is what the demo shows.
