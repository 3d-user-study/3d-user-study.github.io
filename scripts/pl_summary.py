#!/usr/bin/env python3
"""Method-level Plackett-Luce summary combining per-sample stats with a pooled fit.

Input:  --rankings        analysis/<bucket>/rankings.csv      (from reconcile.py)
        --pl_per_sample   analysis/<bucket>/pl_per_sample.csv (from fit_pl.py)
Output: --out_csv         analysis/<bucket>/pl_method_summary.csv

Output columns (one row per method):
  method, mean_score, mean_rank, n_wins, n_last,
  pooled_score, pooled_low_ci, pooled_high_ci, pooled_rank

  - mean_score / mean_rank: arithmetic mean across samples of fit_pl.py's
    per-sample score / rank.
  - n_wins: count of samples where this method's per-sample rank == 1.
  - n_last: count of samples where this method's per-sample rank == 6.
  - pooled_score: softmax of a single Plackett-Luce fit over ALL `main`
    rankings pooled across samples (one global preference vector, not a
    per-sample mean). This is the headline number for "if we treat every
    main ranking as one sample of a global user preference, which method
    wins?". CIs come from 1000-iter bootstrap of the pooled ranking
    list (resample rankings with replacement, refit).
  - pooled_rank: 1 = highest pooled_score.

Only `kind == 'main'` rankings are used (consistent with fit_pl.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import choix
import numpy as np
import pandas as pd

METHODS: list[str] = ["spotex", "goatex", "mvadapter", "TEXGen", "paint3d", "syncmvd"]
METHOD_TO_IDX: dict[str, int] = {m: i for i, m in enumerate(METHODS)}
N_METHODS: int = len(METHODS)
BOOTSTRAP_ITER: int = 1000
CI_LOW: float = 2.5
CI_HIGH: float = 97.5
PL_ALPHA: float = 1e-3
RANK_COLS: list[str] = [f"m_rank{k}" for k in range(1, N_METHODS + 1)]


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def _fit_one(rankings: list[tuple[int, ...]]) -> np.ndarray:
    if not rankings:
        return np.full(N_METHODS, 1.0 / N_METHODS)
    try:
        params = choix.ilsr_rankings(N_METHODS, rankings, alpha=PL_ALPHA)
    except (RuntimeError, np.linalg.LinAlgError):
        params = choix.lsr_rankings(N_METHODS, rankings, alpha=PL_ALPHA)
    return _softmax(np.asarray(params))


def _row_to_ranking(row: pd.Series) -> tuple[int, ...] | None:
    if row["kind"] != "main":
        return None
    out: list[int] = []
    for col in RANK_COLS:
        m = row[col]
        if m not in METHOD_TO_IDX:
            return None
        out.append(METHOD_TO_IDX[m])
    if len(set(out)) != N_METHODS:
        return None
    return tuple(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--rankings",      type=Path, required=True)
    p.add_argument("--pl_per_sample", type=Path, required=True)
    p.add_argument("--out_csv",       type=Path, required=True)
    p.add_argument("--bootstrap_iter", type=int, default=BOOTSTRAP_ITER)
    p.add_argument("--seed",           type=int, default=2024)
    args = p.parse_args()

    per = pd.read_csv(args.pl_per_sample)
    if per.empty:
        sys.exit(f"{args.pl_per_sample} is empty; run fit_pl.py first")
    agg = per.groupby("method", sort=False).agg(
        mean_score=("score", "mean"),
        mean_rank=("rank",  "mean"),
        n_wins   =("rank",  lambda s: int((s == 1).sum())),
        n_last   =("rank",  lambda s: int((s == N_METHODS).sum())),
    ).reset_index()

    df = pd.read_csv(args.rankings)
    if df.empty:
        sys.exit(f"{args.rankings} is empty; run reconcile.py first")

    rankings: list[tuple[int, ...]] = []
    for _, r in df.iterrows():
        rk = _row_to_ranking(r)
        if rk is not None:
            rankings.append(rk)
    if not rankings:
        sys.exit("No main rankings found in --rankings")

    point = _fit_one(rankings)

    rng = np.random.default_rng(args.seed)
    n = len(rankings)
    boot = np.empty((args.bootstrap_iter, N_METHODS))
    for b in range(args.bootstrap_iter):
        idx = rng.integers(0, n, size=n)
        boot[b] = _fit_one([rankings[i] for i in idx])
    low = np.percentile(boot, CI_LOW, axis=0)
    high = np.percentile(boot, CI_HIGH, axis=0)
    pooled_rank = (-point).argsort().argsort() + 1

    pooled = pd.DataFrame({
        "method":         METHODS,
        "pooled_score":   point,
        "pooled_low_ci":  low,
        "pooled_high_ci": high,
        "pooled_rank":    pooled_rank,
    })

    out = agg.merge(pooled, on="method", how="outer")
    out = out.sort_values("pooled_rank").reset_index(drop=True)
    out = out[[
        "method", "mean_score", "mean_rank", "n_wins", "n_last",
        "pooled_score", "pooled_low_ci", "pooled_high_ci", "pooled_rank",
    ]]
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False, float_format="%.6f")
    print(f"pl_summary: {n} pooled rankings, {len(METHODS)} methods -> {args.out_csv}")


if __name__ == "__main__":
    main()
