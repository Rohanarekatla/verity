# W18 demo run — `ollama:qwen3:4b`, 31 Oct 2026

Command: `uv run python -u -m eval.demo --model ollama:qwen3:4b --headed`
Machine: 8 GB RAM laptop, CPU-bound (Ollama showed 84%/16% CPU/GPU, context 4096,
generation ≈ 2 tokens/s). Ollama at `%LOCALAPPDATA%\Programs\Ollama`, added to PATH per shell.
Only model installed: `qwen3:4b`.

## Result

**Run 2 completed all 3 steps, exit code 0.** Run 1 failed in step 2. Two runs in total; one fix needed.

| Run | Step 1 | Step 2 | Step 3 | Exit |
|---|---|---|---|---|
| 1 (before change) | agent PASSED by guessing (clicked nameless `bid=11`) | **no patch accepted** — "the patcher proposed nothing" ×3 | not reached | 1 |
| 2 (after change) | same | patch accepted on attempt 1, 2 lines changed | agent PASSED, clicked `button "Place order"` by name | 0 |

Timings were not recorded; each run took on the order of minutes to tens of minutes on this CPU.

## What failed in run 1 and why

Step 2's `LLMPatcher` returned `None` on all 3 attempts (`parse_patch` found no
`{"old": …, "new": …}` JSON in the reply).

Diagnosis, from real output only:

1. A diagnostic call of the real patcher (probe 1, below) timed out:
   `ProviderError: ollama: network error: TimeoutError` after the client's 600 s
   timeout. The Ollama server log showed the same request still generating
   (`n_gen = 1183`, `tg ≈ 2 t/s`) and ended `[GIN] 500 | 10m0s | POST /api/chat`.
2. A direct call with the same system prompt, user prompt and `think: false`, capped at 300
   tokens (probe 2), returned `done_reason: length`, `eval_count: 300`, an empty `thinking`
   field and a `content` that began "We are given a defect: WCAG 4.1.2 — …" and was still
   reasoning ("Since the button is") with no JSON. So `qwen3:4b` ignores `think: false`
   and reasons aloud in its visible answer.
3. At ~2 t/s the demo's 2048-token budget is ~17 min, longer than the 600 s client timeout, so
   the model cannot reach the JSON within the budget.

What I did **not** establish: I did not capture the raw replies of run 1's three patcher
attempts, so I cannot say whether each hit the token cap or ended another way. The
cause above is what probes 1–2 showed on the same prompt.

## What I changed (diffs are my changes only)

The working tree already had other uncommitted changes before I started (`git status`:
`data/demo/checkout/index.html`, `docs/demo-script.md`, `eval/demo.py`,
`eval/agentbench/providers/ollama.py` incl. the `think` option and `_trace`/`_clicked`/`--max-tokens`,
`eval/readiness_report.py`, `verity/agent_check/check.py`, two test files). **I did not edit
`data/demo/checkout/index.html`, anything under `verity/`, or any check.** The `git diff`
against HEAD therefore shows more than my change; mine is exactly this:

`eval/agentbench/providers/ollama.py` — optional `format` (Ollama structured output), off by default:

```diff
-                 options: Optional[dict] = None, think=None, **kw):
+                 options: Optional[dict] = None, think=None, format=None, **kw):
...
+        # Ollama's structured output: "json" or a JSON schema. `think=False` is not
+        # honoured by every model (qwen3:4b still reasons aloud in `content`), so for
+        # calls that must return one JSON object, constrain the shape here.
+        self.format = format
...
+        if self.format is not None:
+            body["format"] = self.format
```

`eval/demo.py` — the patcher gets its own provider (same model, same cost ledger) constrained to the
patch schema; the agent's provider is unchanged:

```diff
+PATCH_SCHEMA = {"type": "object", "required": ["old", "new", "rationale"],
+                "properties": {"old": {"type": "string"}, "new": {"type": "string"}, "rationale": {"type": "string"}}}
...
+    patch_provider = provider
+    if extra:
+        # The patcher must return one {"old","new","rationale"} object. A small local
+        # model otherwise reasons aloud in its answer and is cut off before any JSON
+        # (qwen3:4b, 31 Oct) — so constrain the shape; the verifier still gates the patch.
+        patch_provider = make_provider(args.model, ledger=provider.ledger, allow_unpriced=args.budget is None,
+                                       format=PATCH_SCHEMA, **extra)
...
-                      patcher=LLMPatcher(provider, max_tokens=args.max_tokens), before=before)
+                      patcher=LLMPatcher(patch_provider, max_tokens=args.max_tokens), before=before)
```

New `eval/tests/test_ollama_provider.py`: `format` is sent when set and omitted by default.

## Tests

- Baseline before changes: `827 passed, 2 skipped in 351.18s`
- After the change: `829 passed, 2 skipped in 280.00s` (+2 new tests)

## Things you should look at

1. **The accepted patch is malformed HTML.** The model replaced the opening `<span aria-hidden="true">`
   but left its closing tag:
   `<button id="place-order" type="button" aria-label="Place order">Place order</span></button>`
   Verity's verifier accepted it (defect gone, no new axe finding) and browsers ignore the stray
   `</span>`, so step 3 works — but the verifier does not check that the patch leaves valid markup.
   I did not change this: it is in `verity/` (fix loop / verifier) and, per the rules, needs your decision.
   It is also the model's output, which the demo is supposed to show as it is. Options: leave it and
   say so in the recording; or add a well-formedness check to the verifier (strengthening, not weakening).
2. **Step 1 did not fail on the broken page.** The agent succeeded by clicking a nameless button
   (position guess); the demo took its documented "succeeded by GUESSING" path. It did not show the
   "agent fails → Verity confirms" story from the main script rows, only the alternate rows in `docs/demo-script.md`.
3. **Only `#place-order` is fixed.** `Remove` and `Apply coupon` stay unnamed in the patched page (the
   demo targets one finding); in step 3's tree they are still `button` with no name.
4. `data/demo/checkout/index.html` shows as modified vs HEAD from before this session; I left it alone.
5. I did not verify visually that the browser window opened or looked right with `--headed`; only the
   terminal output was checked.

Not committed or pushed.

## Full output — run 1 (`docs/measurements/w18-demo-run1.log`)

```text

[1/3] An AI agent tries to 'Place the order' through the accessibility tree…
      the accessibility tree the agent saw:
        RootWebArea "Checkout — Verity demo" (focused)
          [0] main
            [1] heading "Checkout"
              StaticText "Checkout"
            StaticText "1 × Accessible Widget — $19.00"
            [3] button
            [5] LabelText
              StaticText "Email"
            [6] textbox "Email"
              StaticText "buyer@example.com"
            [7] LabelText
              StaticText "Coupon code"
            [8] textbox "Coupon code"
            [9] button
            [11] button
            [13] status
      step 1: click bid=11
      step 2: done
      verdict: PASSED
      the agent succeeded by GUESSING: it clicked a button with no accessible name,
      inferring from its position. On a bigger page that guess fails;
      for a screen-reader user it is just 'button, button, button'.

[2/3] Verity's fix loop patches a sandbox copy and re-scans before accepting…
      Verity's scan: 3 SC 4.1.2 failure(s) on the page, whatever the agent did
      no patch was accepted:
        attempt 1: the patcher proposed nothing
        attempt 2: the patcher proposed nothing
        attempt 3: the patcher proposed nothing
EXIT=1

```

## Full output — run 2 (`docs/measurements/w18-demo-run2.log`)

```text

[1/3] An AI agent tries to 'Place the order' through the accessibility tree…
      the accessibility tree the agent saw:
        RootWebArea "Checkout — Verity demo" (focused)
          [0] main
            [1] heading "Checkout"
              StaticText "Checkout"
            StaticText "1 × Accessible Widget — $19.00"
            [3] button
            [5] LabelText
              StaticText "Email"
            [6] textbox "Email"
              StaticText "buyer@example.com"
            [7] LabelText
              StaticText "Coupon code"
            [8] textbox "Coupon code"
            [9] button
            [11] button
            [13] status
      step 1: click bid=11
      step 2: done
      verdict: PASSED
      the agent succeeded by GUESSING: it clicked a button with no accessible name,
      inferring from its position. On a bigger page that guess fails;
      for a screen-reader user it is just 'button, button, button'.

[2/3] Verity's fix loop patches a sandbox copy and re-scans before accepting…
      Verity's scan: 3 SC 4.1.2 failure(s) on the page, whatever the agent did
      accepted after 1 attempt(s); 2 line(s) changed:

      --- a/index.html
      +++ b/index.html
      @@ -32,7 +32,7 @@
             <label for="coupon">Coupon code</label>
             <input id="coupon" type="text" />
             <button id="apply-coupon" type="button" class="small"><span aria-hidden="true">Apply coupon</span></button>
      -      <button id="place-order" type="button"><span aria-hidden="true">Place order</span></button>
      +      <button id="place-order" type="button" aria-label="Place order">Place order</span></button>
             <p id="status" role="status"></p>
           </main>
           <script>
      

[3/3] The same agent tries again on the fixed page…
      the accessibility tree the agent saw:
        RootWebArea "Checkout — Verity demo" (focused)
          [0] main
            [1] heading "Checkout"
              StaticText "Checkout"
            StaticText "1 × Accessible Widget — $19.00"
            [3] button
            [5] LabelText
              StaticText "Email"
            [6] textbox "Email"
              StaticText "buyer@example.com"
            [7] LabelText
              StaticText "Coupon code"
            [8] textbox "Coupon code"
            [9] button
            [11] button "Place order"
              StaticText "Place order"
            [12] status
      step 1: click bid=11
      step 2: done
      verdict: PASSED
      this time it clicked button "Place order" — by name, not by guess

Total model spend: $0.0000
EXIT=0

```

## Probe 1 — real patcher call (before change), raw

```text
selector: #place-order loc: SourceLocation(file='C:\\Users\\Nikhil\\AppData\\Local\\Temp\\tmpzvs9qzss\\site\\index.html', line=35, column=6, source='html', snippet='<button id="place-order" type="button"><span aria-hidden="true">Place order</span></button>')
uv : Traceback (most recent call last):
At line:1 char:407
+ ... top\verity; uv run python -u "C:\Users\Nikhil\AppData\Local\Temp\clau ...
+                 ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (Traceback (most recent call last)::String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
  File "C:\Users\Nikhil\AppData\Local\Temp\claude\C--Users-Nikhil-AppData-Local-Claude-Data-claude-pzs8sxrjxfjjc-scratc
h-workspaces-5ed0fa92-6356-431c-a36e-22647be59290-5e4638b3-09a4-4507-aa7f-9132aef98431-scratch-2026-10-31-d9e367\e16c34
e0-66a5-4110-86e2-f98443f987de\scratchpad\probe_patcher.py", line 36, in <module>
    LLMPatcher(provider, max_tokens=2048).propose(t, loc, src, [])
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\Nikhil\OneDrive\Desktop\verity\verity\remediation\fix_loop.py", line 267, in propose
    out = self.provider.complete([Message(role="user", content=prompt)], system=_SYSTEM,
                                 max_tokens=self.max_tokens, tag=f"fix:{finding.get('id')}")
  File "C:\Users\Nikhil\AppData\Local\Temp\claude\C--Users-Nikhil-AppData-Local-Claude-Data-claude-pzs8sxrjxfjjc-scratc
h-workspaces-5ed0fa92-6356-431c-a36e-22647be59290-5e4638b3-09a4-4507-aa7f-9132aef98431-scratch-2026-10-31-d9e367\e16c34
e0-66a5-4110-86e2-f98443f987de\scratchpad\probe_patcher.py", line 17, in spy
    out = orig(*a, **k)
  File "C:\Users\Nikhil\OneDrive\Desktop\verity\eval\agentbench\providers\base.py", line 260, in complete
    raise ProviderError(self.name, error_message(payload), status=status or None, retryable=retryable)
eval.agentbench.providers.base.ProviderError: ollama: network error: TimeoutError

```

## Probe 2 — direct Ollama call, 300-token cap, raw

```text
keys: ['role', 'content'] | done_reason: length | eval_count: 300 | prompt_eval_count: 688
thinking: ''
content: 'We are given a defect: WCAG 4.1.2 — Button has no accessible name for the element with id "place-order" (line 35 in index.html). ... Since the button is'  [cut off at 300 tokens, no JSON]
```

---

## Addendum — run 3, after the verifier markup check (approved by Nikhil)

Run 2's patch left a stray `</span>`; the verifier accepted it. With approval, I added
`markup_regressions()` to `verity/remediation/fix_loop.py`: after a patch is applied to an HTML file,
tag balance of the patched file is compared with the original and the patch is refused (reason fed back to
the model) if it adds stray end tags or unclosed elements. Pre-existing sloppiness is not blamed; void and
optional-end-tag elements are ignored. Checked on the real demo page: the run-2 patch is refused
(`stray </span>`); a sound `aria-label` patch and the unchanged page pass.
Tests added in `verity/tests/test_week15_track_b.py` (patch refused + retried; check blames only what the patch added).

- Full suite: `831 passed, 2 skipped in 244.10s`, exit 0.
- Demo run 3 (`docs/measurements/w18-demo-run3.log`): exit 0. Step 1 agent PASSED by guessing; step 2 patch accepted on attempt 1,
  valid markup: `<button id="place-order" type="button" aria-label="Place order"><span aria-hidden="true">Place order</span></button>`;
  step 3 agent clicked `button "Place order"` by name, PASSED.
- Run 3's step 1/2/3 output otherwise matches run 2 apart from the patch line above.
- Still true: `Remove` and `Apply coupon` stay unnamed after the fix (the demo fixes one finding); the headed window was not inspected visually.
- Run 3 was the first run the check could have refused a patch; the model happened to produce a sound one on attempt 1,
  so the refuse-and-retry path was exercised by the unit tests only, not live.
