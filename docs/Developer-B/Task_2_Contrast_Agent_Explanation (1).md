# Task 2: The Contrast Agent & Incomplete Findings

## 1. Overview & The Core Problem
Static code accessibility scanners like `axe-core` evaluate HTML and CSS code directly. While effective for standard layout elements, static analyzers cannot inspect rendered image pixels on the screen.

### The "Blind Robot" Problem
* When text uses standard background colors (e.g., `color: white; background-color: black;`), a static scanner can parse the CSS, compute the contrast ratio, and immediately classify the element into `passes` or `violations`.
* When text is placed over a background image, gradient, or canvas (e.g., `background-image: url('photo.jpg')`), the scanner can read the text color but cannot determine the underlying background pixel values.
* Because static rule engines cannot make assumptions without verification, `axe-core` routes these ambiguous cases to a dedicated **`incomplete`** bucket.

---

## 2. The Dilemma: Why the `incomplete` Bucket is Challenging

Handling ambiguous findings without dedicated architecture introduces two major failure modes:

| Strategy | Consequence |
|---|---|
| **Option A: Ignore `incomplete` findings** | Real accessibility defects (e.g., white text over a light photo) are missed, creating compliance risks. |
| **Option B: Treat as definitive failures** | False positives crash the CI/CD pipeline (exiting with code 1), causing developer friction. |

---

## 3. How `contrast.py` Solves the Dilemma

The solution uses a two-phase architecture:

### Phase 1: Status Override & Trust Partitioning (Immediate)
* The orchestrator catches `color-contrast` findings from the `incomplete` bucket.
* `contrast.py` changes the finding's status (`provenance`) to **`NEEDS_REVIEW`** and its outcome to **`cantTell`**.
* **Result:** The finding is preserved in `report.json` for auditing without failing the build (exits with code 0).

### Phase 2: Deterministic Mathematical Adjudication (Downstream / Future)
* WCAG 2.x requires specific relative luminance calculations:
  $$L = 0.2126R + 0.7152G + 0.0722B$$
* When screenshot artifacts and computer vision capabilities are wired up, pixel samples are extracted from the element region and passed into `calculate_relative_luminance()` and `calculate_contrast_ratio()`.
* The mathematical evaluation determines whether the element definitively passes or fails.

---

## 4. Components Built

1. **`verity/agents/contrast.py`**:
   - `_normalize_srgb()`: Applies standard sRGB color space gamma expansion.
   - `calculate_relative_luminance()`: Computes perceived brightness per WCAG 2.x formulas.
   - `calculate_contrast_ratio()`: Computes $(L_1 + 0.05) / (L_2 + 0.05)$.
   - `flag_needs_review()`: Tags incomplete contrast issues with `NEEDS_REVIEW` and `cantTell`.
2. **`verity/orchestrator/main.py`**:
   - Extracts both `violations` and `incomplete` buckets from the worker payload.
   - Filters for `id == "color-contrast"` within `incomplete`.
   - Routes those items through `flag_needs_review()` before passing them to deduplication.

---

## 5. Unified End-to-End Execution Flow

This chart shows how Task 1 (Deduplication/Waivers) and Task 2 (Contrast Agent) work together to process the findings from the scanner to the final report.

```text
[ START: User runs `verity scan <url>` ]
                         │
                         ▼
        [ Node Worker: render() & runAxe() ]
          Returns massive JSON payload
                         │
         ┌───────────────┴───────────────┐
         │                               │
[ Bucket 1: violations ]        [ Bucket 2: incomplete ]
         │                               │
         ▼                               ▼
[ map_raw_violation() ]         [ Filter: id == "color-contrast" ]
 provenance: AUTHORITATIVE               │
 outcome: fail                           ▼
         │                      [ verity/agents/contrast.py ]
         │                       Overrides status (Task 2):
         │                       • provenance: NEEDS_REVIEW
         │                       • outcome: cantTell
         │                               │
         └───────────────┬───────────────┘
                         ▼
        [ Merged List of Mapped Findings ]
                         │
                         ▼
       ======================================
         TASK 1: VALIDATOR ENGINE (dedup.py)
       ======================================
                         │
    [ Step 1: Signature Generation ]
    hash(SC id, normalized selector, rule id)
                         │
                         ▼
    [ Step 2: Deduplication ]
    Are there duplicate signatures? 
    ├── YES ──> Discard duplicate
    └── NO ───> Keep unique finding
                         │
                         ▼
    [ Step 3: Waiver Matching ]
    Is the signature in `waivers.yaml`?
    ├── YES ──> Set `waived = true`, attach justification
    └── NO ───> Leave `waived = false`
                         │
                         ▼
        [ Generate Final AuditReport ]
        Written to `report.json`
                         │
                         ▼
[ END: CLI Exit Code Evaluation ]
├── Unwaived AUTHORITATIVE findings? ──> Exit Code 1 (Fail Build)
└── Only waived or NEEDS_REVIEW? ──────> Exit Code 0 (Pass Build)
```
