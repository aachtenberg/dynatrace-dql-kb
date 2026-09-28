// The chat page: sends questions, streams the agent's steps, asks before a
// query runs, and draws the charts and graphs the agent returns. Everything
// from the server or the model is inserted as text, never as HTML.
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
  function store(key, value) {
    try {
      if (value === undefined) return sessionStorage.getItem(key);
      sessionStorage.setItem(key, value);
    } catch (e) { /* storage blocked: keep going without it */ }
    return value;
  }
  function newId() {
    var raw = window.crypto && crypto.randomUUID ? crypto.randomUUID()
      : String(Date.now()) + Math.random().toString(16).slice(2);
    return raw.replace(/[^A-Za-z0-9_-]/g, "");
  }

  // The token arrives once in the URL (?t=...), then lives in this tab only.
  var params = new URLSearchParams(location.search);
  if (params.get("t")) {
    store("dqlToken", params.get("t"));
    history.replaceState(null, "", location.pathname);
  }
  var state = {
    token: store("dqlToken") || "",
    session: store("dqlSession") || store("dqlSession", newId()),
    config: null,
    busy: false
  };
  var log = $("#log"), input = $("#input"), sendBtn = $("#send"), auto = $("#auto");

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

  // -- header, welcome ---------------------------------------------------
  function showConfig(cfg) {
    state.config = cfg;
    var parts = [cfg.error ? cfg.provider_label + " · not ready" : cfg.model_name];
    parts.push(cfg.can_run ? "tenant " + cfg.tenant : "no tenant: queries are written, not run");
    if (cfg.user) parts.push(cfg.user);
    $("#meta").textContent = parts.join(" · ");
    $("#meta").title = $("#meta").textContent;
    $("#btn-settings").hidden = false;
    auto.disabled = !cfg.can_run;
    var chosen = store("dqlAuto");
    auto.checked = cfg.can_run && (chosen === null || chosen === undefined ? !!cfg.auto_run : chosen === "1");
  }

  var EXAMPLES = [
    "Any open problems right now?",
    "Which hosts had CPU above 90% in the last hour?",
    "Chart CPU for the five busiest hosts over the last 6 hours",
    "Draw who calls whom between processes",
    "Errors in logs over the last hour, by host"
  ];
  function welcome() {
    var w = el("div", "welcome");
    w.appendChild(el("h1", null, "Ask your Dynatrace tenant"));
    w.appendChild(el("p", null, "The model searches this repo's DQL reference, checks every metric and " +
      "field name against your tenant, runs the query and answers from the records. It can draw " +
      "charts and graphs from what it ran. You approve each query unless you switch that off."));
    var chips = el("div", "chips");
    EXAMPLES.forEach(function (q) { chips.appendChild(button(q, "chip", function () { send(q); })); });
    w.appendChild(chips);
    if (state.config && state.config.error) {
      var b = el("div", "banner");
      b.appendChild(el("strong", null, "The model is not ready. "));
      b.appendChild(document.createTextNode(state.config.error + " "));
      b.appendChild(button("Open settings", "ghost", openSettings));
      w.insertBefore(b, w.firstChild);
    }
    log.appendChild(w);
  }
  function clearLog() { log.textContent = ""; welcome(); }

  // -- a turn: the agent's steps for one question -------------------------
  function newTurn() {
    var box = el("section", "turn");
    log.appendChild(box);
    var spinner = null, card = null;

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
      var actions = null;
      return {
        status: function (text, kind) { status.textContent = text; status.className = "qstatus" + (kind ? " " + kind : ""); },
        ask: function (id) {
          this.status("Waiting for you", "warn");
          actions = el("div", "qactions");
          var said = el("input");
          said.placeholder = "or say what to change, e.g. last 24h, only prod hosts";
          said.setAttribute("aria-label", "What to change instead of running");
          var self = this;
          function answer(run, text) {
            Array.prototype.forEach.call(actions.querySelectorAll("button,input"), function (n) { n.disabled = true; });
            self.status(run ? "Running…" : (text ? "Sent your change" : "Not run"), run ? "" : "muted");
            api("/api/approve", { id: id, run: run, said: text || "" }).catch(function (e) {
              self.status("Could not answer the prompt: " + e.message, "error");
            });
            setTimeout(function () { if (actions) { actions.remove(); actions = null; } }, 300);
          }
          var run = button("Run", "primary", function () { answer(true); });
          actions.appendChild(run);
          actions.appendChild(button("Don't run", "ghost", function () { answer(false); }));
          actions.appendChild(said);
          actions.appendChild(button("Send", "ghost", function () { if (said.value.trim()) answer(false, said.value.trim()); }));
          said.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter" && said.value.trim()) { ev.preventDefault(); answer(false, said.value.trim()); }
          });
          c.appendChild(actions);
          run.focus();
        },
        result: function (d) {
          this.status(d.record_count + (d.record_count === 1 ? " record" : " records") + " · " + d.scanned + " scanned" +
                      (d.notes && d.notes.length ? " · " + d.notes[0] : ""), "ok");
          if (!d.rows || !d.rows.length) return;
          var det = el("details", "records");
          var shown = d.rows.length < d.record_count ? d.rows.length + " of " + d.record_count : String(d.rows.length);
          det.appendChild(el("summary", null, "Show " + shown + " records"));
          det.addEventListener("toggle", function once() {
            if (!det.open || det.childNodes.length > 1) return;
            det.appendChild(recordsTable(d.fields, d.rows));
          });
          c.appendChild(det);
        }
      };
    }

    function figure(spec) {
      var fig = el("figure", "viz-card");
      var cap = el("figcaption");
      cap.appendChild(el("span", "viz-title", spec.title || (spec.kind === "graph" ? "Graph" : "Chart")));
      if (spec.unit) cap.appendChild(el("span", "viz-unit", "(" + spec.unit + ")"));
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
        } else if (spec.kind === "bar") {
          stop = window.DqlCharts.bar(spec, body);
        } else {
          stop = window.DqlCharts.timeseries(spec, body);
        }
      }
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
          case "lint": if (card) card.status("Stopped before running: " + d.issues.join(" "), "warn"); break;
          case "approval": if (card) card.ask(d.id); break;
          case "skipped": if (card) card.status(d.said ? "Not run. You said: " + d.said : "Not run", "muted"); break;
          case "result": if (card) card.result(d); break;
          case "query_error": if (card) card.status(d.summary, "error"); break;
          case "visual": figure(d.spec); break;
          case "visual_error": step("Could not draw:", d.message, "muted"); break;
          case "answer":
            var a = el("div", "answer");
            a.appendChild(window.DqlMarkdown.render(d.text || ""));
            box.appendChild(a);
            break;
          case "error": box.appendChild(el("div", "error-box", d.text)); break;
          case "cancelled": step("Stopped.", null); break;
        }
        scroll();
      },
      error: function (text) { clearSpinner(); box.appendChild(el("div", "error-box", text)); scroll(); },
      end: clearSpinner
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
    sendBtn.textContent = b ? "Stop" : "Send";
    sendBtn.className = b ? "danger" : "primary";
    if (!b) input.focus();
  }

  function send(text) {
    text = (text || "").trim();
    if (!text || state.busy) return;
    var w = log.querySelector(".welcome");
    if (w) w.remove();
    var you = el("div", "you");
    you.appendChild(el("div", null, text));
    log.appendChild(you);
    input.value = "";
    autosize();
    var turn = newTurn();
    setBusy(true);
    scroll(true);
    fetch("/api/chat", {
      method: "POST", headers: headers(true),
      body: JSON.stringify({ session: state.session, message: text, auto: auto.checked })
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
            if (data) {
              try { turn.on(kind, JSON.parse(data)); } catch (e) { /* skip a malformed event */ }
            }
          }
          return pump();
        });
      }
      return pump();
    }).catch(function (e) {
      turn.error("Connection lost: " + e.message);
    }).then(function () {
      turn.end();
      setBusy(false);
    });
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(200, input.scrollHeight + 2) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); send(input.value); }
  });
  $("#composer").addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (state.busy) api("/api/cancel", {}).catch(function () {});
    else send(input.value);
  });
  $("#btn-new").addEventListener("click", function () {
    if (state.busy) return;
    api("/api/reset", {}).then(clearLog).catch(function (e) { alert(e.message); });
  });
  auto.addEventListener("change", function () { store("dqlAuto", auto.checked ? "1" : "0"); });

  // -- settings ----------------------------------------------------------
  var drawer = $("#settings"), form = $("#settings-form"), msg = $("#settings-msg");

  function setMsg(text, isError) { msg.textContent = text || ""; msg.className = "settings-msg" + (isError ? " error" : ""); }

  function renderSettings() {
    var cfg = state.config;
    form.textContent = "";
    $("#settings-provider").textContent = "Provider: " + cfg.provider_label +
      " (set on the server with LLM_PROVIDER)." + (cfg.allow_settings ? "" : " Settings are fixed on this server.");
    cfg.fields.forEach(function (f) {
      var wrap = el("div", "field");
      var id = "set-" + f.key;
      var lab = el("label", null, f.label);
      lab.htmlFor = id;
      wrap.appendChild(lab);
      var inp = el("input");
      inp.id = id;
      inp.name = f.key;
      inp.disabled = !cfg.allow_settings;
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
      if (f.type === "select") {
        var dl = el("datalist");
        dl.id = id + "-list";
        (f.options || []).forEach(function (o) {
          var opt = el("option");
          opt.value = typeof o === "string" ? o : o.value;
          if (typeof o !== "string") opt.label = o.label;
          dl.appendChild(opt);
        });
        inp.setAttribute("list", dl.id);
        wrap.appendChild(dl);
      }
      if (f.dynamic) {
        var row = el("div", "row");
        row.appendChild(inp);
        var load = button("Load list", "ghost", function () { loadOptions(f, inp); });
        load.disabled = !cfg.allow_settings;
        row.appendChild(load);
        wrap.appendChild(row);
        wrap.appendChild(el("div", "options-msg"));
      } else {
        wrap.appendChild(inp);
      }
      if (f.help) wrap.appendChild(el("div", "help", f.help));
      form.appendChild(wrap);
      if (f.key === "region") {
        inp.addEventListener("change", function () {
          var model = form.querySelector("#set-model");
          var mf = cfg.fields.filter(function (x) { return x.key === "model"; })[0];
          if (model && mf) loadOptions(mf, model);
        });
      }
    });
  }

  function loadOptions(f, inp) {
    var note = inp.closest(".field").querySelector(".options-msg");
    var region = form.querySelector("#set-region");
    note.textContent = "Loading…";
    api("/api/models" + (region ? "?region=" + encodeURIComponent(region.value.trim()) : ""))
      .then(function (d) {
        var dl = document.getElementById(inp.id + "-list");
        dl.textContent = "";
        d.options.forEach(function (o) {
          var opt = el("option");
          opt.value = o.value;
          opt.label = o.label;
          dl.appendChild(opt);
        });
        note.textContent = d.options.length + " available. Type to filter, or enter an id.";
      })
      .catch(function (e) { note.textContent = "Could not list: " + e.message + " You can still type an id."; });
  }

  function openSettings() {
    if (!state.config) return;
    renderSettings();
    setMsg("");
    drawer.hidden = false;
    var first = form.querySelector("input:not([disabled])");
    if (first) first.focus();
    var mf = state.config.fields.filter(function (x) { return x.dynamic; })[0];
    if (mf && state.config.allow_settings) loadOptions(mf, form.querySelector("#set-" + mf.key));
  }
  function closeSettings() { drawer.hidden = true; }

  $("#btn-settings").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#settings-cancel").addEventListener("click", closeSettings);
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && !drawer.hidden) closeSettings(); });
  $("#settings-save").addEventListener("click", function () {
    if (state.busy) { setMsg("Wait for the current answer, or stop it.", true); return; }
    var values = {};
    Array.prototype.forEach.call(form.querySelectorAll("input[name]"), function (inp) {
      if (inp.value !== inp.dataset.initial) values[inp.name] = inp.value.trim();
    });
    if (!Object.keys(values).length) { closeSettings(); return; }
    setMsg("Saving…");
    api("/api/settings", { values: values }).then(function (cfg) {
      showConfig(cfg);
      closeSettings();
      if (cfg.reset) {
        clearLog();
        var note = el("div", "step", "Started a new chat with " + cfg.model_name + ".");
        log.appendChild(note);
      }
    }).catch(function (e) { setMsg(e.message, true); });
  });

  // -- start -------------------------------------------------------------
  api("/api/config").then(function (cfg) {
    showConfig(cfg);
    clearLog();
    input.focus();
  }).catch(function (e) {
    $("#meta").textContent = "Not connected";
    var b = el("div", "banner");
    b.appendChild(el("strong", null, "Cannot reach the chat server. "));
    b.appendChild(document.createTextNode(e.message + (/token|signed/i.test(e.message)
      ? " Open the link printed by ./util/dql_chat.sh (it carries the access token)." : "")));
    log.appendChild(b);
  });
})();
