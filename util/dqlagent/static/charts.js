// Line and bar charts in plain SVG, drawn from specs built on the server from
// query results. Follows the repo's dataviz rules: a fixed 8-slot palette,
// 2px lines with ringed end dots, bars at most 24px thick with a rounded data
// end, hairline grid, one y axis, a legend for 2+ series, a crosshair tooltip
// listing every series, and a table view for every chart.
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";

  function svg(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function slotClass(i) { return i >= 0 && i < 8 ? "s" + i : "s-other"; }

  // -- numbers and time -------------------------------------------------
  function niceTicks(min, max, count) {
    if (!isFinite(min) || !isFinite(max)) { min = 0; max = 1; }
    if (min === max) { max = min === 0 ? 1 : min + Math.abs(min) * 0.1; }
    var raw = (max - min) / Math.max(1, count);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var f = raw / mag;
    var step = (f >= 7.5 ? 10 : f >= 3.5 ? 5 : f >= 1.5 ? 2 : 1) * mag;
    var lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    var ticks = [];
    for (var v = lo; v <= hi + step / 2; v += step) ticks.push(Number(v.toFixed(10)));
    return { lo: lo, hi: hi, ticks: ticks };
  }
  function fmtAxis(v) {
    var a = Math.abs(v);
    if (a >= 1e9) return trim(v / 1e9) + "B";
    if (a >= 1e6) return trim(v / 1e6) + "M";
    if (a >= 1e4) return trim(v / 1e3) + "K";
    return v.toLocaleString(undefined, { maximumFractionDigits: a < 1 ? 3 : 1 });
  }
  function trim(v) { return Number(v.toFixed(1)).toLocaleString(); }
  function fmtValue(v, unit) {
    if (v === null || v === undefined) return "no data";
    var s = v.toLocaleString(undefined, { maximumFractionDigits: Math.abs(v) < 10 ? 2 : 1 });
    return unit ? s + (unit === "%" ? "%" : " " + unit) : s;
  }
  var TIME_STEPS = [60e3, 5 * 60e3, 10 * 60e3, 15 * 60e3, 30 * 60e3, 3600e3, 2 * 3600e3, 3 * 3600e3,
                    6 * 3600e3, 12 * 3600e3, 864e5, 2 * 864e5, 7 * 864e5, 30 * 864e5];
  function timeTicks(lo, hi, target) {
    var span = hi - lo, step = TIME_STEPS[TIME_STEPS.length - 1];
    for (var i = 0; i < TIME_STEPS.length; i++) {
      if (span / TIME_STEPS[i] <= target) { step = TIME_STEPS[i]; break; }
    }
    var offset = new Date(lo).getTimezoneOffset() * 60e3;  // align to local midnight
    var first = Math.ceil((lo - offset) / step) * step + offset;
    var out = [];
    for (var t = first; t <= hi; t += step) out.push(t);
    return { ticks: out, step: step };
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtTime(t, step) {
    var d = new Date(t);
    var hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
    if (step >= 864e5) return MONTHS[d.getMonth()] + " " + d.getDate();
    if (d.getHours() === 0 && d.getMinutes() === 0 && step >= 3600e3) return MONTHS[d.getMonth()] + " " + d.getDate();
    return hm;
  }
  function fmtTimeFull(t) {
    var d = new Date(t);
    return MONTHS[d.getMonth()] + " " + d.getDate() + ", " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function textWidth(s) { return String(s).length * 6.6; }   // 11px system sans, close enough
  function clip(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }

  // -- legend ------------------------------------------------------------
  function legend(names, shape) {
    var box = el("div", "legend");
    names.forEach(function (name, i) {
      var item = el("span", "item");
      item.appendChild(el("span", (shape === "rect" ? "key-rect " : "key-line ") + slotClass(i)));
      item.appendChild(el("span", null, name));
      box.appendChild(item);
    });
    return box;
  }

  // -- responsive rendering ---------------------------------------------
  function responsive(host, draw) {
    var lastW = 0, timer = null;
    function run() {
      var w = Math.max(320, Math.floor(host.clientWidth || 600));
      if (w === lastW) return;
      lastW = w;
      draw(w);
    }
    run();
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { clearTimeout(timer); timer = setTimeout(run, 80); });
      ro.observe(host);
      return function () { ro.disconnect(); };
    }
    return function () {};
  }

  // -- line chart --------------------------------------------------------
  function timeseries(spec, host) {
    var series = spec.series || [];
    var timed = spec.x === "time";
    host.textContent = "";
    if (series.length >= 2) host.appendChild(legend(series.map(function (s) { return s.name; }), "line"));
    var plot = el("div", "plot");
    plot.tabIndex = 0;
    plot.setAttribute("role", "img");
    plot.setAttribute("aria-label", (spec.title || "Chart") + ": " + series.length +
      " series. Use the table view for exact values; arrow keys move the readout.");
    host.appendChild(plot);

    return responsive(host, function (W) {
      plot.textContent = "";
      var H = 260;
      var xs = [], ys = [];
      series.forEach(function (s) {
        s.points.forEach(function (p) { xs.push(p[0]); if (p[1] !== null) ys.push(p[1]); });
      });
      var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
      if (xmin === xmax) xmax = xmin + 1;
      var ymin = ys.length ? Math.min.apply(null, ys) : 0, ymax = ys.length ? Math.max.apply(null, ys) : 1;
      var yt = niceTicks(Math.min(0, ymin), ymax, 4);
      var left = 10 + Math.max.apply(null, yt.ticks.map(function (t) { return textWidth(fmtAxis(t)); }));

      // Direct end labels only for <= 4 series whose ends sit apart.
      var ends = series.map(function (s, i) {
        for (var j = s.points.length - 1; j >= 0; j--) if (s.points[j][1] !== null) return { i: i, p: s.points[j] };
        return null;
      });
      var top = 10, bottom = 24;
      var plotH = H - top - bottom;
      var yOf = function (v) { return top + plotH - (v - yt.lo) / (yt.hi - yt.lo) * plotH; };
      var labelled = series.length <= 4 && series.length >= 1;
      if (labelled) {
        var ysEnd = ends.filter(Boolean).map(function (e) { return yOf(e.p[1]); }).sort(function (a, b) { return a - b; });
        for (var k = 1; k < ysEnd.length; k++) if (ysEnd[k] - ysEnd[k - 1] < 14) labelled = false;
        if (series.length === 1) labelled = false;   // the title names a single series
      }
      var right = labelled ? 12 + Math.min(130, Math.max.apply(null, series.map(function (s) { return textWidth(clip(s.name, 20)); }))) : 14;
      var plotW = W - left - right;
      var xOf = function (v) { return left + (v - xmin) / (xmax - xmin) * plotW; };

      var root = svg("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H }, plot);
      yt.ticks.forEach(function (t) {
        var y = Math.round(yOf(t)) + 0.5;
        svg("line", { x1: left, x2: left + plotW, y1: y, y2: y, "class": t === 0 ? "axis" : "grid" }, root);
        var lab = svg("text", { x: left - 6, y: y + 3.5, "text-anchor": "end", "class": "tick" }, root);
        lab.textContent = fmtAxis(t);
      });
      if (timed) {
        var tt = timeTicks(xmin, xmax, Math.max(2, Math.floor(plotW / 90)));
        tt.ticks.forEach(function (t) {
          var lab = svg("text", { x: xOf(t), y: H - 6, "text-anchor": "middle", "class": "tick" }, root);
          lab.textContent = fmtTime(t, tt.step);
        });
      } else {
        niceTicks(xmin, xmax, Math.max(2, Math.floor(plotW / 90))).ticks.forEach(function (t) {
          if (t < xmin || t > xmax) return;
          var lab = svg("text", { x: xOf(t), y: H - 6, "text-anchor": "middle", "class": "tick" }, root);
          lab.textContent = fmtAxis(t);
        });
      }
      var axisY = Math.round(yOf(yt.lo)) + 0.5;
      svg("line", { x1: left, x2: left + plotW, y1: axisY, y2: axisY, "class": "axis" }, root);

      series.forEach(function (s, i) {
        var d = "", pen = false;
        s.points.forEach(function (p) {
          if (p[1] === null) { pen = false; return; }
          d += (pen ? "L" : "M") + xOf(p[0]).toFixed(1) + " " + yOf(p[1]).toFixed(1);
          pen = true;
        });
        if (d) svg("path", { d: d, "class": "line " + slotClass(i) }, root);
      });
      ends.forEach(function (e) {
        if (!e) return;
        svg("circle", { cx: xOf(e.p[0]), cy: yOf(e.p[1]), r: 4, "class": "dot " + slotClass(e.i) }, root);
        if (labelled) {
          var t = svg("text", { x: xOf(e.p[0]) + 8, y: yOf(e.p[1]) + 4, "class": "end-label" }, root);
          t.textContent = clip(series[e.i].name, 20);
        }
      });

      // Crosshair + tooltip: snaps to the nearest x; lists every series there.
      var grid = series.length ? series[0].points.map(function (p) { return p[0]; }) : [];
      var cross = svg("line", { y1: top, y2: top + plotH, "class": "cross", visibility: "hidden" }, root);
      var marks = series.map(function (s, i) {
        return svg("circle", { r: 4, "class": "dot " + slotClass(i), visibility: "hidden" }, root);
      });
      var tip = el("div", "tooltip");
      tip.hidden = true;
      plot.appendChild(tip);
      var current = -1;

      function nearest(pts, x) {
        var lo = 0, hi = pts.length - 1;
        if (hi < 0) return -1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (pts[mid][0] < x) lo = mid; else hi = mid; }
        return Math.abs(pts[lo][0] - x) <= Math.abs(pts[hi][0] - x) ? lo : hi;
      }
      function show(idx) {
        if (idx < 0 || idx >= grid.length) return hide();
        current = idx;
        var x = grid[idx], px = xOf(x);
        cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
        tip.textContent = "";
        tip.appendChild(el("div", "t-head", timed ? fmtTimeFull(x) : "Point " + (x + 1)));
        var rows = series.map(function (s, i) {
          var j = nearest(s.points, x);
          var v = j >= 0 ? s.points[j][1] : null;
          if (v !== null) {
            marks[i].setAttribute("cx", xOf(s.points[j][0])); marks[i].setAttribute("cy", yOf(v));
            marks[i].setAttribute("visibility", "visible");
          } else {
            marks[i].setAttribute("visibility", "hidden");
          }
          return { i: i, v: v, name: s.name };
        });
        rows.sort(function (a, b) { return (b.v === null ? -Infinity : b.v) - (a.v === null ? -Infinity : a.v); });
        rows.forEach(function (r) {
          var row = el("div", "t-row");
          row.appendChild(el("span", "key-line " + slotClass(r.i)));
          row.appendChild(el("span", "t-val", fmtValue(r.v, spec.unit)));
          row.appendChild(el("span", "t-name", r.name));
          tip.appendChild(row);
        });
        tip.hidden = false;
        var tw = tip.offsetWidth;
        tip.style.left = (px + 12 + tw > W ? px - 12 - tw : px + 12) + "px";
        tip.style.top = top + "px";
      }
      function hide() {
        current = -1;
        tip.hidden = true;
        cross.setAttribute("visibility", "hidden");
        marks.forEach(function (m) { m.setAttribute("visibility", "hidden"); });
      }
      var hit = svg("rect", { x: left, y: top, width: plotW, height: plotH, fill: "transparent" }, root);
      hit.addEventListener("pointermove", function (ev) {
        var r = root.getBoundingClientRect();
        var x = xmin + (ev.clientX - r.left - left) / plotW * (xmax - xmin);
        show(series.length ? nearest(series[0].points, x) : -1);
      });
      hit.addEventListener("pointerleave", hide);
      plot.onkeydown = function (ev) {
        if (ev.key === "ArrowRight") { show(Math.min(grid.length - 1, current + 1)); ev.preventDefault(); }
        else if (ev.key === "ArrowLeft") { show(current < 0 ? grid.length - 1 : Math.max(0, current - 1)); ev.preventDefault(); }
        else if (ev.key === "Escape") hide();
      };
      plot.onblur = hide;
    });
  }

  // -- bar chart ---------------------------------------------------------
  function barPath(x0, x1, y, h, r) {
    // Square at the baseline (x0), 4px rounded data end (x1).
    if (x1 < x0) { var t = x0; x0 = x1; x1 = t; r = -r; }
    var w = x1 - x0;
    var rr = Math.min(Math.abs(r), w / 2, h / 2);
    if (r >= 0) {
      return "M" + x0 + " " + y + "H" + (x1 - rr) + "Q" + x1 + " " + y + " " + x1 + " " + (y + rr) +
             "V" + (y + h - rr) + "Q" + x1 + " " + (y + h) + " " + (x1 - rr) + " " + (y + h) + "H" + x0 + "Z";
    }
    return "M" + x1 + " " + y + "H" + (x0 + rr) + "Q" + x0 + " " + y + " " + x0 + " " + (y + rr) +
           "V" + (y + h - rr) + "Q" + x0 + " " + (y + h) + " " + (x0 + rr) + " " + (y + h) + "H" + x1 + "Z";
  }

  function bar(spec, host) {
    var bars = spec.bars || [];
    host.textContent = "";
    var plot = el("div", "plot");
    plot.setAttribute("role", "img");
    plot.setAttribute("aria-label", (spec.title || "Bar chart") + ": " + bars.length + " bars; values are printed at each bar.");
    host.appendChild(plot);
    return responsive(host, function (W) {
      plot.textContent = "";
      var band = 28, thick = 16, top = 6, bottom = 22;
      var H = top + bars.length * band + bottom;
      var labelW = Math.min(Math.floor(W * 0.38), 16 + Math.max.apply(null, bars.map(function (b) { return textWidth(clip(b.label, 40)); })));
      var valueW = 16 + Math.max.apply(null, bars.map(function (b) { return textWidth(fmtValue(b.value, spec.unit)); }));
      var x0 = labelW, plotW = Math.max(60, W - labelW - valueW);
      var vals = bars.map(function (b) { return b.value; });
      var xt = niceTicks(Math.min(0, Math.min.apply(null, vals)), Math.max(0, Math.max.apply(null, vals)), Math.max(2, Math.floor(plotW / 110)));
      var xOf = function (v) { return x0 + (v - xt.lo) / (xt.hi - xt.lo) * plotW; };
      var root = svg("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H }, plot);
      xt.ticks.forEach(function (t) {
        var x = Math.round(xOf(t)) + 0.5;
        svg("line", { x1: x, x2: x, y1: top, y2: H - bottom, "class": t === 0 ? "axis" : "grid" }, root);
        var lab = svg("text", { x: x, y: H - 6, "text-anchor": "middle", "class": "tick" }, root);
        lab.textContent = fmtAxis(t);
      });
      var tip = el("div", "tooltip");
      tip.hidden = true;
      plot.appendChild(tip);
      var maxChars = Math.max(6, Math.floor((labelW - 12) / 6.6));
      bars.forEach(function (b, i) {
        var y = top + i * band + (band - thick) / 2;
        var g = svg("g", { tabindex: 0 }, root);
        var lab = svg("text", { x: x0 - 8, y: y + thick / 2 + 4, "text-anchor": "end", "class": "bar-label" }, g);
        lab.textContent = clip(b.label, maxChars);
        var title = svg("title", {}, g);
        title.textContent = b.label + ": " + fmtValue(b.value, spec.unit);
        var zero = xOf(0), end = xOf(b.value);
        var mark = svg("path", { d: barPath(zero, end, y, thick, 4), "class": "bar s0" }, g);
        var val = svg("text", { x: (b.value >= 0 ? end + 6 : end - 6), y: y + thick / 2 + 4,
                                "text-anchor": b.value >= 0 ? "start" : "end", "class": "bar-value" }, g);
        val.textContent = fmtValue(b.value, spec.unit);
        // The hit target is the whole row, bigger than the mark.
        var hit = svg("rect", { x: 0, y: top + i * band, width: W, height: band, fill: "transparent" }, g);
        function on() {
          mark.classList.add("dim");
          tip.textContent = "";
          var row = el("div", "t-row");
          row.appendChild(el("span", "t-val", fmtValue(b.value, spec.unit)));
          row.appendChild(el("span", "t-name", b.label));
          tip.appendChild(row);
          tip.hidden = false;
          tip.style.left = Math.min(W - tip.offsetWidth, Math.max(0, end + 12)) + "px";
          tip.style.top = (y - 30) + "px";
        }
        function off() { mark.classList.remove("dim"); tip.hidden = true; }
        hit.addEventListener("pointerenter", on);
        hit.addEventListener("pointerleave", off);
        g.addEventListener("focus", on);
        g.addEventListener("blur", off);
      });
    });
  }

  // -- table view (every chart has one) -----------------------------------
  function table(spec) {
    var wrap = el("div", "tablewrap");
    var t = el("table", "data"), thead = el("thead"), tbody = el("tbody"), hr = el("tr");
    t.appendChild(thead); t.appendChild(tbody); thead.appendChild(hr); wrap.appendChild(t);
    function th(s) { hr.appendChild(el("th", null, s)); }
    if (spec.kind === "bar") {
      th("Name"); th("Value" + (spec.unit ? " (" + spec.unit + ")" : ""));
      spec.bars.forEach(function (b) {
        var tr = el("tr");
        tr.appendChild(el("td", null, b.label));
        tr.appendChild(el("td", "num", fmtValue(b.value)));
        tbody.appendChild(tr);
      });
      return wrap;
    }
    var series = spec.series || [];
    th(spec.x === "time" ? "Time" : "Point");
    series.forEach(function (s) { th(s.name); });
    var n = series.length ? series[0].points.length : 0;
    for (var j = 0; j < Math.min(n, 1000); j++) {
      var tr = el("tr"), x = series[0].points[j][0];
      tr.appendChild(el("td", null, spec.x === "time" ? fmtTimeFull(x) : String(x + 1)));
      series.forEach(function (s) {
        var p = s.points[j];
        tr.appendChild(el("td", "num", p ? fmtValue(p[1]) : ""));
      });
      tbody.appendChild(tr);
    }
    return wrap;
  }

  window.DqlCharts = { timeseries: timeseries, bar: bar, table: table, fmtValue: fmtValue };
})();
