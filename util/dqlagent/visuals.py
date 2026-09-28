"""Charts and graphs for the browser chat, built only from query results the
agent already holds. The model names a result and the fields to draw; every
number and every node comes from the records Grail returned, never from text
the model wrote.

Specs are plain JSON, so any front end can draw them. Graphs use React Flow's
node and edge shape ({id, data, position} / {id, source, target}), with
positions computed here, so they drop into React Flow as they are.
"""

import math
import re
from datetime import datetime, timezone

# The categorical palette has eight validated slots. A ninth series never gets
# a generated hue; the chart keeps the eight largest and says how many it left out.
MAX_SERIES = 8
MAX_POINTS = 1500
MAX_BARS = 30
MAX_NODES = 150
MAX_EDGES = 400

# Node types keep their colour slot across every graph (colour follows the
# entity, never its rank). Types not listed take the free slots in order.
TYPE_SLOTS = {"HOST": 0, "PROCESS": 1, "PROCESS_GROUP_INSTANCE": 1, "SERVICE": 2,
              "K8S_POD": 3, "CONTAINER": 3, "CONTAINER_GROUP_INSTANCE": 3,
              "K8S_CLUSTER": 4, "K8S_NAMESPACE": 4, "KUBERNETES_CLUSTER": 4,
              "APPLICATION": 6, "PROBLEM": 7}
FREE_SLOTS = [5]

_ID_TYPE = re.compile(r"^([A-Z][A-Z0-9_]*)-[0-9A-Fa-f]{6,}$")
_PROBLEM_ID = re.compile(r"^P-\d+$")          # Davis problem display ids


class VisualError(ValueError):
    pass


def _get(rec: dict, name: str):
    """A field by its flat name ('dt.entity.host'), else by a dotted path into
    nested records ('timeframe.start')."""
    if name in rec:
        return rec[name]
    cur = rec
    for part in name.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _fields(records) -> list[str]:
    seen = []
    for rec in records[:200]:
        for k in rec:
            if k not in seen:
                seen.append(k)
    return seen


def _need(records, *names):
    fields = _fields(records)
    for name in names:
        if name and not any(_get(r, name) is not None for r in records[:200]):
            if any(name in r for r in records[:200]):
                raise VisualError(f"Field {name!r} is empty (null) in every record.")
            raise VisualError(f"No field {name!r} in this result. Its fields are: "
                              + ", ".join(fields[:40]))


def _ts_ms(value):
    """ISO timestamp (with up to nanosecond fractions) or epoch number to ms."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1e6 if v > 1e14 else v          # ns -> ms, else already ms
    text = str(value).strip().replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", text)
    if m:
        text = m.group(1) + (m.group(2) or "")[:7] + m.group(3)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() * 1000


_DUR = {"ns": 1e-6, "us": 1e-3, "ms": 1, "s": 1e3, "m": 6e4, "h": 3.6e6, "d": 8.64e7}


def _duration_ms(value):
    """Grail durations arrive as nanoseconds (number or digit string); '5m' style too."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1e6
    text = str(value).strip()
    if text.isdigit():
        return int(text) / 1e6
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(ns|us|ms|s|m|h|d)$", text)
    return float(m.group(1)) * _DUR[m.group(2)] if m else None


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def timeseries(records, value_field, series_field=None, title="", unit="") -> dict:
    if not records:
        raise VisualError("The result has no records to draw.")
    _need(records, value_field, series_field)
    series = []
    for i, rec in enumerate(records):
        vals = _get(rec, value_field)
        if vals is None:
            continue
        if not isinstance(vals, list):
            raise VisualError(f"{value_field!r} holds single values, not a series over "
                              "time. Use show_bar, or run timeseries without scalar:true.")
        start = _ts_ms(_get(rec, "timeframe.start"))
        step = _duration_ms(rec.get("interval"))
        timed = start is not None and bool(step)
        points = [[start + j * step if timed else j, _num(v)] for j, v in enumerate(vals)]
        if series_field:
            name = _get(rec, series_field)
            name = ", ".join(map(str, name)) if isinstance(name, list) else str(name)
        else:
            name = value_field if len(records) == 1 else f"{value_field} #{i + 1}"
        series.append({"name": name, "points": points, "timed": timed, "order": i})
    if not series:
        raise VisualError(f"No record has a value in {value_field!r}.")
    dropped = 0
    if len(series) > MAX_SERIES:
        def peak(s):
            return max((p[1] for p in s["points"] if p[1] is not None), default=float("-inf"))
        keep = sorted(series, key=peak, reverse=True)[:MAX_SERIES]
        dropped = len(series) - MAX_SERIES
        series = sorted(keep, key=lambda s: s["order"])    # colours follow record order
    for s in series:
        if len(s["points"]) > MAX_POINTS:
            stride = math.ceil(len(s["points"]) / MAX_POINTS)
            s["points"] = s["points"][::stride]
    timed = all(s["timed"] for s in series)
    for s in series:
        s.pop("timed"), s.pop("order")
    return {"kind": "timeseries", "title": title or value_field, "unit": unit,
            "x": "time" if timed else "index", "series": series, "dropped": dropped}


def bar(records, label_field, value_field, title="", unit="", limit=20) -> dict:
    if not records:
        raise VisualError("The result has no records to draw.")
    _need(records, label_field, value_field)
    rows = []
    for rec in records:
        v = _get(rec, value_field)
        if isinstance(v, list):
            raise VisualError(f"{value_field!r} is a series over time. Use show_timeseries, "
                              "or run the timeseries with scalar:true for one value per row.")
        v = _num(v)
        if v is None:
            continue
        label = _get(rec, label_field)
        rows.append({"label": ", ".join(map(str, label)) if isinstance(label, list) else str(label),
                     "value": v})
    if not rows:
        raise VisualError(f"No record has a number in {value_field!r}.")
    rows.sort(key=lambda r: r["value"], reverse=True)
    limit = max(1, min(int(limit or 20), MAX_BARS))
    return {"kind": "bar", "title": title or value_field, "unit": unit,
            "bars": rows[:limit], "dropped": max(0, len(rows) - limit)}


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------

def _node_type(explicit, node_id: str) -> str:
    if explicit:
        return str(explicit).upper()
    if _PROBLEM_ID.match(node_id):
        return "PROBLEM"
    m = _ID_TYPE.match(node_id)
    return m.group(1) if m else ""


def graph(records, source_field, target_field, source_label_field=None,
          target_label_field=None, edge_label_field=None, title="", highlight=None) -> dict:
    """Nodes and edges from rows that each name a source and one or more targets
    (a target field may hold an array, e.g. a problem's affected_entity_ids)."""
    if not records:
        raise VisualError("The result has no records to draw.")
    _need(records, source_field, target_field, source_label_field, target_label_field,
          edge_label_field)
    # Smartscape edge rows carry the node types next to the ids.
    s_type_f = "source_type" if source_field == "source_id" else None
    t_type_f = "target_type" if target_field == "target_id" else None
    nodes, edges = {}, {}

    def add_node(nid, label, ntype):
        if nid not in nodes:
            if len(nodes) >= MAX_NODES:
                return False
            nodes[nid] = {"label": str(label) if label not in (None, "") else nid,
                          "type": _node_type(ntype, nid)}
        elif label not in (None, "") and nodes[nid]["label"] == nid:
            nodes[nid]["label"] = str(label)
        return True

    truncated = False
    for rec in records:
        src = _get(rec, source_field)
        if src in (None, ""):
            continue
        src = str(src)
        if not add_node(src, _get(rec, source_label_field) if source_label_field else None,
                        rec.get(s_type_f) if s_type_f else None):
            truncated = True
            continue
        targets = _get(rec, target_field)
        targets = targets if isinstance(targets, list) else [targets]
        t_labels = _get(rec, target_label_field) if target_label_field else None
        for i, tgt in enumerate(targets):
            if tgt in (None, ""):
                continue
            tgt = str(tgt)
            label = t_labels[i] if isinstance(t_labels, list) and i < len(t_labels) else (
                t_labels if not isinstance(t_labels, list) else None)
            if not add_node(tgt, label, rec.get(t_type_f) if t_type_f else None):
                truncated = True
                continue
            key = (src, tgt)
            if key not in edges:
                if len(edges) >= MAX_EDGES:
                    truncated = True
                    continue
                edges[key] = {"count": 0, "label": None}
            edges[key]["count"] += 1
            if edge_label_field and edges[key]["label"] is None:
                v = _get(rec, edge_label_field)
                edges[key]["label"] = None if v is None else str(v)
    if not nodes:
        raise VisualError(f"No record has a value in {source_field!r}.")

    # Colour slots per type: fixed for known types, then free slots, then grey.
    free, slots = list(FREE_SLOTS), {}
    for n in nodes.values():
        t = n["type"]
        if t in slots:
            continue
        if t in TYPE_SLOTS:
            slots[t] = TYPE_SLOTS[t]
        elif free:
            slots[t] = free.pop(0)
        else:
            slots[t] = None

    wanted = {str(h).lower() for h in (highlight or [])}
    positions = layered_layout(list(nodes), list(edges))
    out_nodes = [{"id": nid,
                  "data": {"label": n["label"], "type": n["type"] or "node",
                           "slot": slots.get(n["type"]),
                           "highlight": nid.lower() in wanted or n["label"].lower() in wanted},
                  "position": {"x": positions[nid][0], "y": positions[nid][1]}}
                 for nid, n in nodes.items()]
    out_edges = []
    for i, ((s, t), e) in enumerate(edges.items()):
        label = e["label"] or (f"×{e['count']}" if e["count"] > 1 else None)
        edge = {"id": f"e{i}", "source": s, "target": t}
        if label:
            edge["label"] = label
        out_edges.append(edge)
    types = sorted({(n["type"] or "node", slots.get(n["type"])) for n in nodes.values()},
                   key=lambda x: (x[1] is None, x[1] if x[1] is not None else 99, x[0]))
    return {"kind": "graph", "title": title, "nodes": out_nodes, "edges": out_edges,
            "types": [{"type": t, "slot": s} for t, s in types], "truncated": truncated}


def layered_layout(ids: list[str], edges: list[tuple[str, str]], col_w: int = 280,
                   row_h: int = 76, max_rows: int = 16) -> dict[str, tuple[int, int]]:
    """Left-to-right layered layout: break cycles, layer by longest path, order
    each layer by the barycentre of its neighbours, then wrap tall layers into
    extra columns so a star (one problem, sixty entities) stays readable."""
    succ = {n: [] for n in ids}
    pred = {n: [] for n in ids}
    for s, t in edges:
        if s != t and s in succ and t in succ:
            succ[s].append(t)
            pred[t].append(s)

    # Drop back edges found by DFS so the rest is acyclic.
    state, back = {}, set()
    for root in sorted(ids, key=lambda n: (len(pred[n]), n)):
        if root in state:
            continue
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((node, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(succ[nxt])))

    dag = {n: [t for t in succ[n] if (n, t) not in back] for n in ids}
    indeg = {n: 0 for n in ids}
    for n in ids:
        for t in dag[n]:
            indeg[t] += 1
    layer = {n: 0 for n in ids}
    queue = sorted(n for n in ids if indeg[n] == 0)
    while queue:
        n = queue.pop(0)
        for t in dag[n]:
            layer[t] = max(layer[t], layer[n] + 1)
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)

    depth = max(layer.values(), default=0)
    layers = [[] for _ in range(depth + 1)]
    for n in sorted(ids):
        layers[layer[n]].append(n)

    def reorder(target, neighbours, ref):
        pos = {n: i for i, n in enumerate(ref)}
        def key(n):
            ps = [pos[m] for m in neighbours[n] if m in pos]
            return (sum(ps) / len(ps) if ps else float("inf"), n)
        target.sort(key=key)

    for _ in range(4):
        for i in range(1, len(layers)):
            reorder(layers[i], pred, layers[i - 1])
        for i in range(len(layers) - 2, -1, -1):
            reorder(layers[i], succ, layers[i + 1])

    positions, x = {}, 0
    for nodes_in_layer in layers:
        cols = max(1, math.ceil(len(nodes_in_layer) / max_rows))
        per_col = math.ceil(len(nodes_in_layer) / cols) if nodes_in_layer else 0
        for c in range(cols):
            chunk = nodes_in_layer[c * per_col:(c + 1) * per_col]
            for r, n in enumerate(chunk):
                positions[n] = (x + c * col_w, int((r - (len(chunk) - 1) / 2) * row_h))
        x += cols * col_w
    return positions
