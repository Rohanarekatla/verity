# SARIF reference — hand-written before any generator code

**Week 8 required artifact, Track B half.** The plan says:

> hand-write a minimal valid SARIF file and confirm it renders as inline
> annotations **before** writing generator code. Catches spec misreadings in
> twenty minutes instead of two days.

Same rule that caught `ARROW_NAVIGABLE` in Week 4. It earned its keep again
here — writing this by hand surfaced a design problem that would otherwise
have appeared as "the annotations don't show up" on a real PR. See
**"What this surfaced"** below; that section is the actual point of the
exercise.

Engineer A writes an independent version; we compare at the pair session.

---

## 1. Minimal valid SARIF 2.1.0 that GitHub will annotate

The smallest thing that produces an inline PR annotation. Every field here is
load-bearing — removing any one of them either fails upload or silently stops
the annotation appearing.

```json
{
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "version": "2.1.0",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "Verity",
          "version": "0.1.0",
          "informationUri": "https://github.com/Rohanarekatla/verity",
          "rules": [
            {
              "id": "color-contrast",
              "name": "ColorContrast",
              "shortDescription": { "text": "Text contrast below the WCAG minimum" },
              "fullDescription": { "text": "SC 1.4.3 requires 4.5:1 for normal text and 3:1 for large text." },
              "helpUri": "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html",
              "defaultConfiguration": { "level": "error" },
              "properties": { "tags": ["accessibility", "wcag", "wcag143"] }
            }
          ]
        }
      },
      "results": [
        {
          "ruleId": "color-contrast",
          "ruleIndex": 0,
          "level": "error",
          "message": { "text": "Contrast 1.14:1 fails SC 1.4.3 at its worst sampled background region, for text of any size." },
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": { "uri": "src/pages/index.html" },
                "region": { "startLine": 42, "startColumn": 5 }
              }
            }
          ],
          "partialFingerprints": {
            "verityFindingSignature/v1": "8e26424cbad4b1c9f3a2e7d05b6c8a1f4e9d2c7b0a3f6e1d8c5b2a9f4e7d0c3b"
          }
        }
      ]
    }
  ]
}
```

## 2. Field-by-field, and what breaks without it

| Field | Required by | Omit it and… |
|---|---|---|
| `version: "2.1.0"` | spec | upload rejected |
| `runs[].tool.driver.name` | spec | upload rejected |
| `runs[].results[].ruleId` | GitHub | the alert has no rule to group under |
| `ruleIndex` | — | still works, but GitHub re-looks-up the rule by id; cheap to include |
| `level` | GitHub | defaults to the rule's `defaultConfiguration.level`; set it per-result because ours varies by provenance |
| `message.text` | spec | upload rejected |
| `locations[].physicalLocation.artifactLocation.uri` | **GitHub, for inline annotation** | the alert appears in the Security tab only — **no inline PR comment** |
| `region.startLine` | **GitHub, for inline annotation** | same: Security tab only |
| `partialFingerprints` | **GitHub, for alert tracking** | every alert is treated as new on each run; "fixed" is never detected and the same defect re-notifies forever |

Two things worth knowing that are easy to get wrong:

- **`uri` must be repo-relative**, with no leading slash and no scheme. An
  absolute path or a `file://` URL uploads fine and then annotates nothing.
- **SARIF `level` is one of `error` / `warning` / `note` / `none`.** There is
  no "critical". Our four severities do **not** map onto it — see §4.

## 3. Provenance → SARIF level (B8.1)

The plan fixes this mapping, and it is the right way round:

| Verity provenance | SARIF level | Why |
|---|---|---|
| `authoritative` | `error` | Deterministic. May fail a build. |
| `ai assisted` | `warning` | A model was involved; annotates, never gates. |
| `needs review` | `note` | We could not decide. Informational. |

The thing to notice: **the mapping is driven by provenance, not severity.** A
`critical` severity finding that is only `needs_review` is still a `note`,
because `level` in SARIF is what decides whether CI goes red — and an
undecided finding must never do that. Severity goes in `properties` instead,
for humans triaging.

## 4. Severity goes in properties, not level

```json
"properties": {
  "verity.severity": "critical",
  "verity.provenance": "authoritative",
  "verity.outcome": "fail",
  "verity.successCriterion": "1.4.3",
  "verity.wcagLevel": "AA"
}
```

Four levels do not fit into three, and conflating them would mean a
`moderate`-severity authoritative failure outranks a `critical`-severity
needs-review one in the wrong direction. Keeping them in separate fields
means neither has to lie.

---

## 5. What this surfaced — the reason for doing it first

**Verity scans a URL. SARIF annotates a file.**

An inline PR annotation needs `artifactLocation.uri` plus `region.startLine`
— a repo-relative path and a line number. A finding on
`https://staging.example.com/pricing` has neither. The DOM selector
`#hero > p:nth-of-type(2)` is not a file position, and there is no general
way to get from one to the other: the HTML may be generated from a template,
a React component, or a CMS record.

So there are exactly three cases, and the generator has to handle all three
rather than pretend:

| What was scanned | Can we annotate inline? |
|---|---|
| A local file (`file://` → repo-relative path) | **Yes** — map the URL to the path. Line number still needs source mapping; we emit line 1 and say so. |
| A URL served by a dev server from known sources | Only with a URL→source map the user supplies. Not in scope this week. |
| An arbitrary remote URL | **No.** Emit the result with no `physicalLocation`; it appears in the Security tab with the selector in the message. |

**This is a decision for the pair session, not something to quietly pick.**
It directly shapes A8.1: whether the GitHub Action scans built files from the
checkout (annotatable) or a deployed preview URL (not annotatable) changes
what the headline feature of Week 8 actually is.

My read: the Action should scan **local built files from the checkout** by
default, precisely so annotations work, and treat remote-URL scanning as a
separate mode that reports to the Security tab. But that is Track A's call to
make with me, and Week 8's gate — *"PR annotations appear inline"* — is not
reachable either way until A8.1 exists.

**Second thing it surfaced:** `partialFingerprints` is what GitHub uses to
tell "same alert" from "new alert" across commits. Ours is keyed
`verityFindingSignature/v1` on the dedup signature — which is **not yet
stable against a code formatter or a class-name hasher**. That is A7.1, also
not started. Until it lands, reformatting a template can make every alert
look new. Versioning the key name (`/v1`) means we can change the scheme
later without GitHub silently merging two incompatible fingerprints.

---

## 6. Still to verify, and I cannot do it

Uploading this file to a real repo and confirming the annotation renders
needs a PR against a GitHub repo with code scanning enabled. That is the half
of the artifact I cannot complete.

```bash
# What to run once A8.1 exists, or by hand with the sample above:
gh api --method POST /repos/{owner}/{repo}/code-scanning/sarifs \
  -f commit_sha="$(git rev-parse HEAD)" \
  -f ref="refs/heads/<branch>" \
  -f sarif="$(gzip -c sample.sarif | base64 -w0)"
```

Then open a PR touching `src/pages/index.html` line 42 and confirm the comment
appears inline rather than only in the Security tab.

A generated sample is written to `eval/fixtures/minimal.sarif.json` by
`verity/tests/test_sarif.py`, so there is always a current file to upload.
