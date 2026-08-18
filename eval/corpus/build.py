"""
A2.3 — Spike A corpus harness.

Takes the clean source pages listed in `sources.yaml`, applies the Week 1
injectors to each, and emits a labelled good/bad corpus with perfect ground
truth: we know exactly which defect was introduced, where, and which success
criterion it maps to, because we introduced it.

    python -m eval.corpus.build            # fetch (cached) + generate
    python -m eval.corpus.build --refetch  # bypass the cache
    python -m eval.corpus.build --offline  # cache only, never hit network

Why generated rather than committed: the acceptance criterion is that the
corpus is "regenerable from a single command and version-controlled by
manifest, not by committing binaries". So `sources.yaml` and this script are
tracked; `.cache/` and `generated/` are not.

Every case carries a `verification` block recording that the injection did
what it claimed and nothing else. Ground truth that is silently wrong makes
every downstream precision number wrong, and the corruption is invisible
without an explicit check — so the check is mandatory, and a case that fails
it is excluded rather than quietly shipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

from bs4 import BeautifulSoup

from eval.inject import detach_label, reduce_contrast, strip_alt

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / ".cache"
OUT_DIR = HERE / "generated"
MANIFEST = HERE / "sources.yaml"

USER_AGENT = "verity-eval-corpus/0.1 (+https://github.com/Rohanarekatla/verity)"
FETCH_TIMEOUT_S = 30


# One defect per case, not "all paragraphs broken at once". A case with a
# single known defect at a known selector is ground truth a precision number
# can actually be computed against; a page with twelve simultaneous defects
# tells you far less and makes a miss impossible to attribute.
MAX_CASES_PER_PAGE_PER_INJECTOR = 3

# Marker used to hand the injector one specific element. Added to a working
# copy, never to either half of the emitted pair.
MARKER = "data-verity-target"


@dataclass
class Injection:
    """One injector, plus how to find something worth injecting into."""

    name: str
    sc_id: str
    inject: Callable[[str, str], str]
    selector: str
    # Which elements on this page are valid targets for this injector?
    targets: Callable[[BeautifulSoup], list]


INJECTIONS: list[Injection] = [
    Injection(
        name="strip_alt",
        sc_id="1.1.1",
        inject=strip_alt.inject,
        selector="img",
        # Only images that HAVE alt — stripping alt from an image that never
        # had it introduces no new defect, so it would be a mislabelled case.
        targets=lambda soup: [i for i in soup.find_all("img") if i.has_attr("alt")],
    ),
    Injection(
        name="detach_label",
        sc_id="1.3.1",
        inject=detach_label.inject,
        selector="label",
        targets=lambda soup: [l for l in soup.find_all("label") if l.has_attr("for")],
    ),
    Injection(
        name="reduce_contrast",
        sc_id="1.4.3",
        inject=reduce_contrast.inject,
        selector="p",
        # Needs visible text: recolouring an empty <p> creates no contrast
        # failure, so it would be labelled as a defect that is not there.
        targets=lambda soup: [p for p in soup.find_all("p") if p.get_text(strip=True)],
    ),
]


def read_sources() -> list[dict]:
    """
    Parse the manifest.

    Deliberately a small hand-rolled reader for the `- id:` / `url:` shape
    this file uses, so the corpus can be built without adding a YAML
    dependency for two fields.
    """
    entries: list[dict] = []
    current: dict = {}
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- id:"):
            if current:
                entries.append(current)
            current = {"id": line.split("id:", 1)[1].strip()}
        elif line.startswith("url:") and current:
            current["url"] = line.split("url:", 1)[1].strip()
    if current:
        entries.append(current)
    return [e for e in entries if e.get("id") and e.get("url")]


def fetch(url: str, cache_key: str, *, refetch: bool, offline: bool) -> Optional[str]:
    """Fetch a page, caching by source id. Returns None if unavailable."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{cache_key}.html"

    if cached.exists() and not refetch:
        return cached.read_text(encoding="utf-8", errors="replace")
    if offline:
        return None

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"  ! fetch failed {url}: {type(exc).__name__}", file=sys.stderr)
        return None

    cached.write_text(html, encoding="utf-8")
    return html


def normalise(html: str) -> str:
    """
    Round-trip HTML through the parser the injectors use.

    Both halves of a pair must share one serialisation, otherwise the pair
    differs by the injected defect *and* by BeautifulSoup's reformatting, and
    a diff of the two is unreadable. See eval/inject/README.md.
    """
    return str(BeautifulSoup(html, "html.parser"))


def verify(clean: str, injected: str, inj: Injection) -> dict:
    """
    Confirm the injection did exactly what it claimed.

    Checks that (a) something actually changed, and (b) the change is confined
    to the attribute this injector is supposed to touch. An injector that
    silently alters something else corrupts ground truth invisibly.
    """
    if clean == injected:
        return {"ok": False, "reason": "injection produced no change"}

    before = BeautifulSoup(clean, "html.parser")
    after = BeautifulSoup(injected, "html.parser")

    b_tags = before.find_all(True)
    a_tags = after.find_all(True)
    if len(b_tags) != len(a_tags):
        return {"ok": False, "reason": f"element count changed {len(b_tags)}->{len(a_tags)}"}

    allowed = {
        "strip_alt": {"alt", "data-verity-original-alt"},
        "detach_label": {"for", "data-verity-original-for"},
        "reduce_contrast": {"style", "data-verity-original-style"},
    }[inj.name]

    changed_attrs: set[str] = set()
    changed_elements = 0
    for b, a in zip(b_tags, a_tags):
        if b.name != a.name:
            return {"ok": False, "reason": f"tag changed {b.name}->{a.name}"}
        diff = {k for k in set(b.attrs) | set(a.attrs) if b.attrs.get(k) != a.attrs.get(k)}
        if diff:
            changed_elements += 1
            changed_attrs |= diff

    stray = changed_attrs - allowed
    if stray:
        return {"ok": False, "reason": f"unintended attributes changed: {sorted(stray)}"}

    return {
        "ok": True,
        "elements_changed": changed_elements,
        "attributes_changed": sorted(changed_attrs),
    }


def build(*, refetch: bool, offline: bool) -> int:
    sources = read_sources()
    print(f"manifest: {len(sources)} source pages")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    fetched = skipped_fetch = skipped_na = failed_verify = 0

    for src in sources:
        html = fetch(src["url"], src["id"], refetch=refetch, offline=offline)
        if html is None:
            skipped_fetch += 1
            continue
        fetched += 1

        clean = normalise(html)
        soup = BeautifulSoup(clean, "html.parser")

        case_dir = OUT_DIR / src["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "clean.html").write_text(clean, encoding="utf-8")

        for inj in INJECTIONS:
            targets = inj.targets(BeautifulSoup(clean, "html.parser"))
            if not targets:
                skipped_na += 1
                continue

            for idx in range(min(len(targets), MAX_CASES_PER_PAGE_PER_INJECTOR)):
                # Mark exactly one element on a working copy, hand the
                # injector a selector matching only that marker, then strip
                # the marker back out. Neither emitted half ever carries it,
                # so the pair differs by the defect alone.
                work = BeautifulSoup(clean, "html.parser")
                marked = inj.targets(work)[idx]
                marked[MARKER] = "1"

                injected_soup = BeautifulSoup(
                    inj.inject(str(work), f"[{MARKER}]"), "html.parser"
                )
                for el in injected_soup.select(f"[{MARKER}]"):
                    del el[MARKER]
                injected = normalise(str(injected_soup))

                checked = verify(clean, injected, inj)
                if not checked["ok"]:
                    print(f"  ! {src['id']}/{inj.name}#{idx}: {checked['reason']}", file=sys.stderr)
                    failed_verify += 1
                    continue

                # Exactly one element must differ — that is what "one defect
                # per case" means, and it is the property the label asserts.
                if checked["elements_changed"] != 1:
                    print(
                        f"  ! {src['id']}/{inj.name}#{idx}: "
                        f"{checked['elements_changed']} elements changed, expected 1",
                        file=sys.stderr,
                    )
                    failed_verify += 1
                    continue

                out = case_dir / f"{inj.name}-{idx}.html"
                out.write_text(injected, encoding="utf-8")

                cases.append({
                    "case_id": f"{src['id']}--{inj.name}--{idx}",
                    "source_id": src["id"],
                    "source_url": src["url"],
                    "injector": inj.name,
                    "target_index": idx,
                    "target_tag": marked.name,
                    "expected_sc": inj.sc_id,
                    "expected_outcome": "fail",
                    "expected_defect_count": 1,
                    "clean_path": str((case_dir / "clean.html").relative_to(HERE)),
                    "injected_path": str(out.relative_to(HERE)),
                    "clean_sha256": hashlib.sha256(clean.encode()).hexdigest(),
                    "injected_sha256": hashlib.sha256(injected.encode()).hexdigest(),
                    "verification": checked,
                })

    labels = {
        "corpus_version": "0.1.0",
        "generated_from": "eval/corpus/sources.yaml",
        "source_pages": fetched,
        "case_count": len(cases),
        "cases": cases,
    }
    (OUT_DIR / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")

    print(f"  fetched         : {fetched}")
    print(f"  unavailable     : {skipped_fetch}")
    print(f"  not applicable  : {skipped_na}")
    print(f"  failed verify   : {failed_verify}")
    print(f"  labelled cases  : {len(cases)}")
    print(f"  labels          : {OUT_DIR / 'labels.json'}")

    if not cases:
        print("no cases generated", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Spike A labelled corpus.")
    ap.add_argument("--refetch", action="store_true", help="bypass the page cache")
    ap.add_argument("--offline", action="store_true", help="use cached pages only")
    args = ap.parse_args()
    return build(refetch=args.refetch, offline=args.offline)


if __name__ == "__main__":
    raise SystemExit(main())
