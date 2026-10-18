# Competitive analysis — where Verity wins, and what to build

**Written 2026-10-18.** Source material for the "Best-in-class backlog" section
of [`execution-plan.md`](execution-plan.md). Star counts are approximate
snapshots from different dates — they measure visibility, not capability.

## The strategic finding

Almost every tool in this space runs on the **same engine**: axe-core sits
under axe DevTools, Lighthouse, Accessibility Insights, Siteimprove, and Pa11y.
And automated engines catch only **~30–57% of WCAG** by their own vendors'
numbers. The whole market is crowded onto one library that misses roughly half
of WCAG. Verity's reason to exist is the other half — the cases axe marks
`incomplete` or cannot test — resolved by a system that never fabricates.

**Do not try to out-axe axe. Own the half nobody automates, honestly.**

## The field

| Tool | What it is | Engine | ~Stars | Where Verity differs |
|---|---|---|---|---|
| axe-core (Deque) | The detection library everyone embeds | self | ~7.1k | Verity wraps it, then resolves its `incomplete` verdicts from real pixels |
| Lighthouse (Google) | Full-site audit (perf+a11y+SEO) | axe-core | ~28k | CI-native conformance gating + provenance; Lighthouse is a score, not a gate |
| Pa11y | CLI wrapper for CI | axe / HTML_CS | ~4.3k | SARIF/JUnit, baseline diffing, trust labels, keyboard testing |
| IBM Equal Access | Checker + ACT rule engine | own | ~1k | Interaction testing + pixel contrast + "math decides" doctrine |
| Accessibility Insights (MS) | Guided manual + automated | axe-core | ~1k | Automates what they leave manual (keyboard traversal/trap, focus-visible) |

Commercial tier (axe DevTools Pro ~$40–45/user/mo, Siteimprove, Level Access):
closed, SaaS, still axe-core underneath. They add guided manual testing,
monitoring dashboards, and procurement-facing reporting.

## Verity's moat today (none of the top 5 do all of these)

1. **Contrast adjudication from real pixels** — `worst_case_ratio` over sampled
   pixels turns axe's `incomplete` into authoritative verdicts.
2. **Keyboard/interaction testing against APG contracts** — tab order,
   multi-cycle trap detection, focus-visible, roving-tabindex awareness.
3. **The trust machinery** — provenance (`authoritative`/`ai_assisted`/
   `needs_review`), three-state outcomes, `cantTell` at confidence 0.0, "the
   model localises, the math decides". This is the strongest brand asset and
   nobody else markets on it.
4. **CI-native, gate-first** — SARIF (stable `/v2` fingerprints), JUnit,
   content-addressed baselines, policy gating, a GitHub Action.

## Roadmap

The prioritised task list lives in `execution-plan.md` → "Best-in-class
backlog" (BC-A / BC-B / BC-C), classified by *when* so it respects the 20-week
plan's scope control, slip rule, and deferred list. In short:

- **Pull forward now (integration gaps):** wire `traverseTabOrder` into
  `scan_url` (the keyboard wedge is dark until then); close the 3.0–4.5
  contrast band; verify SARIF annotations on a real PR.
- **Post-1.0 differentiation:** more APG contracts; new measurable SCs
  (reflow, text-spacing, target size, reduced-motion); `verity-core` +
  test-runner matchers; a hosted playground; headline VPAT/ACR.
- **Stars (distribution, not features):** own the "refuses to lie" story; a
  reproducible honest benchmark vs axe's `incomplete`s; zero-friction trial;
  a low contribution bar (APG contracts are community-friendly YAML).

## Sources

- [axe-core (GitTrend)](https://gittrend.io/repo/dequelabs/axe-core) ·
  [axe-core (OSS Insight)](https://ossinsight.io/analyze/dequelabs/axe-core)
- [Pa11y / Lighthouse / axe-core self-hosted guide](https://www.pistack.xyz/posts/2026-04-18-self-hosted-web-accessibility-testing-pa11y-lighthouse-ci-axe-core-guide-2026/)
- [webability.io — accessibility tool comparison](https://www.webability.io/blog/accessibility-tools-for-websites)
- [axe DevTools overview (ki-syndikat)](https://www.ki-syndikat.de/tools/axe-devtools/)

> A note on method: this analysis used public docs, open-source code, and
> changelogs — not reverse-engineering of commercial products. The REA MCP was
> considered but is the wrong tool here (competitors' engines are open source;
> RE of paid bundles is a ToS/legal matter we did not pursue).
