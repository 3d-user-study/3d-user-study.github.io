#!/usr/bin/env python3
"""Mean-of-samples aggregate ranking with paired-bootstrap 95% CI.

Input:  texture-study/analysis/pl_per_sample.csv  (output of fit_pl.py)
Output: texture-study/analysis/pl_aggregate.csv
        Columns: rank, method, mean_score, low_ci, high_ci, n_samples

Procedure
---------
The aggregate score for method m is the mean of its per-sample PL scores
across the N samples for which we have data. Confidence intervals come
from PAIRED bootstrap: at each iteration we resample SAMPLES with
replacement (NOT individual rankings -- that uncertainty is already
captured in fit_pl.py's per-sample CIs) and recompute every method's
mean from the resampled set. Resampling samples (rather than per-method
independently) preserves the within-sample correlation between methods,
which is the right CI for the question "if I ran this study on a
different draw of N samples, where would each method rank?".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

METHODS: list[str] = ["spotex", "goatex", "mvadapter", "TEXGen", "paint3d", "syncmvd"]
N_METHODS: int = len(METHODS)

BOOTSTRAP_ITER: int = 1000
CI_LOW: float = 2.5
CI_HIGH: float = 97.5


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pl_per_sample", type=Path,
                        default=Path("texture-study/analysis/pl_per_sample.csv"))
    parser.add_argument("--out_csv",       type=Path,
                        default=Path("texture-study/analysis/pl_aggregate.csv"))
    parser.add_argument("--bootstrap_iter", type=int, default=BOOTSTRAP_ITER)
    parser.add_argument("--seed",           type=int, default=2024)
    args = parser.parse_args()

    df = pd.read_csv(args.pl_per_sample)
    if df.empty:
        sys.exit(f"{args.pl_per_sample} is empty; run fit_pl.py first")

    samples = sorted(df["sample"].unique())
    n_samples = len(samples)

    score_mat = np.zeros((n_samples, N_METHODS))
    for i, s in enumerate(samples):
        sub = df[df["sample"] == s]
        for j, m in enumerate(METHODS):
            row = sub[sub["method"] == m]
            if row.empty:
                sys.exit(f"missing score for sample={s} method={m}")
            score_mat[i, j] = row["score"].iloc[0]

    mean_score = score_mat.mean(axis=0)

    rng = np.random.default_rng(args.seed)
    boot = np.empty((args.bootstrap_iter, N_METHODS))
    for b in range(args.bootstrap_iter):
        idx = rng.integers(0, n_samples, size=n_samples)
        boot[b] = score_mat[idx].mean(axis=0)

    low = np.percentile(boot, CI_LOW, axis=0)
    high = np.percentile(boot, CI_HIGH, axis=0)
    ranks = (-mean_score).argsort().argsort() + 1

    out = pd.DataFrame({
        "rank":       ranks,
        "method":     METHODS,
        "mean_score": mean_score,
        "low_ci":     low,
        "high_ci":    high,
        "n_samples":  n_samples,
    }).sort_values("rank").reset_index(drop=True)

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False, float_format="%.6f")

    print(out.to_string(index=False))
    print(f"\nWrote {args.out_csv} ({n_samples} samples)")


if __name__ == "__main__":
    main()
