# Research record — agent accessibility (October 2026)

Evidence behind ADR-0005 and PLAN v2. Gathered 20 Oct 2026. Where a source is
a vendor or a blog, it is labelled so; numbers from single unreplicated sources
are flagged. **Re-check before quoting publicly.**

## 1. AI agents read the web through the accessibility tree

- Google web.dev: agents perceive pages via screenshots, raw HTML, or the
  accessibility tree. <https://web.dev/articles/ai-agent-site-ux>
- Chrome for Developers: Lighthouse **Agentic Browsing** category (from M150):
  accessibility subset (e.g. every interactive element has a programmatic name),
  CLS stability, WebMCP checks; *"informational and unbenchmarked."* Plus
  `chrome-devtools-mcp`. <https://developer.chrome.com/blog/agent-ready-toolkit>
- Playwright MCP is accessibility-tree-based (vision opt-in); OpenAI says
  ChatGPT Atlas uses ARIA (vendor statements, via SEJ).
  <https://www.searchenginejournal.com/the-accessibility-tree-is-how-ai-agents-read-your-site-its-breaking/578171/>
- WebMCP: proposed W3C CG standard (Google + Microsoft) for sites to expose
  tools to agents; origin trial in Chrome. <https://www.frase.io/blog/what-is-webmcp>,
  <https://aisearch.similarweb.com/blog/webmcp/>,
  <https://www.arcade.dev/blog/web-mcp-alex-nahas-interview>

## 2. The gap: no causal measurement exists

- SEJ (opinion piece): **"No measured comparison is provided"** of agent task
  success on accessible vs inaccessible sites; the link rests on vendor
  statements and reasoning. Same article cites WebAIM Million (Feb 2026):
  95.9% of home pages fail; 56.1 errors/page (+10.1%); low contrast 83.9%,
  missing alt 53.1%, missing labels 51%, empty links 46.3%, empty buttons 30.6%.
- Closest academic work is about *representation*, not WCAG defects:
  LCoW (contextualising pages; +31% abs. on WorkArena)
  <https://arxiv.org/pdf/2503.10689>; AXTree filtering on WebArena
  (1.97% → 2.96%) <https://arxiv.org/pdf/2609.27770>; HTML vs AXTree depends on
  model strength <https://arxiv.org/html/2604.01535>; VisualWebArena (AXTree
  gaps; Set-of-Marks helps) <https://arxiv.org/pdf/2401.13649>.
- Conclusion used in ADR-0005: a **controlled study of WCAG defects' effect on
  agent success** is novel.

## 3. Agents for accessibility (prior art to beat, not repeat)

- GitHub's internal accessibility agent: 3,535 PRs reviewed, "68% resolution
  rate" (undefined); orchestrator + 2 sub-agents works better than many; refuses
  complex widgets; admits fixes "can pass automated checks and still be unusable
  with assistive technology"; verification described vaguely.
  <https://github.blog/ai-and-ml/github-copilot/building-a-general-purpose-accessibility-agent-and-what-we-learned-in-the-process/>
- Vendor fixers (unverified claims): Deque <https://www.deque.com/blog/advancing-ai-for-axe-the-next-leap-in-digital-accessibility/>,
  Level Access <https://www.levelaccess.com/ai-accessibility-agents/>.
- Skeptical view: <https://accessible.org/can-ai-automatically-fix-accessibility-issues/>
- LLM accessibility repair, empirical (detection, remediation, cost):
  <https://arxiv.org/pdf/2605.27716>
- Agentic task execution for accessibility: TaskAudit (CHI '26) — 48 errors on
  54 screens vs 4–20 for checkers <https://arxiv.org/pdf/2510.12972>; computer-use
  agents for blind users, best ~52.5% success <https://arxiv.org/html/2609.00524v1>;
  ScreenAudit (secondary figure: 69.2% vs 31.3% coverage).

## 4. Environments, frameworks, models

- BrowserGym: one interface for MiniWoB++ (no services), WebArena (self-hosted),
  WorkArena (gated), and more. <https://github.com/ServiceNow/BrowserGym>,
  <https://pypi.org/project/browsergym-webarena/>
- Agent frameworks compared (blogs): browser-use (agent loop, CDP), Stagehand
  (SDK, caching), Playwright MCP (tree tools).
  <https://menuagentic.com/blogs/browser-use-vs-stagehand-vs-skyvern-vs-playwright-mcp/>,
  <https://www.matthewswong.com/en/blog/playwright-mcp-vs-browser-use-vs-stagehand/>
- Open-weight baselines (model card): Qwen3-8B 49.4% MiniWoB++ / 9.8% WebArena;
  Qwen3-14B 54.9% / 15.1%; WebWorld fine-tunes higher.
  <https://huggingface.co/Qwen/WebWorld-32B>
- RealWorld (Conduit): same spec, many frontends; maintenance status unclear →
  pin and vendor. <https://github.com/gothinkster/realworld>

## 5. Agent security

- WASP (Meta FAIR): web agents hijacked by prompt injection up to 86%
  (secondary summary). <https://www.alphaxiv.org/audio/2504.18575>
- AgentDojo (tool-use; 97 tasks, 629 security cases); WAInjectBench
  <https://arxiv.org/pdf/2510.01354>; plan-then-execute position paper
  <https://arxiv.org/pdf/2605.14290>; WARD defence <https://arxiv.org/pdf/2605.15030>.

## 6. What 2026 AI-engineer hiring screens for

Evals first, then agents, RAG, production concerns (cost, latency, observability,
prompt-injection defence) — recruiting/vendor blogs, treat as opinion.
<https://jobsbyculture.com/blog/ai-evals-engineer-career-guide-2026>,
<https://www.digitalapplied.com/blog/ai-developer-hiring-skills-that-matter-2026>,
<https://aiengineerinsights.com/blog/ai-engineer-skills/>

## 7. What makes open-source AI projects take off (2026)

Viral moment + one striking artifact; agent skills; provider-agnostic and
self-hostable; free. Sources disagree on numbers.
<https://blog.bytebytego.com/p/top-ai-github-repositories-in-2026>,
<https://www.firecrawl.dev/blog/best-github-repos>
