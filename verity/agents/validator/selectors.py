"""
A6.1 — selector normalisation for a stable finding signature.

A finding's identity is keyed partly on its CSS selector. A raw axe selector is
not stable across builds: a CSS-modules / styled-components / emotion pipeline
rewrites class names to a fresh hash on every build (`Button` →
`Button__a1b2c3`, `css-1a2b3c`, `sc-bdVaJa`), and a code formatter can reorder
the classes on an element. Key the signature on that raw string and a team's
waivers stop matching, and GitHub's `partialFingerprints` flag every alert as
new, the morning after they run their bundler. A7.1 is the same requirement
seen from the other side: the signature must *survive a formatter and a
class-name hasher*.

So this module rewrites a selector into a form that keeps everything stable and
discriminating — tag names, structure, position, authored ids and classes —
and neutralises only the parts that churn:

- **generated class names are dropped or reduced to their semantic stem.** The
  hard part is telling a generated name from a stable one. `grid-cols-3`
  (Tailwind) and `card__title` (BEM) are stable and meaningful and are KEPT;
  `Button__a1b2c3` keeps the `button` stem; `css-1a2b3c` / `sc-bdVaJa` /
  `jsx-1837472` / a bare `a1b2c3d4` hash are dropped. The test is entropy and
  known framework prefixes, not "has a digit" — utility classes have digits.
- **classes are sorted**, so a formatter reordering `class="b a"` → `"a b"`
  cannot change the signature.
- **state pseudo-classes** (`:hover`, `:focus-visible`, …) are dropped;
  **structural** ones (`:nth-child`, `:first-child`, …) are kept — position is
  stable identity, interaction state is not.
- **tag names are lowercased.**

The deliberate trade is *stability over maximal specificity*: when the only
thing distinguishing two elements is a hashed class, this collapses them, and
the (sc, rule) pair plus DOM structure carries the rest. A slightly less
specific key that holds still beats a perfectly specific one that churns every
build and makes every waiver and baseline worthless.
"""

from __future__ import annotations

import re

# --- recognising a generated (volatile) token ------------------------------

# Framework-specific class shapes that are regenerated every build.
_FRAMEWORK_HASH = re.compile(
    r"""
    ^(
        css-[a-z0-9]{4,}          # emotion
      | sc-[A-Za-z]{5,}           # styled-components
      | jsx-\d{3,}                # styled-jsx
      | emotion-[a-z0-9]+
      | _[A-Za-z0-9]{5,}          # leading-underscore module hash
    )$
    """,
    re.VERBOSE,
)

# A bare hash token: a single run of letters/digits with enough entropy to be a
# build artefact rather than an authored name. Two shapes are treated as hashes:
#   - mixed-case with a digit, length >= 6  (aB3xK9)
#   - hex-ish, length >= 8, at least two digits  (a1b2c3d4)
# Neither matches an authored utility class (`col`, `mt`, `h2`) or a word.
_MIXED_CASE_HASH = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z\d]{6,}$")
_HEXISH_HASH = re.compile(r"^(?=(?:.*\d){2,})[0-9a-f]{8,}$")


def _looks_hashed(token: str) -> bool:
    """True when a bare token looks machine-generated rather than authored."""
    if _FRAMEWORK_HASH.match(token):
        return True
    if _MIXED_CASE_HASH.match(token):
        return True
    if _HEXISH_HASH.match(token):
        return True
    return False


# A compound like `Stem__a1b2c3` / `Stem_a1b2c3` / `Stem-a1b2c3`: an authored
# stem joined to a hash suffix. We keep the stem and drop the suffix — but only
# when the suffix actually looks hashed, so BEM (`card__title`, suffix is a
# word) and modifiers (`btn--primary`) are left untouched.
_STEM_HASH = re.compile(
    r"^(?P<stem>[A-Za-z][A-Za-z0-9]*?)[-_]{1,2}(?P<suffix>[A-Za-z0-9]+)$"
)


def _normalize_class(cls: str) -> str | None:
    """
    Normalise one class token. Returns the kept form, or None to drop it.

    A stable class is returned unchanged. A `Stem__hash` reduces to its stem.
    A bare hash is dropped entirely (there is nothing stable to keep).
    """
    if _looks_hashed(cls):
        return None

    m = _STEM_HASH.match(cls)
    if m:
        suffix = m.group("suffix")
        stem = m.group("stem")
        # Only strip the suffix if the suffix itself is hash-like. `card__title`
        # (BEM element) and `btn--primary` (BEM modifier) have word suffixes and
        # are kept whole; `Button__a1b2c3` has a hashed suffix and reduces.
        suffix_is_hashy = bool(re.search(r"\d", suffix)) and bool(
            re.search(r"[A-Za-z]", suffix)
        )
        if suffix_is_hashy or _HEXISH_HASH.match(suffix):
            return stem.lower()

    return cls


# --- parsing one compound selector -----------------------------------------

# A structural pseudo-class is stable identity (position in the tree); a state
# pseudo-class (:hover, :focus) is not and must not enter the signature.
_STRUCTURAL_PSEUDO = re.compile(
    r"^:(?:nth-child|nth-of-type|nth-last-child|nth-last-of-type|"
    r"first-child|last-child|only-child|first-of-type|last-of-type|only-of-type)"
    r"(?:\([^)]*\))?$"
)

# Tokenise a compound selector into tag / #id / .class / [attr] / :pseudo parts.
_PART = re.compile(
    r"""
      (?P<id>\#[^.#\[\]:\s]+)
    | (?P<cls>\.[^.#\[\]:\s]+)
    | (?P<attr>\[[^\]]*\])
    | (?P<pseudo>::?[A-Za-z-]+(?:\([^)]*\))?)
    | (?P<tag>^[A-Za-z][A-Za-z0-9-]*|\*)
    """,
    re.VERBOSE,
)


def _normalize_attr(attr: str) -> str:
    """Normalise one `[...]` attribute selector: strip quotes, collapse space."""
    inner = attr[1:-1].strip()
    inner = inner.replace('"', "").replace("'", "")
    inner = " ".join(inner.split())
    # An attribute value that is itself hashed (e.g. [id=radix-a1b2]) is
    # neutralised so it cannot churn the signature.
    if "=" in inner:
        name, _, value = inner.partition("=")
        if _looks_hashed(value):
            value = "*"
        inner = f"{name}={value}"
    return f"[{inner}]"


def _normalize_compound(compound: str) -> str:
    """Normalise one compound selector (no combinators)."""
    tag = ""
    ids: list[str] = []
    classes: list[str] = []
    attrs: list[str] = []
    pseudos: list[str] = []

    for m in _PART.finditer(compound):
        if m.group("tag"):
            tag = m.group("tag").lower()
            if tag == "*":
                tag = ""
        elif m.group("id"):
            # Ids churn the same ways classes do — Radix emits `radix-a1b2`,
            # bundlers emit `css-…` — so normalise them identically: keep a
            # stable id, reduce a stem+hash to its stem, and replace a pure
            # hash with a placeholder so the element stays distinguishable from
            # one with no id at all.
            kept = _normalize_class(m.group("id")[1:])
            ids.append(f"#{kept}" if kept else "#*")
        elif m.group("cls"):
            kept = _normalize_class(m.group("cls")[1:])
            if kept:
                classes.append(f".{kept}")
        elif m.group("attr"):
            attrs.append(_normalize_attr(m.group("attr")))
        elif m.group("pseudo"):
            p = m.group("pseudo")
            if _STRUCTURAL_PSEUDO.match(p):
                pseudos.append(p)
            # state/other pseudo-classes are dropped

    # Sort classes and attrs so source-order/formatter churn cannot matter.
    classes.sort()
    attrs.sort()
    ids.sort()
    return tag + "".join(ids) + "".join(classes) + "".join(attrs) + "".join(pseudos)


# Combinators, normalised to single-space-delimited tokens.
_COMBINATORS = {">", "+", "~"}


def normalize_selector(selector: str) -> str:
    """
    Rewrite a CSS selector into a build-stable, formatter-stable form.

    Idempotent: normalising an already-normalised selector is a no-op, which
    matters because a baseline stored today must still match a scan tomorrow.
    Returns "" for an empty/whitespace selector; the caller decides the
    fallback (see A6.2 region identity in dedup).
    """
    if not selector or not selector.strip():
        return ""

    # Normalise combinator spacing so the split is clean: `a>b` -> `a > b`.
    sel = re.sub(r"\s*([>+~])\s*", r" \1 ", selector)
    sel = " ".join(sel.split())

    out: list[str] = []
    for token in sel.split(" "):
        if token in _COMBINATORS:
            out.append(token)
        elif token:
            out.append(_normalize_compound(token))
    return " ".join(out)
