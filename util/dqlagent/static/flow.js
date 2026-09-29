// Graphs with React Flow (vendored UMD build, no bundler). The server sends
// nodes and edges in React Flow's own shape with positions already laid out,
// so this file only mounts the component and styles the nodes.
(function () {
  "use strict";

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function lib() {
    var RF = window.ReactFlow;
    if (!RF || !window.React || !window.ReactDOM) return null;
    return { RF: RF, Flow: RF.ReactFlow || RF.default, h: window.React.createElement };
  }

  var nodeTypes = null;   // created once: React Flow warns when it changes
  var live = [];          // mounted graphs, redrawn when the theme changes

  function colorMode() {
    return window.DqlTheme ? window.DqlTheme.resolved() : "system";
  }
  if (window.DqlTheme) {
    window.DqlTheme.onChange(function () { live.forEach(function (g) { g.render(); }); });
  }

  function DqlNode(props) {
    var L = lib(), d = props.data || {};
    var cls = "dql-node " + (d.slot === null || d.slot === undefined ? "s-other" : "s" + d.slot) + (d.highlight ? " hl" : "");
    return L.h("div", { className: cls, title: d.id + (d.type ? " (" + d.type + ")" : "") },
      L.h(L.RF.Handle, { type: "target", position: L.RF.Position.Left, isConnectable: false }),
      L.h("div", { className: "n-label" }, d.label),
      L.h("div", { className: "n-type" }, d.type),
      L.h(L.RF.Handle, { type: "source", position: L.RF.Position.Right, isConnectable: false }));
  }

  function graph(spec, host) {
    var L = lib();
    host.textContent = "";
    if (!L || !L.Flow) {
      host.appendChild(el("p", "muted", "The graph library did not load; use the table view."));
      return function () {};
    }
    if (!nodeTypes) nodeTypes = { dql: DqlNode };
    var types = spec.types || [];
    if (types.length) {
      var legend = el("div", "legend");
      types.forEach(function (t) {
        var item = el("span", "item");
        item.appendChild(el("span", "key-rect " + (t.slot === null || t.slot === undefined ? "s-other" : "s" + t.slot)));
        item.appendChild(el("span", null, t.type));
        legend.appendChild(item);
      });
      host.appendChild(legend);
    }
    var box = el("div", "graph-host");
    box.setAttribute("role", "img");
    box.setAttribute("aria-label", (spec.title || "Graph") + ": " + spec.nodes.length + " nodes and " +
      spec.edges.length + " edges. The table view lists every edge.");
    host.appendChild(box);
    var nodes = spec.nodes.map(function (n) {
      return { id: n.id, type: "dql", position: n.position,
               data: Object.assign({}, n.data, { id: n.id }) };
    });
    var edges = spec.edges.map(function (e) {
      return Object.assign({}, e, {
        markerEnd: { type: L.RF.MarkerType.ArrowClosed, width: 16, height: 16 },
        labelBgPadding: [4, 2], labelBgBorderRadius: 3
      });
    });
    var FIT = { padding: 0.15, maxZoom: 1 };
    var root = window.ReactDOM.createRoot(box);
    var flow = null;          // the React Flow instance, for fitView
    // defaultNodes are read once, so a re-render (colour mode, size) keeps
    // whatever the reader has dragged, panned or zoomed.
    var g = { expanded: false, render: function () {
      var children = [
        L.h(L.RF.Background, { key: "bg", gap: 20, size: 1 }),
        L.h(L.RF.Controls, { key: "ctl", showInteractive: false, fitViewOptions: FIT })
      ];
      // The minimap earns its room only in the expanded view; at normal
      // size it would cover nodes.
      if (g.expanded && nodes.length > 20) {
        children.push(L.h(L.RF.MiniMap, { key: "map", pannable: true, zoomable: true }));
      }
      root.render(L.h(L.Flow, {
        defaultNodes: nodes, defaultEdges: edges, nodeTypes: nodeTypes,
        fitView: true, fitViewOptions: FIT, minZoom: 0.1, maxZoom: 2,
        nodesConnectable: false, colorMode: colorMode(),
        onInit: function (inst) { flow = inst; }
      }, children));
    } };
    g.render();
    live.push(g);
    var stop = function () {
      live = live.filter(function (x) { return x !== g; });
      root.unmount();
    };
    // Called when the card grows or shrinks: redraw, then fit the new box.
    stop.resize = function (expanded) {
      g.expanded = !!expanded;
      g.render();
      requestAnimationFrame(function () {
        setTimeout(function () { if (flow) flow.fitView(expanded ? { padding: 0.08, maxZoom: 1.5 } : FIT); }, 60);
      });
    };
    return stop;
  }

  function table(spec) {
    var labels = {};
    spec.nodes.forEach(function (n) { labels[n.id] = n.data.label; });
    var wrap = el("div", "tablewrap");
    var t = el("table", "data"), thead = el("thead"), tbody = el("tbody"), hr = el("tr");
    ["From", "To", "Label", "From id", "To id"].forEach(function (h) { hr.appendChild(el("th", null, h)); });
    thead.appendChild(hr); t.appendChild(thead); t.appendChild(tbody); wrap.appendChild(t);
    spec.edges.forEach(function (e) {
      var tr = el("tr");
      [labels[e.source] || e.source, labels[e.target] || e.target, e.label || "", e.source, e.target]
        .forEach(function (v) { tr.appendChild(el("td", null, v)); });
      tbody.appendChild(tr);
    });
    if (!spec.edges.length) {
      spec.nodes.forEach(function (n) {
        var tr = el("tr");
        [n.data.label, "", "", n.id, ""].forEach(function (v) { tr.appendChild(el("td", null, v)); });
        tbody.appendChild(tr);
      });
    }
    return wrap;
  }

  window.DqlFlow = { graph: graph, table: table };
})();
