// Theme: system (follow the OS), light or dark. Loaded before the page draws
// so it never flashes the wrong one. A per-viewer choice, kept in this browser.
(function () {
  "use strict";
  var KEY = "dqlTheme", listeners = [];
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function get() {
    try {
      var v = localStorage.getItem(KEY);
      if (v === "light" || v === "dark") return v;
      if (chosen === null) return "system";
    } catch (e) { /* blocked */ }
    return chosen || "system";
  }
  // What is on screen now: "light" or "dark".
  function resolved() {
    var t = get();
    return t === "system" ? (media && media.matches ? "dark" : "light") : t;
  }
  function apply() {
    var t = get();
    if (t === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    listeners.forEach(function (fn) { fn(t, resolved()); });
  }
  var chosen = null;      // when storage is blocked, the choice lasts for this page
  function set(t) {
    chosen = t === "light" || t === "dark" ? t : "system";
    try {
      if (chosen === "system") localStorage.removeItem(KEY); else localStorage.setItem(KEY, chosen);
    } catch (e) { /* blocked */ }
    apply();
  }
  if (media && media.addEventListener) media.addEventListener("change", function () { if (get() === "system") apply(); });
  apply();
  window.DqlTheme = { get: get, set: set, resolved: resolved, onChange: function (fn) { listeners.push(fn); } };
})();
