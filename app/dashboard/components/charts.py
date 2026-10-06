"""Plotly figure builders in the dark risk-terminal theme. Colour roles: categorical slots in fixed order for
identity; risk colours (with text labels) ONLY for risk levels; a diverging red <-> blue pair with a dark midpoint for
losses vs gains; hedges in green; one y-axis per chart; hover on every mark; tabular figures (IBM Plex Mono)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from components.ui import ACCENT, LINE, MUTED, RISK_COLORS, RISK_ORDER, SURFACE, TEXT

CATEGORICAL = ["#22d3ee", "#f472b6", "#a3e635", "#fbbf24", "#818cf8", "#fb7185", "#34d399", "#c084fc"]
SEQ_BLUE = "#3b82f6"
LOSS, GAIN, MID = "#ef4444", "#3b82f6", "#172238"
HEDGE = "#22c55e"
GRID = "#1c2a45"
FONT = "IBM Plex Sans, Segoe UI, sans-serif"
MONO = "IBM Plex Mono, Consolas, monospace"
PROV = {"CACHED_REAL": "#a78bfa", "LIVE": "#38bdf8", "SYNTHETIC": "#94a3b8"}


def _layout(fig: go.Figure, title: str, height: int = 360, **kw) -> go.Figure:
    fig.update_layout(
        title={"text": title.upper(), "font": {"size": 13, "color": MUTED, "family": FONT}, "x": 0, "xanchor": "left"},
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, height=height, margin={"l": 10, "r": 18, "t": 44, "b": 10},
        font={"size": 13, "color": TEXT, "family": FONT}, hoverlabel={"font_size": 13, "font_family": MONO},
        legend={"orientation": "h", "y": -0.2, "font": {"color": MUTED}}, **kw)
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=LINE, linecolor=LINE, tickfont={"color": MUTED, "family": MONO},
                     title_font={"color": MUTED, "size": 12})
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=LINE, linecolor=LINE, tickfont={"color": MUTED, "family": MONO},
                     title_font={"color": MUTED, "size": 12})
    return fig


def sentiment_trend(df: pd.DataFrame, tickers: list[str]) -> go.Figure:
    fig = go.Figure()
    for i, t in enumerate(tickers[:len(CATEGORICAL)]):
        d = df[df["ticker"] == t].sort_values("time")
        fig.add_trace(go.Scatter(
            x=d["time"], y=d["sentiment_score"], mode="lines+markers", name=t,
            line={"width": 2, "color": CATEGORICAL[i]}, marker={"size": 8, "color": CATEGORICAL[i],
                                                                 "line": {"width": 2, "color": SURFACE}},
            customdata=d[["event_type", "impact_score", "text_excerpt"]].values,
            hovertemplate="<b>%{fullData.name}</b> %{x|%Y-%m-%d %H:%M}<br>sentiment %{y:+.2f}<br>"
                          "%{customdata[0]} · impact %{customdata[1]}<br>%{customdata[2]}<extra></extra>"))
    fig.add_hline(y=0, line={"color": LINE, "width": 1})
    fig.update_yaxes(range=[-1.05, 1.05], title="sentiment (−1 … +1)")
    return _layout(fig, "Sentiment trend by ticker")


def sentiment_band(df: pd.DataFrame, freq: str = "6h") -> go.Figure:
    """Mean sentiment per time bucket (line) with a ±1 standard deviation band, and signal count on hover."""
    d = df.set_index("time").sort_index()["sentiment_score"].resample(freq)
    g = pd.DataFrame({"mean": d.mean(), "std": d.std().fillna(0), "n": d.count()}).dropna(subset=["mean"])
    g = g[g["n"] > 0]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(g.index) + list(g.index[::-1]),
                             y=list((g["mean"] + g["std"]).clip(upper=1)) + list((g["mean"] - g["std"]).clip(lower=-1)
                                                                                 [::-1]),
                             fill="toself", fillcolor="rgba(34,211,238,0.12)", line={"width": 0}, hoverinfo="skip",
                             name="±1 std"))
    fig.add_trace(go.Scatter(x=g.index, y=g["mean"], mode="lines+markers", name="mean sentiment",
                             line={"color": ACCENT, "width": 2}, marker={"size": 5}, customdata=g["n"],
                             hovertemplate="%{x|%b %d %H:%M}<br>mean %{y:+.2f} · %{customdata} signals<extra></extra>"))
    fig.add_hline(y=0, line={"color": LINE, "width": 1})
    fig.update_yaxes(range=[-1.05, 1.05], title="sentiment")
    return _layout(fig, f"Sentiment trend ({freq} buckets, band = ±1 std)", height=320)


def data_mix(counts: dict[str, int], title: str) -> go.Figure:
    labels = list(counts)
    fig = go.Figure(go.Pie(labels=labels, values=list(counts.values()), hole=0.62, sort=False,
                           marker={"colors": [PROV.get(k, CATEGORICAL[i % len(CATEGORICAL)])
                                              for i, k in enumerate(labels)], "line": {"color": SURFACE, "width": 2}},
                           textinfo="percent", textfont={"family": MONO, "size": 12},
                           hovertemplate="%{label}: %{value} signals (%{percent})<extra></extra>"))
    fig.update_layout(showlegend=True, legend={"orientation": "v", "x": 1.0, "y": 0.5})
    return _layout(fig, title, height=240)


def event_distribution(df: pd.DataFrame) -> go.Figure:
    counts = df["event_type"].value_counts().sort_values()
    fig = go.Figure(go.Bar(x=counts.values, y=counts.index, orientation="h", marker={"color": SEQ_BLUE,
                    "cornerradius": 4}, text=counts.values, textposition="outside",
                    hovertemplate="%{y}: %{x} signals<extra></extra>"))
    fig.update_xaxes(title="signals")
    return _layout(fig, "Event distribution", height=max(320, 34 * len(counts) + 90))


def impact_distribution(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    bins = {"start": 1, "end": 10.01, "size": 0.5}
    for level in RISK_ORDER:
        d = df[df["risk_level"] == level]
        if len(d):
            fig.add_trace(go.Histogram(x=d["impact_score"], xbins=bins, name=level,
                                       marker={"color": RISK_COLORS[level], "line": {"width": 1, "color": SURFACE}},
                                       hovertemplate=f"{level}: impact %{{x}}<br>%{{y}} signals<extra></extra>"))
    for x, label in [(4, "Medium"), (7, "High"), (8.5, "Critical")]:
        fig.add_vline(x=x, line={"dash": "dot", "color": LINE, "width": 1},
                      annotation_text=label, annotation_font_color=MUTED)
    fig.update_layout(barmode="stack")
    fig.update_xaxes(range=[1, 10], title="impact score (1–10)")
    fig.update_yaxes(title="signals")
    return _layout(fig, "Impact score distribution")


def share_bar(shares: dict[str, float], title: str, order: list[str] | None = None) -> go.Figure:
    items = [(k, shares[k]) for k in (order or list(shares)) if k in shares]
    fig = go.Figure(go.Bar(x=[v * 100 for _, v in items], y=[k for k, _ in items], orientation="h",
                           marker={"color": SEQ_BLUE, "cornerradius": 4},
                           text=[f"{v * 100:.1f}%" for _, v in items], textposition="outside",
                           hovertemplate="%{y}: %{x:.1f}%<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="% of total", range=[0, max(v for _, v in items) * 118 if items else 1])
    return _layout(fig, title, height=max(300, 36 * len(items) + 100))


def waterfall(summary: dict) -> go.Figure:
    by = summary["by_asset_class"]
    names = ["Before"] + list(by) + ["After"]
    values = [summary["before_value"] / 1e6] + [v / 1e6 for v in by.values()] + [summary["after_value"] / 1e6]
    fig = go.Figure(go.Waterfall(
        x=names, y=values, measure=["absolute"] + ["relative"] * len(by) + ["total"],
        text=[f"{v:,.1f}" for v in values], textposition="outside",
        decreasing={"marker": {"color": LOSS}}, increasing={"marker": {"color": GAIN}},
        totals={"marker": {"color": "#475569"}}, connector={"line": {"color": LINE, "width": 1}},
        hovertemplate="%{x}: %{y:,.2f}m USD<extra></extra>"))
    lo = min(summary["after_value"], summary["before_value"]) / 1e6
    fig.update_yaxes(title="portfolio value (USD m)", range=[lo * 0.97, summary["before_value"] / 1e6 * 1.01])
    return _layout(fig, "Before vs after stress (funded value, by asset class)", height=420)


def pnl_bar(pnl: dict[str, float], title: str, height: int | None = None) -> go.Figure:
    """Horizontal P&L bars (USD m): losses red, gains blue; worst at the top."""
    items = sorted(pnl.items(), key=lambda kv: kv[1])
    fig = go.Figure(go.Bar(x=[v / 1e6 for _, v in items], y=[k for k, _ in items], orientation="h",
                           marker={"color": [LOSS if v < 0 else GAIN for _, v in items], "cornerradius": 3},
                           text=[f"{v / 1e6:+,.1f}" for _, v in items], textposition="auto",
                           hovertemplate="%{y}: %{x:+,.2f}m USD<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.add_vline(x=0, line={"color": LINE, "width": 1})
    fig.update_xaxes(title="stress P&L (USD m)")
    return _layout(fig, title, height=height or max(260, 30 * len(items) + 90))


def exposure_bar(values: dict[str, float], title: str) -> go.Figure:
    """Horizontal bars of USD exposure (accent colour), largest at the top."""
    items = sorted(values.items(), key=lambda kv: -kv[1])
    fig = go.Figure(go.Bar(x=[v / 1e6 for _, v in items], y=[k for k, _ in items], orientation="h",
                           marker={"color": ACCENT, "cornerradius": 3}, text=[f"${v / 1e6:,.1f}m" for _, v in items],
                           textposition="auto", hovertemplate="%{y}: $%{x:,.2f}m<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="USD m")
    return _layout(fig, title, height=max(220, 34 * len(items) + 90))


def top_positions(summary: dict) -> go.Figure:
    rows = sorted(summary["top_contributors"], key=lambda r: r["pnl"])
    labels = [f"{r['asset_id']} · {r['issuer_name'] or r['asset_type']}" + (" (hedge)" if r["is_hedge"] else "")
              for r in rows]
    colors = [HEDGE if r["is_hedge"] else LOSS for r in rows]
    fig = go.Figure(go.Bar(x=[r["pnl"] / 1e6 for r in rows], y=labels, orientation="h",
                           marker={"color": colors, "cornerradius": 4},
                           text=[f"{r['pnl'] / 1e6:+,.2f}m" for r in rows], textposition="auto",
                           hovertemplate="%{y}<br>P&L %{x:+,.2f}m USD<extra></extra>"))
    fig.add_vline(x=0, line={"color": LINE, "width": 1})
    fig.update_xaxes(title="stress P&L (USD m) — red = loss, green = hedge gain")
    return _layout(fig, "Top-10 contributing positions", height=460)


def heatmap(summary: dict) -> go.Figure:
    heat = summary["heatmap"]
    sectors = sorted(heat, key=lambda s: sum(heat[s].values()))
    classes = sorted({a for row in heat.values() for a in row})
    z = [[heat[s].get(a, 0.0) / 1e6 for a in classes] for s in sectors]
    bound = max((abs(v) for row in z for v in row), default=1) or 1
    text = [[f"{v:+.1f}" if abs(v) >= 0.05 else "" for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=classes, y=sectors, zmin=-bound, zmax=bound, zmid=0,
        colorscale=[[0, LOSS], [0.5, MID], [1, GAIN]], text=text, texttemplate="%{text}",
        colorbar={"title": "USD m"}, xgap=2, ygap=2,
        hovertemplate="%{y} × %{x}<br>P&L %{z:+,.2f}m USD<extra></extra>"))
    return _layout(fig, "Risk heatmap: stress P&L by sector × asset class (red = loss)",
                   height=max(360, 34 * len(sectors) + 120))


def sentiment_probs(probs: dict) -> go.Figure:
    order = [("negative", LOSS), ("neutral", "#64748b"), ("positive", HEDGE)]
    fig = go.Figure(go.Bar(x=[n for n, _ in order], y=[probs.get(n, 0) for n, _ in order],
                           marker={"color": [c for _, c in order], "cornerradius": 4},
                           text=[f"{probs.get(n, 0):.2f}" for n, _ in order], textposition="outside",
                           hovertemplate="P(%{x}) = %{y:.3f}<extra></extra>"))
    fig.update_yaxes(range=[0, 1.15], title="probability")
    return _layout(fig, "Sentiment probabilities", height=300)


def factor_contributions(factors: dict, weights: dict) -> go.Figure:
    names = {"E": "E · event severity", "M": "M · sentiment magnitude", "X": "X · exposure / breadth",
             "R": "R · source credibility"}
    keys = ["E", "M", "X", "R"]
    contrib = [weights[k] * factors[k] for k in keys]
    fig = go.Figure(go.Bar(
        x=contrib, y=[names[k] for k in keys], orientation="h", marker={"color": ACCENT, "cornerradius": 3},
        text=[f"{weights[k]:.2f} × {factors[k]:.2f} = {c:.3f}" for k, c in zip(keys, contrib, strict=True)],
        textposition="outside", hovertemplate="%{y}<br>weighted contribution %{x:.3f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, 0.55], title="weight × factor")
    return _layout(fig, "Impact factors (weighted contributions)", height=300)


STATUS = {"WATCH-NEGATIVE": "#ef4444", "MONITOR": "#f5b841", "STABLE": "#22c55e"}


def network_layout(graph: dict, center: str) -> dict[str, tuple[float, float]]:
    """Deterministic radial layout: centre issuer, hop-1 issuers on a ring, hop-2 near their parent, sectors outside,
    positions as small satellites around their issuer."""
    import math

    pos: dict[str, tuple[float, float]] = {center: (0.0, 0.0)}
    hop1 = sorted([n for n in graph["nodes"] if n["kind"] == "issuer" and n.get("hop") == 1],
                  key=lambda n: -n.get("exposure", 0))
    if len(hop1) == 1:
        angles = [math.pi / 2]
    elif len(hop1) == 2:  # upper-left / upper-right: a link between them never crosses the centre node
        angles = [5 * math.pi / 6, math.pi / 6]
    else:
        angles = [math.pi / 2 + 2 * math.pi * i / len(hop1) for i in range(len(hop1))]
    for n, a in zip(hop1, angles, strict=True):
        pos[n["id"]] = (1.0 * math.cos(a), 1.0 * math.sin(a))
    adj = {}
    for e in graph["edges"]:
        adj.setdefault(e["a"], []).append(e["b"])
        adj.setdefault(e["b"], []).append(e["a"])
    hop2 = [n for n in graph["nodes"] if n["kind"] == "issuer" and n.get("hop", 0) >= 2]
    for i, n in enumerate(hop2):
        parent = next((p for p in adj.get(n["id"], []) if p in pos and p != center), None)
        base = math.atan2(*reversed(pos[parent])) if parent else 2 * math.pi * i / max(len(hop2), 1)
        a = base + (i % 3 - 1) * 0.35
        pos[n["id"]] = (1.85 * math.cos(a), 1.85 * math.sin(a))
    sectors = [n for n in graph["nodes"] if n["kind"] == "sector"]
    for n in sectors:
        members = [m for m in adj.get(n["id"], []) if m in pos]
        if center in members or not members:  # the centre issuer's own sector: just below it
            pos[n["id"]] = (0.0, -0.8)
            continue
        ax = sum(pos[m][0] for m in members) / len(members)
        ay = sum(pos[m][1] for m in members) / len(members)
        a = math.atan2(ay, ax)
        pos[n["id"]] = (ax + 0.75 * math.cos(a), ay + 0.75 * math.sin(a))
    for n in graph["nodes"]:
        if n["kind"] != "issuer" or n["id"] not in pos:
            continue
        cx, cy = pos[n["id"]]
        k = len(n.get("positions", []))
        for j, p in enumerate(n.get("positions", [])):
            a = 2 * math.pi * j / max(k, 1) + 0.4
            r = 0.26 if n["id"] == center else 0.2
            pos[f"pos:{p['asset_id']}"] = (cx + r * math.cos(a), cy + r * math.sin(a))
    return pos


def network(graph: dict, center: str, height: int = 560) -> go.Figure:
    """Exposure graph: issuers (size = exposure, colour = watch status), sectors (grey squares), positions (dots),
    issuer links labelled with the relation (width = decay weight)."""
    pos = network_layout(graph, center)
    nodes = {n["id"]: n for n in graph["nodes"]}
    fig = go.Figure()
    for e in graph["edges"]:
        if e["a"] not in pos or e["b"] not in pos:
            continue
        (x0, y0), (x1, y1) = pos[e["a"]], pos[e["b"]]
        is_sector = e["relation"] == "sector"
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", hoverinfo="skip", showlegend=False,
                                 line={"color": LINE if is_sector else ACCENT, "dash": "dot" if is_sector else
                                       ("dash" if e["relation"] == "peer_of" else "solid"),
                                       "width": 1 if is_sector else 1 + 4 * float(e.get("weight") or 0)}))
        if not is_sector:
            fx = 0.6 if e["a"] == center else (0.4 if e["b"] == center else 0.5)  # keep labels off the centre node
            fig.add_annotation(x=x0 + fx * (x1 - x0), y=y0 + fx * (y1 - y0),
                               text=f"{e['relation']} · {e.get('weight')}",
                               showarrow=False, font={"size": 11, "color": ACCENT, "family": MONO},
                               bgcolor="rgba(11,18,32,0.85)")
    px, py, ptext, pcol = [], [], [], []
    for n in graph["nodes"]:
        for p in n.get("positions", []):
            key = f"pos:{p['asset_id']}"
            if key in pos:
                fig.add_trace(go.Scatter(x=[pos[n["id"]][0], pos[key][0]], y=[pos[n["id"]][1], pos[key][1]],
                                         mode="lines", line={"color": "#24324f", "width": 1}, hoverinfo="skip",
                                         showlegend=False))
                px.append(pos[key][0])
                py.append(pos[key][1])
                val = p["market_value"] or p["notional"]
                ptext.append(f"{p['asset_id']} · {p['asset_type']} {p['side']}<br>${val / 1e6:,.1f}m "
                             f"({'MV' if p['market_value'] else 'notional'}) · {p['rating_bucket']}")
                pcol.append(HEDGE if p["side"] == "protection_bought" else "#64748b")
    fig.add_trace(go.Scatter(x=px, y=py, mode="markers", marker={"size": 7, "color": pcol}, hovertext=ptext,
                             hoverinfo="text", name="positions", showlegend=False))
    sx = [pos[n] for n in nodes if nodes[n]["kind"] == "sector" and n in pos]
    fig.add_trace(go.Scatter(x=[p[0] for p in sx], y=[p[1] for p in sx], mode="markers+text",
                             marker={"symbol": "square", "size": 12, "color": "#334155"},
                             text=[nodes[n]["name"] for n in nodes if nodes[n]["kind"] == "sector" and n in pos],
                             textposition="bottom center", textfont={"size": 11, "color": MUTED}, hoverinfo="text",
                             hovertext=[f"sector: {nodes[n]['name']}" for n in nodes
                                        if nodes[n]["kind"] == "sector" and n in pos], showlegend=False))
    iss = [n for n in graph["nodes"] if n["kind"] == "issuer" and n["id"] in pos]
    mx = max((n["exposure"] for n in iss), default=1) or 1
    fig.add_trace(go.Scatter(
        x=[pos[n["id"]][0] for n in iss], y=[pos[n["id"]][1] for n in iss], mode="markers+text",
        marker={"size": [18 + 34 * (n["exposure"] / mx) ** 0.5 for n in iss],
                "color": [STATUS.get(n["status"], "#64748b") for n in iss],
                "line": {"width": [3 if n["id"] == center else 1 for n in iss], "color": TEXT}},
        text=[n["name"].replace(" Ltd.", "").replace(" Inc.", "").replace(" Corp.", "") for n in iss],
        textposition="top center", textfont={"size": 12, "color": TEXT, "family": FONT},
        customdata=[n["id"] for n in iss],
        hovertext=[f"<b>{n['name']}</b> · {n['status']}<br>exposure ${n['exposure'] / 1e6:,.1f}m "
                   f"({n['exposure_pct']:.2f}% of book)<br>hop {n['hop']} · weight {n['weight']:g}" for n in iss],
        hoverinfo="text", name="issuers", showlegend=False))
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    fig.update_xaxes(visible=False, range=[min(xs) - 0.55, max(xs) + 0.55])
    fig.update_yaxes(visible=False, range=[min(ys) - 0.45, max(ys) + 0.45], scaleanchor="x")
    return _layout(fig, "Exposure graph: curated links, size = exposure, colour = watch status", height=height,
                   clickmode="event+select", dragmode=False)
