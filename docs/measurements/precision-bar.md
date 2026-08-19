# The Precision Bar — Week 2, Spike A

**Required artifact, Week 2. Both engineers propose independently, then
agree one number and write it down — before any results exist.**

The bar is the number below which Vision is descoped. Its only job is to be
decided *before* we see how the model performs. A bar set afterwards is not
a bar, it is a description of whatever we got.

Status: **Engineer B's proposal recorded. Engineer A's proposal and the
agreed number are still open.** Fill both in before running the corpus.

---

## Engineer B (Nikhil) — proposal

### 1. Precision bar: ≥ 95%, measured as a lower bound

**A judgment counts as a false positive when the model commits to an answer
(`yes` or `no`, or `located: yes`) and the corpus ground truth disagrees.**

Bar: **the lower bound of the 95% Wilson confidence interval on precision
must be ≥ 90%, with a point estimate ≥ 95%.**

Why a lower bound and not just the headline number: the corpus is 117
confirmed-usable cases, split across the judgments we can actually measure
this week. That is roughly 50–60 cases each. At n=58, a 95% point estimate
carries an interval of roughly ±5 points. "We hit 95%" on 58 cases is not
meaningfully different from "we hit 90%", and betting the next 18 weeks of
the project on the difference would be false precision.

Why 95% and not higher: AI-assisted findings never fail a build. `cli.py`
gates on `provenance=AUTHORITATIVE` only, so a vision false positive costs
trust, not a broken pipeline. Why not lower: trust is the entire product. A
user who finds one bogus finding in ten stops reading all of them, and at
that point the deterministic findings are damaged by association too.

### 2. Abstention ceiling: ≤ 60%

**This is the condition that makes the precision bar mean anything.**

A model that answers `unknown` to every single case scores 100% precision on
zero findings. Our schemas deliberately make abstention easy and legal —
which means precision alone is trivially gameable, by the model and by us.

So: the model must commit to a judgment on **at least 40% of cases**. Below
that, Vision is descoped regardless of how clean the precision number looks,
because a judge that abstains on two thirds of a page is not doing work a
user would notice.

### 3. Recall: reported, not gated

Recall goes in the results table. It does not gate anything this week. A
missed finding is a finding the user was going to have to find manually
anyway — the status quo. A false finding is worse than the status quo, which
is why the asymmetry is deliberate.

### 4. Latency: a separate, independent gate

Vision is descoped on latency alone, whatever precision says:

| Measure | Bar |
|---|---|
| Median end-to-end page scan, vision in path | ≤ 20 s |
| p95 end-to-end page scan | ≤ 45 s |
| Hard fail | any page ≥ 90 s |

Read from `AuditReport.latency` (B2.5), not from a stopwatch.

If we land between 20 s and 45 s median, Vision survives but Week 17's
caching work gets pulled forward — that is a third possible outcome, not a
pass.

### 5. What "descoped" means

Not "deleted". It means: the vision judgments stop being a shipped feature
and become an experiment behind a flag, the project continues on the
deterministic + contrast-maths path, and the Bible's claims are rewritten to
match. **Knowingly** is the operative word in the plan.

---

## Engineer A (Rohan) — proposal

> _To be filled in independently, before comparing. Do not read the section
> above first if you can help it — the point of proposing separately is to
> find out whether we understand the problem the same way._

- Precision bar:
- Abstention ceiling:
- Latency bar:
- Reasoning:

---

## Agreed bar

> _Agreed on: ____________  ·  Signed: Nikhil ____ / Rohan _____

- Precision bar:
- Abstention ceiling:
- Latency bar:
- Where we diverged, and what that told us:

---

## What is actually measurable this week

Worth recording now, because it changes what the bar applies to:

| Judgment | Corpus support | Measurable in W2? |
|---|---|---|
| B2.2 alt-text meaningfulness | `strip_alt` injector | Yes |
| B2.4 contrast-region localisation | `reduce_contrast` injector | Yes |
| B2.3 focus-visible | none — needs before/after focus capture (A4.3, W4) and the `outline_none` injector (B4.3, W4) | **No** |

So Sunday's number covers **two of three** judgments. The bar above applies
to those two. Focus-visible carries forward to Week 4 and is judged against
the same bar then.

See [`spike-a.md`](spike-a.md) for the hardware measurements and
[`../adr/0002-vision-descope-decision.md`](../adr/0002-vision-descope-decision.md)
for the decision itself.
