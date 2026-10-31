"""
A11.1′ — the benchmark task suite.

The (task × defect) matrix the benchmark measures over. A task declares which
defects are *meaningful* for it, so the matrix only contains cells where the
injected accessibility defect could plausibly change the agent's success — a
`div_button` cell on a task with no button would be a wasted, uninterpretable
run.

Defect applicability follows what each defect in `defects.js` touches:

- **strip_name** / **div_button** — tasks where success runs through a *button*
  or *link* (the control loses its name, or its role).
- **detach_label** — tasks where success runs through a *labelled form control*
  (a checkbox, an option, a text field): detaching the label removes the
  control's accessible name.

Success for every MiniWoB task is the env's own reward (`EnvRewardCheck`), never
an LLM judgment — the pre-registered primary metric.

Scope note: the plan's W11 artifact also calls for 2–3 **vendored web apps**
(RealWorld/Conduit, an e-commerce demo, an admin/forms app) under pinned
Docker. Those are infrastructure (standing up and pinning three apps) and are
tracked in `VENDORED_APPS` below as pending; the MiniWoB++ families here are the
runnable, deterministic core of the suite today.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

HERE = Path(__file__).resolve().parent
MINIWOB_HTML = HERE / "vendor" / "miniwob-plusplus" / "miniwob" / "html" / "miniwob"

# The three defects, from defects.js.
BUTTON_DEFECTS = ("strip_name", "div_button")
LINK_DEFECTS = ("strip_name",)
FORM_DEFECTS = ("detach_label",)
# Keyboard / focus family (H3): a control out of the Tab order, a trap, no focus
# ring. They only bite agents that use the keyboard (the screen-reader agent),
# so they apply to every task family that needs a control.
KEYBOARD_DEFECTS = ("keyboard_trap", "remove_from_tab_order", "outline_none")


@dataclass(frozen=True)
class Task:
    """One benchmark task and the defects meaningful for it."""

    id: str
    app: str            # "miniwob" (today) or a vendored app id (pending)
    family: str         # "button" | "link" | "form" | "select"
    defects: tuple[str, ...]
    success: str = "env-reward"  # MiniWoB: the env computes reward on its solved state


# ~24 MiniWoB++ tasks across four families. Deliberately spread so a defect's
# effect is measured on more than one task shape (plan H1).
MINIWOB_TASKS: tuple[Task, ...] = (
    # Buttons — name/role defects bite hardest here.
    Task("click-button", "miniwob", "button", BUTTON_DEFECTS + KEYBOARD_DEFECTS),
    Task("click-button-sequence", "miniwob", "button", BUTTON_DEFECTS),
    Task("click-test", "miniwob", "button", BUTTON_DEFECTS),
    Task("click-widget", "miniwob", "button", BUTTON_DEFECTS),
    Task("click-dialog", "miniwob", "button", BUTTON_DEFECTS),
    Task("click-dialog-2", "miniwob", "button", BUTTON_DEFECTS),
    Task("button-delay", "miniwob", "button", BUTTON_DEFECTS),
    # Links / navigation — the name defect applies.
    Task("click-link", "miniwob", "link", LINK_DEFECTS + KEYBOARD_DEFECTS),
    Task("click-menu", "miniwob", "link", LINK_DEFECTS),
    Task("click-menu-2", "miniwob", "link", LINK_DEFECTS),
    Task("click-tab", "miniwob", "link", LINK_DEFECTS),
    Task("click-tab-2", "miniwob", "link", LINK_DEFECTS),
    # Labelled selection controls — detach_label removes the name.
    Task("click-checkboxes", "miniwob", "select", FORM_DEFECTS + KEYBOARD_DEFECTS),
    Task("click-checkboxes-soft", "miniwob", "select", FORM_DEFECTS),
    Task("click-option", "miniwob", "select", FORM_DEFECTS),
    Task("choose-list", "miniwob", "select", FORM_DEFECTS),
    Task("click-collapsible", "miniwob", "select", FORM_DEFECTS),
    # Text-entry forms — labels name the inputs.
    Task("enter-text", "miniwob", "form", FORM_DEFECTS + KEYBOARD_DEFECTS),
    Task("enter-text-dynamic", "miniwob", "form", FORM_DEFECTS),
    Task("enter-password", "miniwob", "form", FORM_DEFECTS),
    Task("login-user", "miniwob", "form", FORM_DEFECTS + KEYBOARD_DEFECTS),
    Task("use-autocomplete", "miniwob", "form", FORM_DEFECTS),
    Task("focus-text", "miniwob", "form", FORM_DEFECTS),
    Task("email-inbox-forward", "miniwob", "form", FORM_DEFECTS),
)

# Pending — the vendored web apps (pinned Docker). Tracked so the suite's shape
# is explicit; standing these up is the infrastructure half of A11.1′.
VENDORED_APPS: tuple[dict, ...] = (
    {"id": "conduit", "kind": "realworld-frontend", "status": "pending", "image": "TBD-pinned-digest"},
    {"id": "shop", "kind": "e-commerce-demo", "status": "pending", "image": "TBD-pinned-digest"},
    {"id": "admin", "kind": "admin-forms", "status": "pending", "image": "TBD-pinned-digest"},
)


def cells(tasks: tuple[Task, ...] = MINIWOB_TASKS, *, include_clean: bool = True) -> Iterator[tuple[Task, Optional[str]]]:
    """
    Yield every (task, variant) cell. `variant` is None for the clean control,
    else a defect name. The clean control is per task, not per defect — it is
    the same page, so it is yielded once.
    """
    for task in tasks:
        if include_clean:
            yield task, None
        for defect in task.defects:
            yield task, defect


def available(tasks: tuple[Task, ...] = MINIWOB_TASKS, html_dir: Path = MINIWOB_HTML) -> list[Task]:
    """The subset whose MiniWoB HTML is actually present (vendor fetched)."""
    return [t for t in tasks if t.app != "miniwob" or (html_dir / f"{t.id}.html").exists()]


def summary(tasks: tuple[Task, ...] = MINIWOB_TASKS) -> dict:
    """Shape of the suite: task count, cell count, families, defect coverage."""
    all_cells = list(cells(tasks))
    defect_cells = [c for c in all_cells if c[1] is not None]
    families: dict[str, int] = {}
    defects: dict[str, int] = {}
    for t in tasks:
        families[t.family] = families.get(t.family, 0) + 1
        for d in t.defects:
            defects[d] = defects.get(d, 0) + 1
    return {
        "tasks": len(tasks),
        "cells_total": len(all_cells),
        "cells_with_defect": len(defect_cells),
        "families": families,
        "defect_coverage": defects,
    }
