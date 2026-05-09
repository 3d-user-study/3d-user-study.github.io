#!/usr/bin/env python3
"""Per-sample Bradley-Terry MLE fit with 1000-iter bootstrap 95% CI.

Input:  texture-study/analysis/judgments.csv
        (sample, methodL, methodR, choice in {L,R}, workerId, hitId,
         assignmentId, trialIdx) -- emitted by scripts/reconcile.py.

Output: texture-study/analysis/bt_per_sample.csv
        Columns: sample, method, score, low_ci, high_ci, rank, n_judgments
        - score:  softmax(BT log-strengths), sums to 1.0 per sample.
        - low_ci, high_ci: 2.5 / 97.5 percentile of bootstrap distribution.
        - rank: 1 = highest score within that sample.

For each sample we
  1. build the list of (winner_idx, loser_idx) pairs from `judgments.csv`,
  2. fit BT once via choix.ilsr_pairwise (point estimate),
  3. bootstrap the pair list with replacement BOOTSTRAP_ITER times and
     refit each draw,
  4. take 2.5 / 97.5 percentiles per method as the 95% CI.

A small alpha regularizes both the point fit and bootstrap refits, which
keeps choix stable even when a bootstrap draw produces a disconnected
comparison graph.
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
BT_ALPHA: float = 1e-3


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def _fit_one(pairs: list[tuple[int, int]]) -> np.ndarray:
    if not pairs:
        return np.full(N_METHODS, 1.0 / N_METHODS)
    try:
        params = choix.ilsr_pairwise(N_METHODS, pairs, alpha=BT_ALPHA)
    except (RuntimeError, np.linalg.LinAlgError):
        params = choix.lsr_pairwise(N_METHODS, pairs, alpha=BT_ALPHA)
    return _softmax(np.asarray(params))


def _pairs_for_sample(sub: pd.DataFrame) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for r in sub.itertuples(index=False):
        m_l: str = r.methodL
        m_r: str = r.methodR
        if m_l not in METHOD_TO_IDX or m_r not in METHOD_TO_IDX:
            continue
        l_idx = METHOD_TO_IDX[m_l]
        r_idx = METHOD_TO_IDX[m_r]
        if r.choice == "L":
            out.append((l_idx, r_idx))
        elif r.choice == "R":
            out.append((r_idx, l_idx))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judgments", type=Path,
                        default=Path("texture-study/analysis/judgments.csv"))
    parser.add_argument("--out_csv",   type=Path,
                        default=Path("texture-study/analysis/bt_per_sample.csv"))
    parser.add_argument("--bootstrap_iter", type=int, default=BOOTSTRAP_ITER)
    parser.add_argument("--seed",           type=int, default=2024)
    args = parser.parse_args()

    df = pd.read_csv(args.judgments)
    if df.empty:
        sys.exit(f"{args.judgments} is empty; run reconcile.py first")

    rng = np.random.default_rng(args.seed)
    samples = sorted(df["sample"].unique())

    rows: list[dict[str, object]] = []
    skipped: list[str] = []
    for sample in samples:
        sub = df[df["sample"] == sample]
        pairs = _pairs_for_sample(sub)
        n = len(pairs)
        if n == 0:
            skipped.append(sample)
            continue

        point = _fit_one(pairs)

        boot = np.empty((args.bootstrap_iter, N_METHODS))
        pairs_arr = np.asarray(pairs, dtype=np.int64)
        for b in range(args.bootstrap_iter):
            idx = rng.integers(0, n, size=n)
            resamp = [(int(w), int(l)) for w, l in pairs_arr[idx]]
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
                "n_judgments": n,
            })

    out = pd.DataFrame(rows, columns=[
        "sample", "method", "score", "low_ci", "high_ci", "rank", "n_judgments",
    ])
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False, float_format="%.6f")

    n_done = len(samples) - len(skipped)
    print(f"BT fit complete: {n_done} samples ({len(rows)} rows) -> {args.out_csv}")
    if skipped:
        print(f"  skipped (no judgments): {skipped}")


if __name__ == "__main__":
    main()
