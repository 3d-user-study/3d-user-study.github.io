#!/usr/bin/env python3
"""Generate trial map (public) and offline reconciliation map for the GitHub
Pages static-host architecture.

Outputs (driven by `--seed`, default 2024 per plan):

  texture-study/docs/trialMap.json          PUBLIC (fetched by client)
                                            Record<HitId, ClientTrialSpec[]>
                                            ClientTrialSpec: {i, kind, dirL, dirR, vig?}
                                            NO method names. NO sample id.
                                            NO `expected`. NO aliases.

  texture-study/scripts/aliasmap_full.json  OFFLINE (.gitignored)
                                            Method-aware data for reconciler.
                                            Filename retained for backward
                                            compatibility with reconcile.py
                                            and launch_hits.py.

The two files are emitted from a single in-memory state; consistency
assertions block the run on any mismatch.

Under GH Pages there is no server-side alias rewriting. Each (sample, method)
pair has been pre-renamed to `{sample}/{hash16}` by dehydrate_meshes.py. The
public trial map ships those opaque dirs; an adversary without the salt
cannot recover method names from URLs OR JSON.

Residual risk (acknowledged): the same hash means the same (sample, method)
across HITs, so an attacker can cluster votes by hash within sample. They
still cannot name the method without the private salt + method_hash_map.json.

H_TUTORIAL is a reserved hitId emitted alongside the production HITs.
launch_hits.py filters it out via RESERVED_HITIDS.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

METHODS: list[str] = ["spotex", "goatex", "mvadapter", "TEXGen", "paint3d", "syncmvd"]
TUTORIAL_HITID: str = "H_TUTORIAL"


def _dir_for(sample: str, method: str, hash_map: dict[str, dict[str, str]]) -> str:
    h = hash_map[sample][method]
    return f"{sample}/{h}"


def _greedy_pick(
    rng: random.Random,
    cov: dict[tuple[str, frozenset[str]], int],
    samples: list[str],
    pairs: list[frozenset[str]],
    n: int,
) -> list[tuple[str, frozenset[str]]]:
    universe = [(s, p) for s in samples for p in pairs]
    rng.shuffle(universe)
    universe.sort(key=lambda sp: cov[sp])
    return universe[:n]


def _build_real_trials(
    rng: random.Random,
    cells: list[tuple[str, frozenset[str]]],
    hash_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sample, pair in cells:
        m1, m2 = list(pair)
        if rng.random() < 0.5:
            method_l, method_r = m1, m2
        else:
            method_l, method_r = m2, m1
        out.append({
            "kind": "real",
            "sample": sample,
            "methodL": method_l,
            "methodR": method_r,
            "dirL": _dir_for(sample, method_l, hash_map),
            "dirR": _dir_for(sample, method_r, hash_map),
        })
    return out


def _build_vig_trials(
    rng: random.Random,
    samples: list[str],
    n: int,
    hash_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _ in range(n):
        s = rng.choice(samples)
        method = rng.choice(METHODS)
        side: str = rng.choice(["L", "R"])
        d = _dir_for(s, method, hash_map)
        expected: str = "b" if side == "L" else "a"
        out.append({
            "kind": "vigilance",
            "sample": s,
            "methodL": method,
            "methodR": method,
            "dirL": d,
            "dirR": d,
            "vig": side,
            "expected": expected,
        })
    return out


def _client_view(t: dict[str, Any]) -> dict[str, Any]:
    keys: tuple[str, ...] = ("kind", "dirL", "dirR")
    out: dict[str, Any] = {k: t[k] for k in keys}
    if "vig" in t:
        out["vig"] = t["vig"]
    return out


def _emit_trial_json(full_map: dict[str, dict[str, Any]], path: Path) -> None:
    public_map: dict[str, list[dict[str, Any]]] = {}
    for hid, blob in full_map.items():
        public_map[hid] = [
            {"i": t["i"], **_client_view(t)} for t in blob["trials"]
        ]
    path.write_text(json.dumps(public_map, indent=2), encoding="utf-8")


def _emit_full_json(full_map: dict[str, dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(full_map, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_hits", type=int, default=240)
    parser.add_argument("--n_real", type=int, default=20)
    parser.add_argument("--n_vigilance", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2024)
    parser.add_argument(
        "--viewer_index",
        type=Path,
        default=Path("/Users/kkh4022/Workspace/SPOTex/portable_viewer/data/viewer_index.json"),
    )
    parser.add_argument(
        "--method_hash_map",
        type=Path,
        default=Path("texture-study/scripts/method_hash_map.json"),
        help="PRIVATE map written by dehydrate_meshes.py: {sample: {method: hash16}}",
    )
    parser.add_argument("--out_trial_json", type=Path, default=Path("texture-study/docs/trialMap.json"))
    parser.add_argument("--out_full_json",  type=Path, default=Path("texture-study/scripts/aliasmap_full.json"))
    args = parser.parse_args()

    rng = random.Random(args.seed)

    samples: list[str] = json.loads(args.viewer_index.read_text())["samples"]
    if not samples:
        raise SystemExit("viewer_index.json has no samples")

    hash_map: dict[str, dict[str, str]] = json.loads(args.method_hash_map.read_text())
    missing_samples = [s for s in samples if s not in hash_map]
    if missing_samples:
        raise SystemExit(f"method_hash_map missing {len(missing_samples)} samples: {missing_samples[:3]}")
    for s in samples:
        for m in METHODS:
            if m not in hash_map[s]:
                raise SystemExit(f"method_hash_map[{s}] missing method '{m}'")

    pairs: list[frozenset[str]] = [frozenset(p) for p in combinations(METHODS, 2)]
    assert len(pairs) == 15, f"expected 15 method pairs, got {len(pairs)}"

    cov: dict[tuple[str, frozenset[str]], int] = defaultdict(int)
    full_map: dict[str, dict[str, Any]] = {}

    for i in range(args.n_hits):
        hid = f"H_{i + 1:04d}"

        cells = _greedy_pick(rng, cov, samples, pairs, args.n_real)
        for sp in cells:
            cov[sp] += 1

        real = _build_real_trials(rng, cells, hash_map)
        vig  = _build_vig_trials(rng, samples, args.n_vigilance, hash_map)
        trials = real + vig
        rng.shuffle(trials)
        for idx, t in enumerate(trials):
            t["i"] = idx

        full_map[hid] = {"trials": trials}

    tut_sample = samples[0]
    tut_m1, tut_m2 = METHODS[0], METHODS[1]
    tut_trial = {
        "i": 0,
        "kind": "real",
        "sample": tut_sample,
        "methodL": tut_m1,
        "methodR": tut_m2,
        "dirL": _dir_for(tut_sample, tut_m1, hash_map),
        "dirR": _dir_for(tut_sample, tut_m2, hash_map),
    }
    full_map[TUTORIAL_HITID] = {"trials": [tut_trial]}

    args.out_trial_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_full_json.parent.mkdir(parents=True, exist_ok=True)

    _emit_trial_json(full_map, args.out_trial_json)
    _emit_full_json(full_map, args.out_full_json)

    production_hits: set[str] = {f"H_{i + 1:04d}" for i in range(args.n_hits)}
    reserved: set[str] = {TUTORIAL_HITID}
    all_hits = production_hits | reserved

    trial_map = json.loads(args.out_trial_json.read_text())
    full_check = json.loads(args.out_full_json.read_text())
    raw_trial_text = args.out_trial_json.read_text()

    assert set(trial_map.keys()) == all_hits, (
        f"trialMap key mismatch: {set(trial_map) - all_hits} / {all_hits - set(trial_map)}"
    )
    assert set(full_check.keys()) == all_hits, "fullMap key mismatch"
    assert '"H_TEST"' not in raw_trial_text, "H_TEST stub leaked into trialMap"

    assert len(trial_map[TUTORIAL_HITID]) == 1, "tutorial must have exactly 1 trial"
    for hid in production_hits:
        assert len(trial_map[hid]) == 25, f"{hid} has {len(trial_map[hid])} trials, expected 25"

    forbidden_keys = {"sample", "methodL", "methodR", "expected", "aliasL", "aliasR"}
    for m in METHODS:
        assert m not in raw_trial_text, (
            f"INVARIANT #2 VIOLATED: method '{m}' appears in {args.out_trial_json}"
        )
    for hid, trials in trial_map.items():
        for t in trials:
            for fk in forbidden_keys:
                assert fk not in t, (
                    f"INVARIANT #2 VIOLATED: forbidden key '{fk}' in trialMap[{hid}].i={t['i']}"
                )

    for hid, blob in full_check.items():
        for t in blob["trials"]:
            for side in ("L", "R"):
                method = t[f"method{side}"]
                expected_dir = _dir_for(t["sample"], method, hash_map)
                actual_dir = t[f"dir{side}"]
                assert actual_dir == expected_dir, (
                    f"dir mismatch {hid}.i={t['i']}.{side}: {actual_dir} != {expected_dir}"
                )

    for hid in all_hits:
        for t in full_check[hid]["trials"]:
            cv = {"i": t["i"], **_client_view(t)}
            assert cv in trial_map[hid], f"client_view drift for {hid}.i={t['i']}"

    print(f"OK: {len(all_hits)} entries ({len(production_hits)} production + 1 tutorial)")
    print(f"  trial.json -> {args.out_trial_json}")
    print(f"  full.json  -> {args.out_full_json}")
    print(f"  coverage   -> {sum(cov.values())} cell-votes across {len(cov)} cells")


if __name__ == "__main__":
    main()
