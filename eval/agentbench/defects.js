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

  const DEFECTS = { detach_label: detachLabel, strip_name: stripName, div_button: divButton };

  window.__verityDefect = (name) => {
    const fn = DEFECTS[name];
    if (!fn) throw new Error("unknown defect " + name);
    const apply = () => fn(document);
    apply();
    new MutationObserver(apply).observe(document.documentElement, { childList: true, subtree: true });
    window.__verityDefectApplied = name;
  };
})();
