# What Verity does not test, and why (S19.4)

Verity's rule is that a wrong finding is worse than a missing one, and that a
tool which quietly checks less than it claims is worse than none. This page is
the "checks less" list, stated up front. Coverage numbers come from
`verity/standards.py` (`coverage_summary`), not from marketing.

| Area | What Verity does | What it does not do | Why |
|---|---|---|---|
| **Conformance overall** | finds failures; marks undecidable items for review | never declares a page or a criterion "passes" WCAG | automated checks cannot prove conformance (ADR-0004); the ACR never writes "Supports" from automation |
| **Criteria attempted** | 23 of the 55 Level A/AA criteria have an automated check; 6 of them are decided by Verity's own measurements | the other 32 A/AA criteria (captions, audio description, reading order meaning, consistent help, error suggestion…) | no automated test exists or is meaningful; they are listed as *not tested*, never omitted |
| **Images (1.1.1, 1.4.5)** | missing/empty alt via axe; image inventory and OCR triage | judging whether alt text is *meaningful*; reading text in images | the vision model abstained on 79% of cases (ADR-0002); kept as a flag-gated experiment |
| **Contrast (1.4.3)** | worst-case ratio from real rendered pixels, incl. text over images/gradients | gradients/animation/video it cannot sample stably → `cantTell`; APCA | an unstable sample is not evidence; APCA is not a WCAG 2.x criterion |
| **Keyboard (2.1.1, 2.1.2, 2.4.3, 2.4.7)** | tab-order traversal, trap detection over N cycles, focus indicator by style + pixel diff, five APG widget contracts | widgets beyond tabs, disclosure, menu button, dialog, combobox; focus order *meaningfulness* | APG patterns beyond the core five are deferred; meaning needs a person |
| **Shadow DOM / iframes** | accessible names inside shadow roots (browser-computed) | traversing into closed shadow roots or cross-origin iframes | not reachable from the page; every scan's coverage section counts what was skipped |
| **Dynamic states** | the page as rendered after settle, plus states the contracts open | exhaustive state exploration (every modal, every error state) | combinatorial; bounded by design |
| **Screen readers** | a virtual screen reader over Chrome's accessibility tree | NVDA / JAWS / VoiceOver behaviour | real screen-reader automation in CI is fragile; deferred by plan |
| **Agents (`agent-check`)** | an LLM agent attempts a task; failures confirmed by deterministic checks | treating an unconfirmed agent failure as a site defect | an agent can fail for its own reasons; unconfirmed = needs review |
| **Benchmarks** | pre-registered, verified-injection measurements | claims beyond the measured tasks, models and defects | see the paper's limitations section |
| **Platforms** | Chromium | Firefox / WebKit rendering differences | single engine; documented, not hidden |

Every scan prints a **coverage section** (CHECKED / PARTIAL / NOT CHECKED, with
the reason) and `--trace` writes the same as `verity-trace.json`.
