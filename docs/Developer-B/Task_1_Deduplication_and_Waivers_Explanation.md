# Task 1: Deduplication and Waiver Engine

## Overview
Accessibility scanners like `axe-core` are powerful but can be noisy. They often flag the exact same issue multiple times. Additionally, sometimes a technical "violation" (like a brand color contrast issue) is explicitly approved by design teams. 

If we fail the continuous integration (CI) build for duplicates and approved exceptions, developers will get frustrated and stop using Verity. 

**Task 1** solves this by acting as the **Final Filter**. It ensures that the final report only contains unique findings, and it safely "waives" known, approved issues without silently deleting them.

---

## What We Built

During this task, we implemented the following components:

1. **`verity/agents/validator/dedup.py`**: The core logic engine containing:
   - `generate_finding_signature()`: Creates a unique ID for each finding.
   - `load_waivers()`: Reads approved exceptions from a YAML file.
   - `process_findings()`: The main loop that removes duplicates and applies waivers.
2. **Orchestrator Integration (`main.py`)**: Inserted the deduplication step precisely before the final Audit Report is generated.
3. **`waivers.yaml`**: The configuration file that stores the approved exceptions.

---

## Core Concepts

### 1. The Success Criterion (SC) ID
A specific, numbered rule from the Web Content Accessibility Guidelines (WCAG). For example:
* **`1.4.3`**: Contrast (Minimum)
* **`1.1.1`**: Non-text Content (Missing alt tags)

### 2. Deduplication (The "Bouncer")
The code creates a unique signature for every finding by hashing three things: `hash(SC id, selector, rule id)`. If multiple findings have the exact same signature, the code keeps the first one and throws the rest away.

### 3. The Waiver (The "Hall Pass")
Once duplicates are removed, the code checks the surviving signatures against `waivers.yaml`. If it finds a match, it sets `waived: true` and attaches justification metadata (e.g., `approved_by: Design Lead`).

---

## Step-by-Step Flow Chart

Here is exactly how the `dedup.py` code processes findings:

```text
[ START: 3 Raw Findings enter dedup.py ]
      │
      ├── Error A: Contrast on .brand-text
      ├── Error B: Contrast on .brand-text
      └── Error C: Missing alt on #logo
      │
      ▼
=========================================================
 STEP 1: SIGNATURE GENERATION
 The code creates a unique hash(SC id, selector, rule id) 
 for every finding.
=========================================================
      │
      ├── Error A -> Signature: "Hash-123"
      ├── Error B -> Signature: "Hash-123" (Exact same inputs)
      └── Error C -> Signature: "Hash-999"
      │
      ▼
=========================================================
 STEP 2: DEDUPLICATION (The Bouncer)
 The code checks its blank dictionary to see if the 
 signature is already saved.
=========================================================
      │
      ├── Looks at Error A ("Hash-123"): Not in dictionary. 
      │   ✅ ACTION: Save it.
      │
      ├── Looks at Error B ("Hash-123"): Already in dictionary!
      │   ❌ ACTION: Delete it. (Duplicate removed)
      │
      └── Looks at Error C ("Hash-999"): Not in dictionary.
          ✅ ACTION: Save it.
      │
      ▼
[ CHECKPOINT: 2 Unique Findings Survive ]
(Error A and Error C)
      │
      ▼
=========================================================
 STEP 3: WAIVER MATCHING (The Hall Pass)
 The code checks the surviving finding signatures against 
 the partialFingerprints list in waivers.yaml.
=========================================================
      │
      ├── Looks at Error A ("Hash-123"): 
      │   Found in waivers.yaml! 
      │   ✅ ACTION: Set `waived = true` and attach justification.
      │
      └── Looks at Error C ("Hash-999"): 
          Not found in waivers.yaml.
          ❌ ACTION: Do nothing. Leave `waived = false`.
      │
      ▼
[ END: Return Clean List to main.py ]
```

---

## The Final Outcome

Both waived and non-waived findings **are always recorded in the final `report.json`**. Verity never silently drops an issue, providing a transparent audit trail. 

The only difference is how the Command Line Interface (CLI) treats them:

* **`waived: false`**: The bug is real and unapproved. It is recorded in the JSON **AND** it crashes the CI/CD build (exit code 1). The developer must fix it.
* **`waived: true`**: The bug has an approved exception. It is recorded in the JSON with its justification, **BUT** it allows the CI/CD build to pass (exit code 0).




