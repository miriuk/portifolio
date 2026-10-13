"""How to split money among the names already chosen.

The PM (arena/desk.py) takes *which* symbols to hold and *how much* to
invest from the agents' votes. The split among those symbols can come
from the votes themselves, or from the risk of the names:

- `equal`: the same slice each (the control: a better split must beat it);
- `inverse_vol`: each name in proportion to 1 / its volatility, so a calm
  stock and a wild coin put the same risk in the book (naive risk parity);
- `hrp`: Hierarchical Risk Parity (López de Prado, 2016, "Building
  Diversified Portfolios that Outperform Out of Sample"; implemented in
  PyPortfolioOpt and skfolio, written here from the paper): names are
  clustered by how they move together, and the money is split top-down
  along that tree, between the two branches of each node, in inverse
  proportion to each branch's variance (the tree-following bisection
  later implementations use; the paper halves the sorted list). Two names that are
  really one bet (Nasdaq-100 and Nvidia, BTC and ETH) share a slice
  instead of taking two, and no covariance matrix is ever inverted,
  which is what makes it stable on short, noisy histories.

Everything here is numpy only; weights are long-only and sum to one.
"""
from __future__ import annotations

import numpy as np

METHODS = ("votes", "equal", "inverse_vol", "hrp")


def _clean(returns: np.ndarray) -> np.ndarray:
    r = np.asarray(returns, float)
    return r[~np.isnan(r).any(axis=1)] if r.ndim == 2 else r


def inverse_vol_weights(returns: np.ndarray) -> np.ndarray:
    """T x n returns -> n weights proportional to 1 / standard deviation."""
    r = _clean(returns)
    sd = r.std(axis=0, ddof=1) if len(r) > 1 else np.ones(r.shape[1])
    sd = np.where(sd > 0, sd, np.nanmin(sd[sd > 0]) if (sd > 0).any() else 1.0)
    w = 1.0 / sd
    return w / w.sum()


def linkage_tree(dist: np.ndarray):
    """Single-linkage tree over a distance matrix, as nested pairs of leaf
    indices: names that move together merge first."""
    n = len(dist)
    nodes = {i: (i, [i]) for i in range(n)}            # id -> (tree, leaves)
    while len(nodes) > 1:
        keys = list(nodes)
        best, pair = np.inf, None
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                d = dist[np.ix_(nodes[keys[a]][1], nodes[keys[b]][1])].min()
                if d < best:
                    best, pair = d, (keys[a], keys[b])
        p, q = pair
        (tp, lp), (tq, lq) = nodes[p], nodes.pop(q)
        nodes[p] = ((tp, tq), lp + lq)
    return next(iter(nodes.values()))[0]


def _leaves(tree) -> list[int]:
    return [tree] if isinstance(tree, (int, np.integer)) else _leaves(tree[0]) + _leaves(tree[1])


def seriation(dist: np.ndarray) -> list[int]:
    """Leaf order of the linkage tree: names that merge early sit side by side."""
    return _leaves(linkage_tree(dist))


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    sub = cov[np.ix_(idx, idx)]
    ivp = 1.0 / np.maximum(np.diag(sub), 1e-18)
    ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)


def hrp_weights(returns: np.ndarray) -> np.ndarray:
    """T x n returns -> n Hierarchical Risk Parity weights."""
    r = _clean(returns)
    n = r.shape[1]
    if n == 1:
        return np.ones(1)
    if len(r) < 3:
        return np.full(n, 1.0 / n)
    cov = np.cov(r, rowvar=False)
    sd = np.sqrt(np.maximum(np.diag(cov), 1e-18))
    corr = np.clip(cov / np.outer(sd, sd), -1.0, 1.0)
    dist = np.sqrt(np.maximum((1.0 - corr) / 2.0, 0.0))
    w = np.ones(n)
    stack = [linkage_tree(dist)]                    # split along the tree, cluster by cluster
    while stack:
        node = stack.pop()
        if isinstance(node, (int, np.integer)):
            continue
        left, right = _leaves(node[0]), _leaves(node[1])
        vl, vr = _cluster_var(cov, left), _cluster_var(cov, right)
        alpha = 1.0 - vl / (vl + vr) if vl + vr > 0 else 0.5
        w[left] *= alpha
        w[right] *= 1.0 - alpha
        stack += [node[0], node[1]]
    return w / w.sum()


def split(method: str, symbols: list[str], returns: np.ndarray | None,
          votes: dict[str, float]) -> dict[str, float]:
    """Shares (summing to one) of the chosen `symbols` under `method`;
    `returns` is T x len(symbols), oldest first. Falls back to the votes'
    own proportions when there is too little history."""
    if not symbols:
        return {}
    total = sum(votes.get(s, 0.0) for s in symbols)
    by_votes = {s: votes.get(s, 0.0) / total if total > 0 else 1.0 / len(symbols) for s in symbols}
    if method == "votes" or len(symbols) == 1:
        return by_votes
    if method == "equal":
        return {s: 1.0 / len(symbols) for s in symbols}
    r = None if returns is None else _clean(returns)
    if r is None or r.ndim != 2 or len(r) < 10:
        return by_votes
    if method == "inverse_vol":
        w = inverse_vol_weights(r)
    elif method == "hrp":
        w = hrp_weights(r)
    else:
        raise ValueError(f"unknown weighting {method!r}; choose from {', '.join(METHODS)}")
    return dict(zip(symbols, map(float, w)))
