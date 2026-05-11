#!/usr/bin/env python3
"""Per-sample Plackett-Luce MLE fit with 1000-iter bootstrap 95% CI.

Input:  texture-study/analysis/rankings.csv
        (sample, kind, m_rank1..m_rank6, workerId, hitId, assignmentId,
         trialIdx) -- emitted by scripts/reconcile.py. m_rankK is the
        method NAME placed at rank K by the worker (1 = best, 6 = worst).

Output: texture-study/analysis/pl_per_sample.csv
        Columns: sample, method, score, low_ci, high_ci, rank, n_rankings
        - score:  softmax(PL log-strengths), sums to 1.0 per sample.
        - low_ci, high_ci: 2.5 / 97.5 percentile of bootstrap distribution.
        - rank: 1 = highest score within that sample.

For each sample we
  1. build the list of full rankings (lists of method indices in
     best-to-worst order) from `rankings.csv`,
  2. fit Plackett-Luce once via choix.ilsr_rankings (point estimate),
  3. bootstrap the ranking list with replacement BOOTSTRAP_ITER times
     and refit each draw,
  4. take 2.5 / 97.5 percentiles per method as the 95% CI.

Only `kind == 'main'` rankings are used. Vigilance rankings are
degenerate under the current vigilance design (5 `_corrupt_K` bait
slots + 1 `spotex` target, with the pass criterion forcing spotex to
rank 1) and carry no PL signal, so reconcile.py emits them for audit
but fit_pl.py ignores them.

A small alpha regularizes both the point fit and bootstrap refits, which
keeps choix stable even when a bootstrap draw produces a disconnected
comparison graph (e.g. all rankings happen to share a fixed top method).
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--rankings", type=Path,
                        default=Path("texture-study/analysis/rankings.csv"))
    parser.add_argument("--out_csv",  type=Path,
                        default=Path("texture-study/analysis/pl_per_sample.csv"))
    parser.add_argument("--bootstrap_iter", type=int, default=BOOTSTRAP_ITER)
    parser.add_argument("--seed",           type=int, default=2024)
    args = parser.parse_args()

    df = pd.read_csv(args.rankings)
    if df.empty:
        sys.exit(f"{args.rankings} is empty; run reconcile.py first")

    rng = np.random.default_rng(args.seed)
    samples = sorted(df["sample"].unique())

    rows: list[dict[str, object]] = []
    skipped: list[str] = []
    for sample in samples:
        sub = df[df["sample"] == sample]
        rankings: list[tuple[int, ...]] = []
        for _, r in sub.iterrows():
            ranking = _row_to_ranking(r)
            if ranking is not None:
                rankings.append(ranking)
        n = len(rankings)
        if n == 0:
            skipped.append(sample)
            continue

        point = _fit_one(rankings)

        boot = np.empty((args.bootstrap_iter, N_METHODS))
        for b in range(args.bootstrap_iter):
            idx = rng.integers(0, n, size=n)
            resamp = [rankings[i] for i in idx]
            boot[b] = _fit_one(resamp)

        low = np.percentile(boot, CI_LOW, axis=0)
        high = np.percentile(boot, CI_HIGH, axis=0)
        ranks = (-point).argsort().argsort() + 1

        for i, m in enumerate(METHODS):
            rows.append({
                "sample":      sample,
                "method":      m,
                "score":       float(point[i]),
                "low_ci":      float(low[i]),
                "high_ci":     float(high[i]),
                "rank":        int(ranks[i]),
                "n_rankings":  n,
            })

    out = pd.DataFrame(rows, columns=[
        "sample", "method", "score", "low_ci", "high_ci", "rank", "n_rankings",
    ])
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False, float_format="%.6f")

    n_done = len(samples) - len(skipped)
    print(f"PL fit complete: {n_done} samples ({len(rows)} rows) -> {args.out_csv}")
    if skipped:
        print(f"  skipped (no rankings): {skipped}")


if __name__ == "__main__":
    main()
