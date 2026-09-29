// The chat page: sends questions, streams the agent's steps, asks before a
// query runs, draws the charts and graphs the agent returns, and keeps a list
// of past chats to reopen. Everything from the server or the model is
// inserted as text, never as HTML.
(function () {
  "use strict";
  var $ = function (s) { return document.querySelector(s); };
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function button(text, cls, onclick) {
    var b = el("button", cls, text);
    b.type = "button";
    if (onclick) b.addEventListener("click", onclick);
    return b;
  }
  function keep(storage, key, value) {
    try {
      if (value === undefined) return storage.getItem(key);
      storage.setItem(key, value);
    } catch (e) { /* storage blocked: keep going without it */ }
    return value;
  }
  function tab(key, value) { return keep(window.sessionStorage, key, value); }       // this tab
  function local(key, value) { return keep(window.localStorage, key, value); }      // this browser
  function newId() {
    var raw = window.crypto && crypto.randomUUID ? crypto.randomUUID()
      : String(Date.now()) + Math.random().toString(16).slice(2);
    return raw.replace(/[^A-Za-z0-9_-]/g, "");
  }

  // -- icons (inline SVG, drawn with DOM calls) ----------------------------
  var SVG = "http://www.w3.org/2000/svg";
  var ICONS = {
    "arrow-up": [["path", { d: "M12 19V5" }], ["path", { d: "m5 12 7-7 7 7" }]],
    stop: [["rect", { x: 7, y: 7, width: 10, height: 10, rx: 1.5, fill: "currentColor", stroke: "none" }]],
    settings: [["path", { d: "M20 7h-9" }], ["path", { d: "M14 17H5" }], ["circle", { cx: 17, cy: 17, r: 3 }], ["circle", { cx: 7, cy: 7, r: 3 }]],
    sidebar: [["rect", { x: 3, y: 3, width: 18, height: 18, rx: 2 }], ["path", { d: "M9 3v18" }]],
    "new": [["path", { d: "M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" }],
            ["path", { d: "M18.4 2.6a1 1 0 0 1 3 3l-9 9a2 2 0 0 1-.85.5l-2.87.84a.5.5 0 0 1-.62-.62l.84-2.87a2 2 0 0 1 .5-.85z" }]],
    x: [["path", { d: "M18 6 6 18" }], ["path", { d: "m6 6 12 12" }]],
    chevron: [["path", { d: "m6 9 6 6 6-6" }]],
    shield: [["path", { d: "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" }]],
    forward: [["path", { d: "m6 17 5-5-5-5" }], ["path", { d: "m13 17 5-5-5-5" }]],
    dots: [["circle", { cx: 5, cy: 12, r: 1 }], ["circle", { cx: 12, cy: 12, r: 1 }], ["circle", { cx: 19, cy: 12, r: 1 }]],
    expand: [["path", { d: "M15 3h6v6" }], ["path", { d: "M9 21H3v-6" }], ["path", { d: "M21 3l-7 7" }], ["path", { d: "M3 21l7-7" }]],
    shrink: [["path", { d: "M4 14h6v6" }], ["path", { d: "M20 10h-6V4" }], ["path", { d: "M14 10l7-7" }], ["path", { d: "M3 21l7-7" }]],
    check: [["path", { d: "M20 6 9 17l-5-5" }]],
    alert: [["path", { d: "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" }],
            ["path", { d: "M12 9v4" }], ["path", { d: "M12 17h.01" }]],
    ok: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "m9 12 2 2 4-4" }]]
  };
  function icon(name) {
    var svg = document.createElementNS(SVG, "svg");
    var attrs = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2,
                  "stroke-linecap": "round", "stroke-linejoin": "round", "class": "icon", "aria-hidden": "true" };
    Object.keys(attrs).forEach(function (k) { svg.setAttribute(k, attrs[k]); });
    (ICONS[name] || []).forEach(function (p) {
      var e = document.createElementNS(SVG, p[0]);
      Object.keys(p[1]).forEach(function (k) { e.setAttribute(k, p[1][k]); });
      svg.appendChild(e);
    });
    return svg;
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-icon]"), function (n) {
    n.insertBefore(icon(n.getAttribute("data-icon")), n.firstChild);
  });

  // -- state -------------------------------------------------------------
  // The token arrives once in the URL (?t=...), then lives in this tab only.
  var params = new URLSearchParams(location.search);
  if (params.get("t")) {
    tab("dqlToken", params.get("t"));
    history.replaceState(null, "", location.pathname);
  }
  var state = {
    token: tab("dqlToken") || "",
    session: tab("dqlSession") || tab("dqlSession", newId()),   // the open conversation
    config: null,
    ready: false,
    busy: false,
    auto: false,
    history: false,
    conversations: [],
    providerModels: {},   // provider -> {options, loading, error} for the model picker
    stops: []          // unmount functions of drawn charts and graphs
  };
  var app = $("#app"), log = $("#log"), input = $("#input"), sendBtn = $("#send");
  var expandedViz = null;    // the chart or graph blown up to fill the window

  function headers(json) {
    var h = { "X-DQL-Token": state.token, "X-DQL-Client": "1" };
    if (json) h["Content-Type"] = "application/json";
    return h;
  }
  function api(path, body) {
    var opts = { method: body ? "POST" : "GET", headers: headers(!!body) };
    var url = path;
    if (body) {
      opts.body = JSON.stringify(Object.assign({ session: state.session }, body));
    } else {
      url += (path.indexOf("?") >= 0 ? "&" : "?") + "session=" + encodeURIComponent(state.session);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
        return data;
      });
    });
  }

  function nearBottom() { return log.scrollHeight - log.scrollTop - log.clientHeight < 120; }
  function scroll(force) { if (force || nearBottom()) log.scrollTop = log.scrollHeight; }
  function noteLine(text) { var n = el("div", "note-line", text); log.appendChild(n); scroll(true); return n; }

  // -- header, mode and model pills ----------------------------------------
  function field(key) {
    var fs = (state.config && state.config.fields) || [];
    for (var i = 0; i < fs.length; i++) if (fs[i].key === key) return fs[i];
    return null;
  }
  function currentModel() { var f = field("model"); return f && f.value ? String(f.value) : ""; }
  // us.anthropic.claude-haiku-4-5-20251001-v1:0 -> claude-haiku-4-5
  function modelShort(id) {
    return String(id || "").replace(/^(us|eu|apac|global|us-gov|jp|au|ca)\./, "")
      .replace(/^[a-z0-9-]+\.(?=[a-z])/, "")
      .replace(/-\d{8}(-v\d+:\d+)?$/, "").replace(/-v\d+:\d+$/, "");
  }

  function showConfig(cfg) {
    state.config = cfg;
    var parts = [cfg.can_run ? "tenant " + cfg.tenant : "no tenant: queries are written, not run"];
    if (cfg.user) parts.push(cfg.user);
    $("#meta").textContent = parts.join(" · ");
    $("#meta").title = $("#meta").textContent;
    var pill = $("#model-pill");
    pill.textContent = "";
    var multi = (cfg.providers || []).length > 1;
    pill.appendChild(el("span", null, cfg.error ? "Model not ready"
      : (modelShort(currentModel()) || cfg.model_name) + (multi ? " · " + cfg.provider_short : "")));
    pill.appendChild(icon("chevron"));
    pill.title = cfg.error ? cfg.error : cfg.provider_label + ": " + cfg.model_name +
      (cfg.allow_settings ? " · click to switch (/model)" : " · fixed on this server");
    pill.disabled = !cfg.allow_settings && !cfg.error;
    var h = cfg.history || {};
    state.history = !!h.on;
    $("#history-note").textContent = h.on
      ? "Chats are kept on this server" + (h.days ? " for " + h.days + " days." : ".")
      : "History is off on this server: chats last until it restarts.";
    var chosen = local("dqlAuto");
    state.auto = cfg.can_run && (chosen === null || chosen === undefined ? !!cfg.auto_run : chosen === "1");
    renderMode();
  }

  function renderMode() {
    var m = $("#mode"), can = !!(state.config && state.config.can_run), on = state.auto && can;
    m.textContent = "";
    m.disabled = !can;
    m.setAttribute("aria-pressed", on ? "true" : "false");
    m.appendChild(icon(on ? "forward" : "shield"));
    m.appendChild(el("span", null, !can ? "Queries are written, not run" : on ? "Run automatically" : "Ask before running"));
    m.title = !can ? "No tenant is configured on the server."
      : on ? "Queries run as soon as the model writes them; each is still checked for common DQL mistakes. Click to approve each one."
           : "You approve each query before it runs. Click to run them automatically.";
  }
  function setAuto(on) {
    state.auto = !!on;
    local("dqlAuto", on ? "1" : "0");
    renderMode();
  }

  function renderSend() {
    sendBtn.textContent = "";
    if (state.busy) {
      sendBtn.dataset.state = "stop";
      sendBtn.setAttribute("aria-label", "Stop");
      sendBtn.title = "Stop (Esc)";
      sendBtn.disabled = false;
      sendBtn.appendChild(icon("stop"));
    } else {
      sendBtn.dataset.state = "send";
      sendBtn.setAttribute("aria-label", "Send");
      sendBtn.title = "Send (Enter)";
      sendBtn.disabled = !state.ready || !input.value.trim();
      sendBtn.appendChild(icon("arrow-up"));
    }
  }
  function setTitle(t) { $("#conv-title").textContent = t || "New chat"; document.title = (t ? t + " · " : "") + "DQL chat"; }

  // -- welcome -----------------------------------------------------------
  var EXAMPLES = [
    "Any open problems right now?",
    "Which hosts had CPU above 90% in the last hour?",
    "Chart CPU for the five busiest hosts over the last 6 hours",
    "Draw who calls whom between processes",
    "Errors in logs over the last hour, by host"
  ];
  function welcome() {
    var w = el("div", "welcome");
    w.appendChild(el("h1", null, "What do you want to know about your tenant?"));
    w.appendChild(el("p", null, "The model searches this repo's DQL reference, checks every metric and " +
      "field name against your tenant, runs the query and answers from the records, with a short summary " +
      "and anything worth a look. It can draw charts and graphs from what it ran."));
    var hint = state.config && state.config.problems_hint;
    if (hint) w.appendChild(problemsCard());
    var chips = el("div", "chips");
    EXAMPLES.forEach(function (q) {
      if (hint && q === PROBLEMS_Q) return;          // the card above asks it
      chips.appendChild(button(q, "chip", function () { send(q); }));
    });
    w.appendChild(chips);
    if (state.config && state.config.error) {
      var b = el("div", "banner");
      b.appendChild(el("strong", null, "The model is not ready. "));
      b.appendChild(document.createTextNode(state.config.error + " "));
      b.appendChild(button("Pick a model", "ghost", function () { openModelMenu(); }));
      w.insertBefore(b, w.firstChild);
    }
    log.appendChild(w);
  }
  // -- open problems: a card on the welcome screen, a badge in the top bar ----
  // The server runs one fixed read-only query (never the model's); a click
  // hands the question to the agent like any other.
  var PROBLEMS_Q = "Any open problems right now?";
  var problemsReq = null;          // {at, promise}: one request per 30 s
  function loadProblems() {
    if (!state.config || !state.config.problems_hint) return Promise.resolve(null);
    if (problemsReq && Date.now() - problemsReq.at < 30000) return problemsReq.promise;
    var p = api("/api/problems").catch(function (e) { return { enabled: true, error: e.message }; })
      .then(function (d) { renderBadge(d); return d; });
    problemsReq = { at: Date.now(), promise: p };
    return p;
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function catLabel(c) {
    c = String(c || "").replace(/_/g, " ").toLowerCase();
    return c.charAt(0).toUpperCase() + c.slice(1);
  }
  function renderBadge(d) {
    var b = $("#problems-badge"), n = d && d.enabled && !d.error ? d.open : 0;
    b.hidden = !n;
    if (!n) return;
    b.textContent = "";
    b.appendChild(icon("alert"));
    b.appendChild(el("span", null, plural(n, "open problem", "open problems")));
    b.title = "Davis problems open on the tenant. Click to ask about them.";
  }
  $("#problems-badge").addEventListener("click", function () { send(PROBLEMS_Q); });
  function askProblem(p) {
    send("What is problem " + p.id + " (" + p.name + ") affecting, and since when?");
  }
  function problemsCard() {
    var card = el("section", "problems-card loading");
    card.setAttribute("aria-live", "polite");
    card.setAttribute("aria-label", "Open problems");
    var head = el("div", "pc-head");
    head.appendChild(el("span", "pc-title spin", "Checking for open problems…"));
    card.appendChild(head);
    loadProblems().then(function (d) {
      if (!d || !card.isConnected) return;
      card.classList.remove("loading");
      head.textContent = "";
      if (d.error) {
        card.classList.add("unknown");
        head.appendChild(el("span", "pc-title", "Could not check for open problems"));
        head.appendChild(button("Ask the agent", "ghost pc-action", function () { send(PROBLEMS_Q); }));
        card.appendChild(el("p", "pc-note", d.error));
        return;
      }
      if (!d.open) {
        card.classList.add("ok");
        head.appendChild(icon("ok"));
        head.appendChild(el("span", "pc-title", "No open problems right now"));
        head.appendChild(button("Any in the last 24 hours?", "ghost pc-action",
          function () { send("Any problems in the last 24 hours, open or closed?"); }));
      } else {
        card.classList.add("alert");
        head.appendChild(icon("alert"));
        head.appendChild(el("span", "pc-title", plural(d.open, "open problem", "open problems")));
        head.appendChild(el("span", "pc-cats", Object.keys(d.by_category || {}).map(function (k) {
          return d.by_category[k] + " " + catLabel(k).toLowerCase();
        }).join(" · ")));
        head.appendChild(button("Look at them", "primary pc-action", function () { send(PROBLEMS_Q); }));
        var list = el("div", "pc-list");
        (d.items || []).forEach(function (p) {
          var r = button(null, "pc-item", function () { askProblem(p); });
          r.appendChild(el("span", "pc-id", p.id));
          r.appendChild(el("span", "pc-name", p.name));
          r.appendChild(el("span", "pc-cat", catLabel(p.category)));
          r.appendChild(el("span", "pc-when", p.start ? when(p.start) : ""));
          r.title = "Ask about " + p.id + (p.affected ? ", " + plural(p.affected, "affected entity", "affected entities") : "");
          list.appendChild(r);
        });
        card.appendChild(list);
        if (d.open > (d.items || []).length) {
          card.appendChild(el("p", "pc-note", (d.open - d.items.length) + " more; Look at them covers all of them."));
        }
      }
      var ago = when(d.checked);
      card.appendChild(el("p", "pc-foot", "Checked " + (ago === "now" ? "just now" : ago + " ago") +
        " with a fixed read-only query (" + d.scanned + " scanned), not by the model."));
    });
    return card;
  }

  function clearLog(withWelcome) {
    state.stops.forEach(function (stop) { try { stop(); } catch (e) { /* already gone */ } });
    state.stops = [];
    log.textContent = "";
    if (withWelcome !== false) welcome();
  }
  function addYou(text) {
    var w = log.querySelector(".welcome");
    if (w) w.remove();
    var you = el("div", "you");
    you.appendChild(el("div", null, text));
    log.appendChild(you);
  }

  // -- a turn: the agent's steps for one question -------------------------
  function newTurn() {
    var box = el("section", "turn");
    log.appendChild(box);
    var spinner = null, card = null, cards = [];

    function step(label, detail, cls) {
      var s = el("div", "step" + (cls ? " " + cls : ""));
      s.appendChild(el("span", null, label));
      if (detail) {
        var d = el("span", "detail", detail);
        d.title = detail;
        s.appendChild(d);
      }
      box.appendChild(s);
      return s;
    }

    function queryCard(query) {
      var c = el("div", "qcard");
      var head = el("div", "qhead");
      head.appendChild(el("span", "qlabel", "Query"));
      var status = el("span", "qstatus", "Checking…");
      head.appendChild(status);
      head.appendChild(window.DqlMarkdown.copyButton(function () { return query; }));
      head.lastChild.classList.remove("copy");
      c.appendChild(head);
      var pre = el("pre");
      pre.appendChild(el("code", null, query));
      c.appendChild(pre);
      box.appendChild(c);
      var card = {
        settled: false,
        status: function (text, kind) {
          status.textContent = text;
          status.className = "qstatus" + (kind ? " " + kind : "");
        },
        // "Run this query?" with numbered options, like a permission prompt.
        ask: function (id) {
          var self = this;
          self.status("Waiting for you", "warn");
          var p = el("div", "qprompt");
          p.setAttribute("role", "group");
          p.setAttribute("aria-label", "Run this query?");
          p.appendChild(el("div", "qprompt-title", "Run this query?"));
          function opt(n, text, cls) {
            var b = button(null, "opt " + cls);
            b.appendChild(el("kbd", null, n));
            b.appendChild(el("span", null, text));
            return b;
          }
          var yes = opt("1", "Yes", "opt-yes");
          var always = opt("2", "Yes, and don't ask again", "opt-always");
          var noRow = el("div", "opt opt-no");
          noRow.appendChild(el("kbd", null, "3"));
          var said = el("input");
          said.placeholder = "No, and tell the model what to do differently";
          said.setAttribute("aria-label", "No, and tell the model what to do differently");
          noRow.appendChild(said);
          var noBtn = button("Don't run", "ghost opt-no-btn");
          noRow.appendChild(noBtn);
          noRow.addEventListener("click", function (ev) { if (ev.target === noRow) said.focus(); });
          said.addEventListener("input", function () { noBtn.textContent = said.value.trim() ? "Send" : "Don't run"; });
          p.appendChild(yes);
          p.appendChild(always);
          p.appendChild(noRow);
          p.appendChild(el("p", "opt-hint", "Press 1, 2 or 3 · Esc declines"));
          var done = false;
          function answer(run, text) {
            if (done) return;
            done = true;
            Array.prototype.forEach.call(p.querySelectorAll("button,input"), function (n) { n.disabled = true; });
            self.status(run ? "Running…" : (text ? "Sent your change" : "Not run"), run ? "" : "muted");
            api("/api/approve", { id: id, run: run, said: text || "" }).catch(function (e) {
              self.status("Could not answer the prompt: " + e.message, "error");
            });
            setTimeout(function () { p.remove(); input.focus(); }, 250);
          }
          yes.addEventListener("click", function () { answer(true); });
          always.addEventListener("click", function () { setAuto(true); answer(true); });
          noBtn.addEventListener("click", function () { answer(false, said.value.trim()); });
          said.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter") { ev.preventDefault(); answer(false, said.value.trim()); }
          });
          p.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); answer(false, said.value.trim()); return; }
            if (ev.target === said) return;
            if (ev.key === "1") { ev.preventDefault(); answer(true); }
            else if (ev.key === "2") { ev.preventDefault(); setAuto(true); answer(true); }
            else if (ev.key === "3") { ev.preventDefault(); said.focus(); }
          });
          c.appendChild(p);
          yes.focus();
        },
        result: function (d) {
          this.status(d.record_count + (d.record_count === 1 ? " record" : " records") + " · " + d.scanned + " scanned" +
                      (d.notes && d.notes.length ? " · " + d.notes[0] : ""), "ok");
          if (!d.rows || !d.rows.length) return;
          var det = el("details", "records");
          var shown = d.rows.length < d.record_count ? d.rows.length + " of " + d.record_count : String(d.rows.length);
          det.appendChild(el("summary", null, "Show " + shown + " records"));
          det.addEventListener("toggle", function () {
            if (!det.open || det.childNodes.length > 1) return;
            det.appendChild(recordsTable(d.fields, d.rows));
          });
          c.appendChild(det);
        }
      };
      cards.push(card);
      return card;
    }

    function figure(spec) {
      var fig = el("figure", "viz-card");
      var cap = el("figcaption");
      cap.appendChild(el("span", "viz-title", spec.title || (spec.kind === "graph" ? "Graph" : "Chart")));
      if (spec.unit) cap.appendChild(el("span", "viz-unit", "(" + spec.unit + ")"));
      cap.appendChild(el("span", "spacer"));
      var grow = button(null, "icon-btn viz-expand", function () { setExpanded(!fig.classList.contains("expanded")); });
      cap.appendChild(grow);
      fig.appendChild(cap);
      if (spec.dropped) fig.appendChild(el("p", "viz-note", spec.dropped + " more not shown (the largest are drawn). Narrow the query to see them."));
      if (spec.truncated) fig.appendChild(el("p", "viz-note", "Cut at 150 nodes / 400 edges. Narrow the query to see the rest."));
      var body = el("div", "viz-body");
      fig.appendChild(body);
      var foot = el("div", "viz-foot");
      var src = spec.source || {};
      foot.appendChild(el("span", null, "Drawn from query " + (src.result_id || "") + ", not typed by the model"));
      var showingTable = false, stop = null;
      function draw() {
        if (stop) { stop(); stop = null; }
        body.textContent = "";
        if (showingTable) {
          body.appendChild(spec.kind === "graph" ? window.DqlFlow.table(spec) : window.DqlCharts.table(spec));
        } else if (spec.kind === "graph") {
          stop = window.DqlFlow.graph(spec, body);
          if (fig.classList.contains("expanded") && stop.resize) stop.resize(true);
        } else if (spec.kind === "bar") {
          stop = window.DqlCharts.bar(spec, body);
        } else {
          stop = window.DqlCharts.timeseries(spec, body);
        }
      }
      // Leaving the chat: drop the expanded view without redrawing, then unmount.
      state.stops.push(function () { setExpanded(false, true); if (stop) stop(); });

      // Expand: the card fills the window over a backdrop; the same button,
      // Esc or a click on the backdrop puts it back. Graphs re-fit the new
      // box and keep what was dragged; charts redraw at the new size.
      function paintGrow(on) {
        grow.textContent = "";
        grow.appendChild(icon(on ? "shrink" : "expand"));
        grow.setAttribute("aria-label", on ? "Restore size" : "Expand");
        grow.setAttribute("aria-pressed", on ? "true" : "false");
        grow.title = on ? "Restore size (Esc)" : "Expand";
      }
      function setExpanded(on, quiet) {
        if (on === fig.classList.contains("expanded")) return;
        if (on && expandedViz) expandedViz.collapse();
        fig.classList.toggle("expanded", on);
        app.classList.toggle("viz-open", on);
        if (on) {
          var shade = el("div", "viz-backdrop");
          shade.addEventListener("click", function () { setExpanded(false); });
          document.body.appendChild(shade);
          expandedViz = { fig: fig, shade: shade, collapse: function () { setExpanded(false); } };
          fig.setAttribute("role", "dialog");
          fig.setAttribute("aria-modal", "true");
          fig.setAttribute("aria-label", (spec.title || "Chart") + ", expanded");
        } else {
          if (expandedViz && expandedViz.fig === fig) { expandedViz.shade.remove(); expandedViz = null; }
          fig.removeAttribute("role");
          fig.removeAttribute("aria-modal");
          fig.removeAttribute("aria-label");
        }
        paintGrow(on);
        if (quiet) return;
        if (stop && stop.resize) stop.resize(on);
        grow.focus();
        if (!on) fig.scrollIntoView({ block: "nearest" });
      }
      paintGrow(false);

      var toggle = button("Table", "ghost viz-toggle", function () {
        showingTable = !showingTable;
        toggle.textContent = showingTable ? (spec.kind === "graph" ? "Graph" : "Chart") : "Table";
        draw();
      });
      foot.appendChild(toggle);
      if (src.query) {
        var det = el("details");
        det.appendChild(el("summary", null, "Query"));
        var pre = el("pre");
        pre.appendChild(el("code", null, src.query));
        det.appendChild(pre);
        foot.appendChild(det);
      }
      fig.appendChild(foot);
      box.appendChild(fig);
      draw();
    }

    function clearSpinner() { if (spinner) { spinner.remove(); spinner = null; } }

    return {
      on: function (kind, d) {
        if (kind !== "thinking") clearSpinner();
        switch (kind) {
          case "thinking": clearSpinner(); spinner = step("Thinking…", null, "spin"); break;
          case "tool": step(d.name === "search_docs" ? "Searched the docs:" : "Checked names:", d.detail); break;
          case "query": card = queryCard(d.query); break;
          case "lint": if (card) { card.settled = true; card.status("Stopped before running: " + d.issues.join(" "), "warn"); } break;
          case "approval": if (card) card.ask(d.id); break;
          case "skipped": if (card) { card.settled = true; card.status(d.said ? "Not run. You said: " + d.said : "Not run", "muted"); } break;
          case "result": if (card) { card.settled = true; card.result(d); } break;
          case "query_error": if (card) { card.settled = true; card.status(d.summary, "error"); } break;
          case "visual": figure(d.spec); break;
          case "visual_error": step("Could not draw:", d.message, "muted"); break;
          case "answer":
            var a = el("div", "answer");
            a.appendChild(window.DqlMarkdown.render(d.text || ""));
            box.appendChild(a);
            break;
          case "error":
            var err = el("div", "error-box", d.text);
            // A model the account or server cannot use: fix it here, not in .env.
            if (/not (available|enabled|found)|no such model|unknown model|does not exist|access denied/i.test(d.text) &&
                state.config && state.config.allow_settings) {
              var fix = button("Pick another model", "ghost error-fix", function () { openModelMenu(); });
              err.appendChild(fix);
            }
            box.appendChild(err);
            break;
          case "cancelled": step("Stopped.", null); break;
        }
        scroll();
      },
      error: function (text) { clearSpinner(); box.appendChild(el("div", "error-box", text)); scroll(); },
      // A reopened chat, or an answer that ended early: a query with no
      // outcome did not run.
      finish: function () {
        clearSpinner();
        cards.forEach(function (c) { if (!c.settled) c.status("Not run", "muted"); });
      }
    };
  }

  function cellText(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "number") return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  }
  function recordsTable(fields, rows) {
    var cols = fields.slice(0, 16);
    var wrap = el("div", "tablewrap");
    var t = el("table", "data"), thead = el("thead"), tbody = el("tbody"), hr = el("tr");
    cols.forEach(function (f) { hr.appendChild(el("th", null, f)); });
    thead.appendChild(hr); t.appendChild(thead); t.appendChild(tbody); wrap.appendChild(t);
    rows.forEach(function (r) {
      var tr = el("tr");
      cols.forEach(function (f) {
        var text = cellText(r[f]);
        var td = el("td", typeof r[f] === "number" ? "num" : null, text);
        td.title = text;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    return wrap;
  }

  // -- sending and streaming ---------------------------------------------
  function setBusy(b) {
    state.busy = b;
    input.disabled = b;
    renderSend();
    if (!b) input.focus();
  }

  function send(text) {
    text = (text || "").trim();
    if (!text || state.busy || !state.ready) return;
    addYou(text);
    input.value = "";
    autosize();
    var turn = newTurn();
    setBusy(true);
    scroll(true);
    var sid = state.session;
    fetch("/api/chat", {
      method: "POST", headers: headers(true),
      body: JSON.stringify({ session: sid, message: text, auto: state.auto })
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (d) { turn.error(d.error || "HTTP " + r.status); });
      }
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = "";
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) return;
          buf += dec.decode(res.value, { stream: true });
          var idx;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            var chunk = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            var kind = "message", data = "";
            chunk.split("\n").forEach(function (line) {
              if (line.indexOf("event:") === 0) kind = line.slice(6).trim();
              else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
            });
            if (!data) continue;
            var parsed;
            try { parsed = JSON.parse(data); } catch (e) { continue; }   // skip a malformed event
            if (kind === "conversation") { conversationStarted(parsed); continue; }
            turn.on(kind, parsed);
          }
          return pump();
        });
      }
      return pump();
    }).catch(function (e) {
      turn.error("Connection lost: " + e.message);
    }).then(function () {
      turn.finish();
      setBusy(false);
      if (state.history) loadRecents();
    });
  }

  function cancel() { if (state.busy) api("/api/cancel", {}).catch(function () {}); }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(220, input.scrollHeight + 2) + "px";
  }

  // -- conversations (history) --------------------------------------------
  function when(ts) {
    var s = Date.now() / 1000 - ts;
    if (s < 60) return "now";
    if (s < 3600) return Math.floor(s / 60) + "m";
    if (s < 86400) return Math.floor(s / 3600) + "h";
    if (s < 7 * 86400) return Math.floor(s / 86400) + "d";
    return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function loadRecents() {
    return api("/api/conversations").then(function (d) {
      state.history = !!d.history;
      state.conversations = d.conversations || [];
      renderRecents();
    }).catch(function () { /* the list is a convenience; the chat still works */ });
  }

  function conversationStarted(c) {
    setTitle(c.title);
    if (!state.conversations.some(function (x) { return x.id === c.id; })) {
      state.conversations.unshift({ id: c.id, title: c.title, updated: Date.now() / 1000, turns: 1 });
      renderRecents();
    }
  }

  function renderRecents() {
    var nav = $("#recents");
    closeRowMenu();
    nav.textContent = "";
    $("#recents-label").hidden = !state.history;
    if (!state.history) return;
    if (!state.conversations.length) { nav.appendChild(el("p", "side-note", "No chats yet.")); return; }
    state.conversations.forEach(function (c) {
      var row = el("div", "recent" + (c.id === state.session ? " current" : ""));
      row.dataset.id = c.id;
      var open = button(null, "recent-open", function () { openConversation(c.id); closeSideIfNarrow(); });
      open.appendChild(el("span", "recent-title", c.title || "Untitled"));
      open.appendChild(el("span", "recent-when", when(c.updated)));
      open.title = c.title || "";
      if (c.id === state.session) open.setAttribute("aria-current", "page");
      var more = button(null, "icon-btn recent-more");
      more.appendChild(icon("dots"));
      more.setAttribute("aria-label", "More for " + (c.title || "this chat"));
      more.setAttribute("aria-haspopup", "menu");
      more.setAttribute("aria-expanded", "false");
      more.addEventListener("click", function (ev) { ev.stopPropagation(); rowMenu(row, c, more); });
      row.appendChild(open);
      row.appendChild(more);
      nav.appendChild(row);
    });
  }

  var rowMenuEl = null;
  function closeRowMenu() {
    if (!rowMenuEl) return;
    var btn = rowMenuEl.parentNode && rowMenuEl.parentNode.querySelector(".recent-more");
    if (btn) btn.setAttribute("aria-expanded", "false");
    rowMenuEl.remove();
    rowMenuEl = null;
  }
  function rowMenu(row, c, more) {
    var wasOpen = rowMenuEl && rowMenuEl.parentNode === row;
    closeRowMenu();
    if (wasOpen) return;
    var m = el("div", "popover row-menu");
    m.setAttribute("role", "menu");
    var rename = button("Rename", "menu-item", function () { closeRowMenu(); startRename(row, c); });
    var del = button("Delete", "menu-item danger", function (ev) {
      ev.stopPropagation();
      if (!del.dataset.armed) { del.dataset.armed = "1"; del.textContent = "Delete for good?"; return; }
      closeRowMenu();
      api("/api/conversation/delete", { id: c.id }).then(function () {
        state.conversations = state.conversations.filter(function (x) { return x.id !== c.id; });
        if (c.id === state.session) newChat();
        else renderRecents();
      }).catch(function (e) { noteLine("Could not delete: " + e.message); });
    });
    [rename, del].forEach(function (b) { b.setAttribute("role", "menuitem"); m.appendChild(b); });
    row.appendChild(m);
    rowMenuEl = m;
    more.setAttribute("aria-expanded", "true");
    rename.focus();
  }
  function startRename(row, c) {
    var inp = el("input", "recent-edit");
    inp.value = c.title || "";
    inp.setAttribute("aria-label", "Chat title");
    row.textContent = "";
    row.appendChild(inp);
    inp.focus();
    inp.select();
    var finished = false;
    function finish(save) {
      if (finished) return;
      finished = true;
      var t = inp.value.trim();
      if (!save || !t || t === c.title) { renderRecents(); return; }
      api("/api/conversation/rename", { id: c.id, title: t }).then(function () {
        c.title = t;
        if (c.id === state.session) setTitle(t);
        renderRecents();
      }).catch(function (e) { renderRecents(); noteLine("Could not rename: " + e.message); });
    }
    inp.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); finish(true); }
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); finish(false); }
    });
    inp.addEventListener("blur", function () { finish(true); });
  }

  function newChat() {
    if (state.busy) return;
    state.session = newId();
    tab("dqlSession", state.session);
    clearLog();
    setTitle("");
    renderRecents();
    input.focus();
  }

  function openConversation(id) {
    if (state.busy) { noteLine("Stop the current answer before switching chats."); return Promise.resolve(); }
    return api("/api/conversation?id=" + encodeURIComponent(id)).then(function (conv) {
      state.session = id;
      tab("dqlSession", id);
      clearLog(false);
      setTitle(conv.title);
      replay(conv.events || []);
      renderRecents();
      scroll(true);
      input.focus();
    }).catch(function (e) { noteLine("Could not open that chat: " + e.message); });
  }

  function replay(events) {
    var turn = null;
    events.forEach(function (ev) {
      if (ev.kind === "user") {
        if (turn) turn.finish();
        addYou(ev.data.text || "");
        turn = newTurn();
        return;
      }
      if (!turn) turn = newTurn();
      turn.on(ev.kind, ev.data || {});
    });
    if (turn) turn.finish();
  }

  // -- sidebar -----------------------------------------------------------
  var narrow = window.matchMedia("(max-width: 900px)");
  function closeSideIfNarrow() { if (narrow.matches) app.classList.remove("side-open"); }
  if (local("dqlSide") === "0") app.classList.add("side-collapsed");
  $("#btn-side").addEventListener("click", function () {
    if (narrow.matches) { app.classList.toggle("side-open"); return; }
    var collapsed = app.classList.toggle("side-collapsed");
    local("dqlSide", collapsed ? "0" : "1");
  });
  $("#btn-side-close").addEventListener("click", function () { app.classList.remove("side-open"); });
  $("#scrim").addEventListener("click", function () { app.classList.remove("side-open"); });
  function showRecents() {
    if (narrow.matches) app.classList.add("side-open");
    else { app.classList.remove("side-collapsed"); local("dqlSide", "1"); }
    var first = $("#recents .recent-open");
    if (first) first.focus();
    if (!state.history) noteLine("History is off on this server, so there are no past chats to reopen.");
  }
  $("#btn-new").addEventListener("click", function () { newChat(); closeSideIfNarrow(); });

  // -- slash commands ----------------------------------------------------
  var COMMANDS = [
    { cmd: "/clear", desc: "Start a new chat (this one stays in Recents)", run: function () { newChat(); } },
    { cmd: "/resume", desc: "Reopen a past chat", run: function () { showRecents(); } },
    { cmd: "/model", desc: "Switch the model", run: function () { openModelMenu(); } },
    { cmd: "/problems", desc: "Ask about the open Davis problems", run: function () { send(PROBLEMS_Q); } },
    { cmd: "/config", desc: "Open settings", run: function () { openSettings(); } },
    { cmd: "/theme", desc: "system, light or dark", run: function (arg) {
      if (["system", "light", "dark"].indexOf(arg) >= 0) window.DqlTheme.set(arg);
      else openSettings("theme");
    } }
  ];
  var slash = $("#slash"), slashActive = 0, slashItems = [];
  function slashQuery() {
    var m = /^(\/\S*)(?:\s+(\S*))?$/.exec(input.value);
    return m ? { cmd: m[1].toLowerCase(), arg: (m[2] || "").toLowerCase(), hasSpace: /\s/.test(input.value) } : null;
  }
  function updateSlash() {
    var q = slashQuery();
    slashItems = q && !q.hasSpace ? COMMANDS.filter(function (c) { return c.cmd.indexOf(q.cmd) === 0; }) : [];
    if (!slashItems.length) { slash.hidden = true; return; }
    closeModelMenu();
    slashActive = Math.min(slashActive, slashItems.length - 1);
    slash.textContent = "";
    slashItems.forEach(function (c, i) {
      var b = button(null, "menu-item", function () { runCommand(c, ""); });
      b.setAttribute("role", "option");
      b.setAttribute("aria-selected", i === slashActive ? "true" : "false");
      b.appendChild(el("span", "cmd", c.cmd));
      b.appendChild(el("span", "desc", c.desc));
      b.addEventListener("mousemove", function () { if (slashActive !== i) { slashActive = i; updateSlash(); } });
      slash.appendChild(b);
    });
    slash.hidden = false;
  }
  function runCommand(c, arg) {
    input.value = "";
    autosize();
    slash.hidden = true;
    renderSend();
    c.run(arg);
  }
  // Enter on a typed command: run it instead of sending it to the model.
  function trySlash() {
    var q = slashQuery();
    if (!q) return false;
    var c = COMMANDS.filter(function (x) { return x.cmd === q.cmd; })[0];
    if (!c && !slash.hidden && slashItems[slashActive]) c = slashItems[slashActive];
    if (!c) { noteLine("Unknown command " + q.cmd + ". Type / to see the commands."); return true; }
    runCommand(c, q.arg);
    return true;
  }

  input.addEventListener("input", function () { autosize(); renderSend(); updateSlash(); });
  input.addEventListener("keydown", function (ev) {
    if (!slash.hidden && slashItems.length) {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        slashActive = (slashActive + (ev.key === "ArrowDown" ? 1 : slashItems.length - 1)) % slashItems.length;
        updateSlash();
        return;
      }
      if (ev.key === "Tab") {
        ev.preventDefault();
        input.value = slashItems[slashActive].cmd + (slashItems[slashActive].cmd === "/theme" ? " " : "");
        updateSlash();
        return;
      }
      if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); slash.hidden = true; return; }
    }
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      if (/^\//.test(input.value.trim()) && trySlash()) return;
      send(input.value);
    }
  });
  $("#composer").addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (state.busy) { cancel(); return; }
    if (/^\//.test(input.value.trim()) && trySlash()) return;
    send(input.value);
  });
  $("#mode").addEventListener("click", function () { setAuto(!state.auto); });

  // -- model picker: every provider the server offers, grouped -------------
  var modelMenu = $("#model-menu"), modelSearch = $("#model-search"), modelList = $("#model-list");
  var modelActive = 0, modelShown = [];
  function providers() {
    var cfg = state.config || {};
    return cfg.providers && cfg.providers.length ? cfg.providers
      : [{ value: cfg.provider, label: cfg.provider_label, short: cfg.provider_short }];
  }
  function openModelMenu() {
    if (!state.config) return;
    if (!state.config.allow_settings) { noteLine("The model is fixed on this server."); return; }
    slash.hidden = true;
    modelMenu.hidden = false;
    $("#model-pill").setAttribute("aria-expanded", "true");
    modelSearch.value = "";
    modelActive = 0;
    providers().forEach(function (p) { if (!state.providerModels[p.value]) loadModels(p.value); });
    renderModelList();
    modelSearch.focus();
  }
  function closeModelMenu() {
    if (modelMenu.hidden) return;
    modelMenu.hidden = true;
    $("#model-pill").setAttribute("aria-expanded", "false");
  }
  // One request per provider, shared by the picker and the settings dialog.
  function loadModels(provider) {
    var entry = { loading: true, options: [] };
    state.providerModels[provider] = entry;
    entry.promise = api("/api/models?provider=" + encodeURIComponent(provider)).then(function (d) {
      return { options: d.options || [] };
    }).catch(function (e) {
      return { options: [], error: e.message };
    }).then(function (done) {
      state.providerModels[provider] = done;
      if (!modelMenu.hidden) renderModelList();
      return done;
    });
    return entry.promise;
  }
  // Bedrock labels read "id — Name"; Ollama's carry size and context as detail.
  function optionText(o) {
    var friendly = String(o.label || "").split(" — ")[1];
    return { main: friendly || (o.label && o.label !== o.value ? o.label : modelShort(o.value) || o.value),
             sub: o.detail || o.value };
  }
  function renderModelList() {
    var q = modelSearch.value.trim().toLowerCase(), cfg = state.config || {};
    var cur = currentModel(), groups = providers(), multi = groups.length > 1;
    modelShown = [];
    modelList.textContent = "";
    groups.forEach(function (g) {
      var entry = state.providerModels[g.value] || { loading: true, options: [] };
      var mine = function (o) { return g.value === cfg.provider && o.value === cur; };
      var all = entry.options;
      // The chat's own model always shows, even when the list lacks it (a typed id).
      if (g.value === cfg.provider && cur && !entry.loading && !all.some(mine)) {
        all = [{ value: cur, label: cur }].concat(all);
      }
      var opts = all.filter(function (o) {
        return !q || [o.value, o.label, o.detail, g.label].join(" ").toLowerCase().indexOf(q) >= 0;
      });
      if (!q) opts = opts.slice().sort(function (a, b) { return mine(b) - mine(a); });   // current first
      if (multi) modelList.appendChild(el("div", "menu-group", g.label));
      if (entry.loading) modelList.appendChild(el("div", "menu-msg", "Loading…"));
      else if (entry.error) modelList.appendChild(el("div", "menu-msg", "Could not list: " + entry.error));
      else if (!opts.length) modelList.appendChild(el("div", "menu-msg", q ? "No match." : "No models listed. Type an id and press Enter."));
      opts.slice(0, 100).forEach(function (o) {
        var b = button(null, "menu-item model-item", o.disabled ? null : function () { chooseModel(g.value, o.value); });
        b.setAttribute("role", "option");
        b.setAttribute("aria-selected", "false");
        var check = el("span", "check");
        if (mine(o)) check.appendChild(icon("check"));
        b.appendChild(check);
        var t = optionText(o);
        b.appendChild(el("span", "mid", t.main));
        b.appendChild(el("span", "mlabel", o.disabled ? (o.why || "unavailable") : t.sub));
        b.title = (o.label || o.value) + (o.detail ? " · " + o.detail : "") + (o.why ? " (" + o.why + ")" : "");
        if (o.disabled) {
          b.setAttribute("aria-disabled", "true");
          b.classList.add("disabled");
        } else {
          modelShown.push({ provider: g.value, value: o.value, el: b });
        }
        modelList.appendChild(b);
      });
    });
    modelActive = Math.min(modelActive, Math.max(0, modelShown.length - 1));
    var active = modelShown[modelActive];
    if (active) {
      active.el.setAttribute("aria-selected", "true");
      if (active.el.scrollIntoView) active.el.scrollIntoView({ block: "nearest" });
    }
  }
  modelSearch.addEventListener("input", function () { modelActive = 0; renderModelList(); });
  modelSearch.addEventListener("keydown", function (ev) {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      if (!modelShown.length) return;
      modelActive = (modelActive + (ev.key === "ArrowDown" ? 1 : modelShown.length - 1)) % modelShown.length;
      renderModelList();
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      var typed = modelSearch.value.trim(), pick = modelShown[modelActive];
      if (pick) chooseModel(pick.provider, pick.value);
      else if (typed) chooseModel(state.config.provider, typed);
    } else if (ev.key === "Escape") {
      ev.preventDefault(); ev.stopPropagation(); closeModelMenu(); input.focus();
    }
  });
  $("#model-pill").addEventListener("click", function (ev) {
    ev.stopPropagation();
    if (modelMenu.hidden) openModelMenu(); else closeModelMenu();
  });
  function chooseModel(provider, id) {
    closeModelMenu();
    input.focus();
    var cfg = state.config || {};
    if (!id || (provider === cfg.provider && id === currentModel())) return;
    var values = { model: id };
    if (provider !== cfg.provider) values.provider = provider;
    saveSettings(values).catch(function (e) { noteLine("Could not switch the model: " + e.message); });
  }

  // Server-side settings (provider, model, region, limits). A new provider,
  // model or region starts a new chat; the old one stays in Recents.
  function saveSettings(values) {
    if (state.busy) return Promise.reject(new Error("Wait for the current answer, or stop it."));
    return api("/api/settings", { values: values }).then(function (cfg) {
      var hadTurns = !!log.querySelector(".you");
      showConfig(cfg);
      if (values.region) delete state.providerModels.bedrock;      // the list follows the region
      if (cfg.reset) {
        var what = (modelShort(currentModel()) || cfg.model_name) +
          (providers().length > 1 ? " (" + cfg.provider_label + ")" : "");
        if (hadTurns) {
          newChat();
          noteLine("Switched to " + what + ". Started a new chat; the last one is in Recents.");
        } else {
          noteLine("Switched to " + what + ".");
        }
      }
      return cfg;
    });
  }

  // -- settings dialog ---------------------------------------------------
  var dialog = $("#settings"), dialogBody = $("#settings-body"), lastFocus = null;
  function setMsg(text, isError) {
    var m = $("#settings-msg");
    m.textContent = text || "";
    m.className = "settings-msg" + (isError ? " error" : "");
  }
  function row(label, help, control, id) {
    var r = el("div", "set-row");
    var t = el("div", "set-text");
    var l = el(id ? "label" : "span", "set-label", label);
    if (id) l.htmlFor = id;
    t.appendChild(l);
    if (help) t.appendChild(el("div", "set-help", help));
    r.appendChild(t);
    var c = el("div", "set-control");
    c.appendChild(control);
    r.appendChild(c);
    return r;
  }
  function switchCtl(on, label, onchange) {
    var s = button(null, "switch");
    s.setAttribute("role", "switch");
    s.setAttribute("aria-checked", on ? "true" : "false");
    s.setAttribute("aria-label", label);
    s.addEventListener("click", function () {
      var next = s.getAttribute("aria-checked") !== "true";
      s.setAttribute("aria-checked", next ? "true" : "false");
      onchange(next);
    });
    return s;
  }
  // A radio group: one tab stop (the chosen item), arrows move between them.
  // onpick returns false to keep the old choice marked (it marks later itself).
  function segmented(name, id, items, current, onpick) {
    var g = el("div", "segmented");
    g.setAttribute("role", "radiogroup");
    g.setAttribute("aria-label", name);
    g.id = id;
    g.mark = function (value) {
      Array.prototype.forEach.call(g.children, function (x) {
        var on = x.dataset.value === value;
        x.setAttribute("aria-checked", on ? "true" : "false");
        x.tabIndex = on ? 0 : -1;
      });
    };
    items.forEach(function (t) {
      var b = button(t[1], null, function () { if (onpick(t[0]) !== false) g.mark(t[0]); });
      b.setAttribute("role", "radio");
      b.dataset.value = t[0];
      g.appendChild(b);
    });
    g.mark(current);
    g.addEventListener("keydown", function (ev) {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      var kids = Array.prototype.slice.call(g.children), i = kids.indexOf(document.activeElement);
      var next = kids[(i + (ev.key === "ArrowRight" ? 1 : kids.length - 1)) % kids.length];
      next.focus();
      next.click();
    });
    return g;
  }
  function themeCtl() {
    return segmented("Theme", "set-theme", [["system", "System"], ["light", "Light"], ["dark", "Dark"]],
                     window.DqlTheme.get(), function (v) { window.DqlTheme.set(v); });
  }
  // Switching provider starts a new chat and changes the fields below, so the
  // dialog redraws once the server has it.
  function providerCtl(cfg, allow) {
    var wrap = el("div");
    var status = el("div", "set-status");
    status.setAttribute("role", "status");
    var g = segmented("Provider", "set-provider", providers().map(function (p) { return [p.value, p.label]; }),
      cfg.provider, function (v) {
        if (v === state.config.provider || !allow) return false;
        status.className = "set-status";
        status.textContent = "Switching…";
        saveSettings({ provider: v }).then(function () { openSettings("provider"); }).catch(function (e) {
          status.className = "set-status error";
          status.textContent = e.message;
        });
        return false;
      });
    Array.prototype.forEach.call(g.children, function (b) { b.disabled = !allow; });
    wrap.appendChild(g);
    wrap.appendChild(status);
    return wrap;
  }
  function fieldInput(f, allow) {
    var id = "set-" + f.key;
    var inp = el("input");
    inp.id = id;
    inp.name = f.key;
    inp.disabled = !allow;
    if (f.type === "number") {
      inp.type = "number";
      if (f.min !== undefined) inp.min = f.min;
      if (f.max !== undefined) inp.max = f.max;
      inp.step = "1";
    } else {
      inp.type = "text";
      inp.spellcheck = false;
    }
    inp.value = f.value === null || f.value === undefined ? "" : f.value;
    inp.dataset.initial = inp.value;
    var wrap = el("div");
    wrap.appendChild(inp);
    var status = el("div", "set-status");
    status.setAttribute("role", "status");
    // Applies on Enter, on leaving the field, or on picking from the list.
    inp.addEventListener("change", function () { commit(inp, status); });
    inp.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") { ev.preventDefault(); commit(inp, status); }
      if (ev.key === "Escape" && inp.value !== inp.dataset.initial) {
        ev.preventDefault(); ev.stopPropagation(); inp.value = inp.dataset.initial;
      }
    });
    var dl = null;
    function fillList(opts) {
      dl.textContent = "";
      opts.forEach(function (o) {
        if (o.disabled) return;
        var opt = el("option");
        opt.value = typeof o === "string" ? o : o.value;
        if (typeof o !== "string") opt.label = o.detail ? o.label + " · " + o.detail : o.label;
        dl.appendChild(opt);
      });
    }
    if (f.type === "select") {
      dl = el("datalist");
      dl.id = id + "-list";
      inp.setAttribute("list", dl.id);
      wrap.appendChild(dl);
      fillList(f.options || []);
    }
    if (f.key === "model" && allow) {
      // The model list of this chat's provider, shared with the picker.
      var provider = state.config.provider;
      var note = el("div", "options-msg");
      wrap.appendChild(note);
      var show = function (entry) {
        var n = entry.options.filter(function (o) { return !o.disabled; }).length;
        note.textContent = entry.error ? "Could not list models: " + entry.error
          : n ? n + " available. Type to filter, or enter an id." : "Enter a model id.";
        if (dl) fillList(entry.options);
      };
      var entry = state.providerModels[provider];
      if (entry && !entry.loading) show(entry);
      else {
        note.textContent = "Loading the model list…";
        (entry && entry.loading ? entry.promise : loadModels(provider)).then(show);
      }
    }
    wrap.appendChild(status);
    return wrap;
  }

  // Every setting applies as soon as it is changed, like /config in Claude
  // Code: no Save button. A new model or region starts a new chat.
  function commit(inp, status) {
    var value = inp.value.trim();
    if (value === inp.dataset.initial || inp.dataset.saving) return;
    var values = {};
    values[inp.name] = value;
    inp.dataset.saving = "1";
    status.className = "set-status";
    status.textContent = "Saving…";
    saveSettings(values).then(function (cfg) {
      // The server may normalise (a region's default model): show what it kept.
      (cfg.fields || []).forEach(function (f) {
        var other = dialogBody.querySelector("input[name='" + f.key + "']");
        if (!other) return;
        var v = f.value === null || f.value === undefined ? "" : String(f.value);
        other.dataset.initial = v;
        if (other === inp || document.activeElement !== other) other.value = v;
      });
      status.textContent = cfg.reset ? "Saved · new chat started" : "Saved";
      setTimeout(function () { if (/^Saved/.test(status.textContent)) status.textContent = ""; }, 2500);
    }).catch(function (e) {
      inp.value = inp.dataset.initial;
      status.className = "set-status error";
      status.textContent = e.message;
    }).then(function () { delete inp.dataset.saving; });
  }

  function openSettings(focus) {
    if (!state.config) return;
    var cfg = state.config, allow = cfg.allow_settings;
    closeModelMenu();
    slash.hidden = true;
    lastFocus = document.activeElement;
    dialogBody.textContent = "";

    dialogBody.appendChild(el("div", "set-section", "General"));
    dialogBody.appendChild(row("Theme", "System follows your operating system.", themeCtl()));
    var sw = switchCtl(state.auto && cfg.can_run, "Run queries without asking", function (on) { setAuto(on); });
    sw.disabled = !cfg.can_run;
    dialogBody.appendChild(row("Run queries without asking",
      cfg.can_run ? "Each query is still checked for common DQL mistakes before it runs. Same as the mode button under the message box."
                  : "No tenant is configured on the server, so queries are written, not run.", sw));

    dialogBody.appendChild(el("div", "set-section", "Model"));
    if (providers().length > 1) {
      dialogBody.appendChild(row("Provider", "The ones this server offers (DQL_CHAT_PROVIDERS). Switching starts a new chat. Keys and URLs stay on the server.",
                                 providerCtl(cfg, allow)));
    } else {
      dialogBody.appendChild(row("Provider", "Set on the server with LLM_PROVIDER. Keys and URLs stay on the server.",
                                 el("span", "set-value", cfg.provider_label)));
    }
    var common = [];
    cfg.fields.forEach(function (f) {
      if (f.key === "max_turns" || f.key === "max_tokens") { common.push(f); return; }
      dialogBody.appendChild(row(f.label, f.help, fieldInput(f, allow), "set-" + f.key));
    });
    dialogBody.appendChild(el("div", "set-section", "Limits"));
    common.forEach(function (f) { dialogBody.appendChild(row(f.label, f.help, fieldInput(f, allow), "set-" + f.key)); });

    dialogBody.appendChild(el("div", "set-section", "History"));
    var h = cfg.history || {};
    dialogBody.appendChild(row("Chat history",
      h.on ? "Your chats, their queries and results are kept on this server so you can reopen them from Recents."
           : "The server runs without history (DQL_CHAT_HISTORY=0). Chats last until it restarts.",
      el("span", "set-value", h.on ? (h.days ? "Kept " + h.days + " days" : "Kept") : "Off")));

    setMsg(allow ? "Changes apply as you make them. A new model or region starts a new chat; the current one stays in Recents."
                 : "Model and limits are fixed on this server.");
    dialog.hidden = false;
    var first = focus === "theme" || focus === "provider" ? dialogBody.querySelector("#set-" + focus + " [aria-checked='true']")
      : dialogBody.querySelector("button[tabindex='0'], input:not([disabled])");
    if (first) first.focus();
  }
  function closeSettings() {
    dialog.hidden = true;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  $("#btn-settings").addEventListener("click", function () { openSettings(); });
  $("#settings-close").addEventListener("click", closeSettings);
  dialog.addEventListener("click", function (ev) { if (ev.target === dialog) closeSettings(); });
  dialog.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); closeSettings(); return; }
    if (ev.key !== "Tab") return;          // keep focus inside the dialog
    var f = Array.prototype.filter.call(dialog.querySelectorAll("button, input, [tabindex]"), function (n) {
      return !n.disabled && n.offsetParent !== null;
    });
    if (!f.length) return;
    if (ev.shiftKey && document.activeElement === f[0]) { ev.preventDefault(); f[f.length - 1].focus(); }
    else if (!ev.shiftKey && document.activeElement === f[f.length - 1]) { ev.preventDefault(); f[0].focus(); }
  });
  // -- global keys and clicks --------------------------------------------
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape" || !dialog.hidden) return;
    if (expandedViz) { ev.preventDefault(); expandedViz.collapse(); return; }
    if (!modelMenu.hidden) { closeModelMenu(); input.focus(); return; }
    if (!slash.hidden) { slash.hidden = true; return; }
    if (rowMenuEl) { closeRowMenu(); return; }
    if (app.classList.contains("side-open")) { app.classList.remove("side-open"); return; }
    if (state.busy && !(ev.target.closest && ev.target.closest(".qprompt"))) cancel();
  });
  document.addEventListener("click", function (ev) {
    if (!modelMenu.hidden && !modelMenu.contains(ev.target) && ev.target !== $("#model-pill")) closeModelMenu();
    if (!slash.hidden && !slash.contains(ev.target) && ev.target !== input) slash.hidden = true;
    if (rowMenuEl && !rowMenuEl.contains(ev.target)) closeRowMenu();
  });

  // -- start -------------------------------------------------------------
  renderSend();
  api("/api/config").then(function (cfg) {
    showConfig(cfg);
    state.ready = true;
    renderSend();
    loadProblems();                  // the badge, also when reopening a chat
    return loadRecents().then(function () {
      // Reopen this tab's chat after a reload.
      var known = state.conversations.some(function (c) { return c.id === state.session; });
      if (known) return openConversation(state.session);
      clearLog();
      setTitle("");
      input.focus();
    });
  }).catch(function (e) {
    $("#meta").textContent = "Not connected";
    var b = el("div", "banner");
    b.appendChild(el("strong", null, "Cannot reach the chat server. "));
    b.appendChild(document.createTextNode(e.message + (/token|signed/i.test(e.message)
      ? " Open the link printed by ./util/dql_chat.sh (it carries the access token)." : "")));
    log.appendChild(b);
  });
})();
