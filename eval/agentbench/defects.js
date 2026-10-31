/*
 * A10.5 — runtime defect overlay for the Agent Accessibility Benchmark.
 *
 * The static injectors in eval/inject/ rewrite HTML strings. MiniWoB++ (and
 * any app) builds its DOM with JavaScript per episode, so the same defects
 * are applied here, in the page, to whatever exists AND whatever appears
 * later (MutationObserver). Semantics mirror the static injectors:
 *
 *   detach_label   <label for> points at an id that does not exist
 *                  (eval/inject/detach_label.py) — inputs lose their name
 *   strip_name     buttons / links keep their visible text, but it is
 *                  aria-hidden, so the control has no accessible name
 *                  (aria_misuse.strip_accessible_name) — "empty button"
 *   div_button     <button> becomes a <div> with a click handler: no role,
 *                  no tab stop (aria_misuse.click_only_widget)
 *
 * Every defect is designed to be INVISIBLE to a sighted user — same pixels —
 * so any change in agent behaviour is attributable to the accessibility tree,
 * not to a visual change. The harness proves this with a pixel diff.
 *
 * Usage: window.__verityDefect(name)  (installed by add_init_script)
 */
(() => {
  const MARK = "data-verity-defect";

  function detachLabel(root) {
    for (const label of root.querySelectorAll("label[for]:not([" + MARK + "])")) {
      label.setAttribute(MARK, "detach_label");
      label.setAttribute("data-verity-original-for", label.getAttribute("for"));
      label.setAttribute("for", "verity-detached-" + Math.random().toString(36).slice(2));
    }
    // Implicit labels (<label><input></label>) name the input too: move the
    // input out of the label, visually in place, so the association breaks.
    for (const label of root.querySelectorAll("label:not([for]):not([" + MARK + "])")) {
      const input = label.querySelector("input, select, textarea");
      if (!input) continue;
      label.setAttribute(MARK, "detach_label");
      label.parentNode.insertBefore(input, label);
    }
  }

  function stripName(root) {
    // <input type=button> is left alone: its name IS its painted value, so it
    // cannot lose the name without changing pixels — and an invisible defect
    // is the whole point.
    for (const el of root.querySelectorAll("button:not([" + MARK + "]), a[href]:not([" + MARK + "])")) {
      el.setAttribute(MARK, "strip_name");
      for (const attr of ["aria-label", "aria-labelledby", "title"]) el.removeAttribute(attr);
      // Wrap all children in an aria-hidden span: same pixels, no name.
      const span = document.createElement("span");
      span.setAttribute("aria-hidden", "true");
      while (el.firstChild) span.appendChild(el.firstChild);
      el.appendChild(span);
    }
  }

  function divButton(root) {
    // Pixel-identical by construction. CSS cannot reproduce a native button's
    // OS-themed painting on a div (measured: 65–2,963 px different), so the
    // real <button> keeps painting itself but leaves the accessibility tree
    // and the Tab order (aria-hidden, tabindex=-1), and a TRANSPARENT roleless
    // <div> carrying the same text sits exactly over it and forwards clicks.
    // To an agent: a generic, roleless, unfocusable element with text — the
    // div-button anti-pattern. To a sighted user: nothing changed.
    for (const btn of root.querySelectorAll("button:not([" + MARK + "])")) {
      const host = btn.offsetParent;
      if (!host) continue; // not rendered: leave it alone
      btn.setAttribute(MARK, "div_button_original");
      btn.setAttribute("aria-hidden", "true");
      btn.tabIndex = -1;
      const div = document.createElement("div");
      div.setAttribute(MARK, "div_button");
      div.textContent = btn.textContent;
      const cs = getComputedStyle(btn);
      const place = () => {
        Object.assign(div.style, {
          position: "absolute", left: btn.offsetLeft + "px", top: btn.offsetTop + "px",
          width: btn.offsetWidth + "px", height: btn.offsetHeight + "px", margin: "0", padding: "0",
          border: "0", background: "transparent", color: "transparent", font: cs.font,
          overflow: "hidden", zIndex: "2147483647", cursor: cs.cursor, userSelect: "none",
        });
      };
      place();
      host.appendChild(div);
      div.addEventListener("click", () => btn.click());
      new ResizeObserver(place).observe(btn);
    }
  }

  // --- keyboard / focus defects (H3; added 2026-10-30 for the pre-registered
  // keyboard family). Invisible in a static render by construction: they only
  // change what happens when the keyboard is used.

  const FOCUSABLE = "a[href], button, input, select, textarea, [tabindex]:not([tabindex='-1'])";

  function rendered(el) {
    return el.offsetParent !== null || el.getClientRects().length > 0;
  }

  function keyboardTrap(root) {
    // The first rendered focusable control swallows Tab / Shift+Tab: focus can
    // reach it but never leave by keyboard (SC 2.1.2). Mirrors
    // eval/inject/keyboard_trap.py.
    if (document.querySelector("[" + MARK + "='keyboard_trap']")) return;
    const el = Array.from(root.querySelectorAll(FOCUSABLE)).find(rendered);
    if (!el) return;
    el.setAttribute(MARK, "keyboard_trap");
    el.addEventListener("keydown", (e) => {
      if (e.key === "Tab") { e.preventDefault(); e.stopPropagation(); el.focus(); }
    }, true);
  }

  function removeFromTabOrder(root) {
    // Every control leaves the Tab sequence (tabindex=-1): still clickable,
    // still in the accessibility tree, unreachable by Tab (SC 2.1.1).
    for (const el of root.querySelectorAll("a[href], button, input, select, textarea")) {
      if (el.hasAttribute(MARK)) continue;
      el.setAttribute(MARK, "remove_from_tab_order");
      el.tabIndex = -1;
    }
  }

  function outlineNone() {
    // No visible focus indicator anywhere (SC 2.4.7). A static screenshot has
    // nothing focused, so pixels are unchanged until the keyboard is used.
    if (document.querySelector("style[" + MARK + "='outline_none']")) return;
    const style = document.createElement("style");
    style.setAttribute(MARK, "outline_none");
    style.textContent = "*:focus, *:focus-visible { outline: none !important; box-shadow: none !important; }";
    document.head.appendChild(style);
  }

  const DEFECTS = {
    detach_label: detachLabel, strip_name: stripName, div_button: divButton,
    keyboard_trap: keyboardTrap, remove_from_tab_order: removeFromTabOrder, outline_none: outlineNone,
  };

  window.__verityDefect = (name) => {
    const fn = DEFECTS[name];
    if (!fn) throw new Error("unknown defect " + name);
    const apply = () => fn(document);
    apply();
    new MutationObserver(apply).observe(document.documentElement, { childList: true, subtree: true });
    window.__verityDefectApplied = name;
  };
})();
