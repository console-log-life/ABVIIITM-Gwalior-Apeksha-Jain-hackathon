"""Risk propagation (contagion) over CURATED issuer links (universe.yaml `links`), not inferred from data.

When a signal hits an issuer:
  direct exposure     = the funded market value we hold in that issuer (1st order);
  propagated exposure = sum over LINKED issuers j of  weight_j x funded exposure_j  (2nd order),
where weight_j is the decay of the relation (supplier_of / parent_of 0.5, peer_of 0.3 by default, config
PROPAGATION_DECAY). With PROPAGATION_MAX_HOPS > 1, longer paths multiply their decays. Every issuer is counted ONCE, at
the strongest path that reaches it (no double counting); the start issuer is never counted as propagated, so cycles
cannot inflate the total. Links are two-way for contagion.

Illustrative: this is a curated exposure map for analyst attention, not a correlation or default-contagion model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import Settings
from risk_engine.entity_resolution.resolver import UNIVERSE_YAML


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    relation: str
    note: str = ""


@lru_cache(maxsize=4)
def load_links(path: Path = UNIVERSE_YAML) -> tuple[Link, ...]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return tuple(Link(x["a"], x["b"], x["relation"], x.get("note", "")) for x in data.get("links") or [])


def neighbours(links: tuple[Link, ...]) -> dict[str, list[tuple[str, Link]]]:
    out: dict[str, list[tuple[str, Link]]] = {}
    for ln in links:
        out.setdefault(ln.a, []).append((ln.b, ln))
        out.setdefault(ln.b, []).append((ln.a, ln))
    return out


def reach(start: str, links: tuple[Link, ...], decay: dict[str, float], max_hops: int = 1) -> dict[str, dict]:
    """Issuers reachable from `start` within max_hops: {issuer: {"weight", "path": [relations], "via"}}; each issuer
    keeps its STRONGEST path (product of decays). `start` itself is excluded."""
    nb = neighbours(links)
    best: dict[str, dict] = {}
    frontier = [(start, 1.0, [], [start])]
    for _ in range(max_hops):
        nxt = []
        for node, w, rels, seen in frontier:
            for other, ln in nb.get(node, []):
                if other in seen:  # cycle guard
                    continue
                w2 = w * float(decay.get(ln.relation, 0.0))
                if w2 <= 0:
                    continue
                path = rels + [ln.relation]
                if other != start and (other not in best or w2 > best[other]["weight"]):
                    best[other] = {"weight": round(w2, 6), "path": path, "via": seen[1:] + [other],
                                   "note": ln.note if len(path) == 1 else ""}
                nxt.append((other, w2, path, seen + [other]))
        frontier = nxt
    return best


def propagated_exposure(issuer_id: str, exposures: dict[str, float], book: float, settings: Settings,
                        links: tuple[Link, ...] | None = None) -> dict:
    links = load_links() if links is None else links
    hits = reach(issuer_id, links, settings.propagation_decay, settings.propagation_max_hops)
    contrib = []
    for other, h in sorted(hits.items(), key=lambda kv: -kv[1]["weight"] * exposures.get(kv[0], 0.0)):
        exp = exposures.get(other, 0.0)
        contrib.append({"issuer_id": other, "relation": " → ".join(h["path"]), "weight": h["weight"],
                        "exposure": round(exp, 2), "weighted": round(h["weight"] * exp, 2), "note": h["note"]})
    direct = exposures.get(issuer_id, 0.0)
    prop = sum(c["weighted"] for c in contrib)
    book = book or 1.0
    return {"issuer_id": issuer_id, "direct_exposure": round(direct, 2), "direct_pct": round(100 * direct / book, 2),
            "propagated_exposure": round(prop, 2), "propagated_pct": round(100 * prop / book, 2),
            "total_pct": round(100 * (direct + prop) / book, 2), "contributions": contrib,
            "decay": dict(settings.propagation_decay), "max_hops": settings.propagation_max_hops}


def propagation_monitor(statuses: dict[str, str], settings: Settings,
                        links: tuple[Link, ...] | None = None) -> dict[str, str]:
    """STABLE issuers linked (weight >= WATCHLIST_PROPAGATION_MIN_WEIGHT) to a WATCH-NEGATIVE issuer -> reason text."""
    min_w = settings.watchlist_propagation_min_weight
    if min_w <= 0:
        return {}
    links = load_links() if links is None else links
    out: dict[str, str] = {}
    for src, status in statuses.items():
        if status != "WATCH-NEGATIVE":
            continue
        for other, h in reach(src, links, settings.propagation_decay, settings.propagation_max_hops).items():
            if statuses.get(other) == "STABLE" and h["weight"] >= min_w and other not in out:
                out[other] = f"linked to {src} ({' → '.join(h['path'])}, weight {h['weight']:g}) on WATCH-NEGATIVE"
    return out
