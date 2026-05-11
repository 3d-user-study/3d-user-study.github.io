#!/usr/bin/env python3
"""Generate trial map (public) and offline reconciliation map for the GitHub
Pages static-host architecture, RANKING variant.

Outputs (driven by `--seed`, default 2024):

  texture-study/docs/trialMap.json          PUBLIC (fetched by client)
                                            Record<HitId, ClientTrialSpec[]>
                                            ClientTrialSpec:
                                              {i, prompt, slots[6]}
                                            slots[k] = {slot: 'A'..'F', dir: str}
                                            NO method names. NO `kind`.
                                            NO `target_slot`.

  texture-study/scripts/aliasmap_full.json  OFFLINE (.gitignored)
                                            Method-aware data for reconciler.
                                            Adds {sample, kind, slots[k].method,
                                            target_slot?} per trial.

Both files emit from one in-memory state; consistency assertions block on any
mismatch. Each main trial = full rank of all 6 real methods for 1 sample.
Each vigilance trial = N_CORRUPTS broken-texture meshes (`_corrupt_0`..
`_corrupt_{N-1}`, all sharing the donor's OBJ topology so they render as the
prompted object but with obviously-broken random-noise textures) plus 1
real `spotex` mesh. The worker must rank the spotex slot FIRST. Public
schema makes vigilance and main indistinguishable to the client.

H_TUTORIAL is reserved; launch_hits.py filters it via RESERVED_HITIDS.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

METHODS: list[str] = ["spotex", "goatex", "mvadapter", "TEXGen", "paint3d", "syncmvd"]
TARGET_METHOD: str = "spotex"
N_CORRUPTS: int = 5
CORRUPT_METHODS: list[str] = [f"_corrupt_{k}" for k in range(N_CORRUPTS)]
SLOTS: list[str] = ["A", "B", "C", "D", "E", "F"]
TUTORIAL_HITID: str = "H_TUTORIAL"
assert TARGET_METHOD in METHODS
assert len(CORRUPT_METHODS) + 1 == len(SLOTS)


def _dir_for(sample: str, method: str, hash_map: dict[str, dict[str, str]]) -> str:
    h = hash_map[sample][method]
    return f"{sample}/{h}"


def _load_prompt(captions_root: Path, sample: str) -> dict[str, Any]:
    src = captions_root / sample / "caption.json"
    if not src.is_file():
        raise SystemExit(f"caption.json missing for sample {sample}: {src}")
    raw = json.loads(src.read_text())
    full = raw.get("FULL")
    if not isinstance(full, str) or not full:
        raise SystemExit(f"caption.json[{sample}] missing 'FULL' field")
    parts: list[dict[str, str]] = []
    for k, v in raw.items():
        if k in ("OBJECT", "FULL") or not isinstance(v, str):
            continue
        parts.append({"label": k, "caption": v})
    return {"FULL": full, "parts": parts}


def _build_main_trial(
    rng: random.Random,
    sample: str,
    prompt: dict[str, Any],
    hash_map: dict[str, dict[str, str]],
) -> dict[str, Any]:
    methods = list(METHODS)
    rng.shuffle(methods)
    slots_full: list[dict[str, str]] = []
    for slot, method in zip(SLOTS, methods):
        slots_full.append({
            "slot": slot,
            "method": method,
            "dir": _dir_for(sample, method, hash_map),
        })
    return {
        "kind": "main",
        "sample": sample,
        "prompt": prompt,
        "slots": slots_full,
    }


def _build_vig_trial(
    rng: random.Random,
    sample: str,
    prompt: dict[str, Any],
    hash_map: dict[str, dict[str, str]],
) -> dict[str, Any]:
    entries = list(CORRUPT_METHODS) + [TARGET_METHOD]
    rng.shuffle(entries)
    slots_full: list[dict[str, str]] = []
    target_slot: str | None = None
    for slot, method in zip(SLOTS, entries):
        slots_full.append({
            "slot": slot,
            "method": method,
            "dir": _dir_for(sample, method, hash_map),
        })
        if method == TARGET_METHOD:
            target_slot = slot
    if target_slot is None:
        raise AssertionError("vigilance trial must have a target slot")
    return {
        "kind": "vigilance",
        "sample": sample,
        "prompt": prompt,
        "slots": slots_full,
        "target_slot": target_slot,
    }


def _client_view(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "i": t["i"],
        "prompt": t["prompt"],
        "slots": [{"slot": s["slot"], "dir": s["dir"]} for s in t["slots"]],
    }


def _emit_trial_json(full_map: dict[str, dict[str, Any]], path: Path) -> None:
    public_map: dict[str, list[dict[str, Any]]] = {}
    for hid, blob in full_map.items():
        public_map[hid] = [_client_view(t) for t in blob["trials"]]
    path.write_text(json.dumps(public_map, indent=2), encoding="utf-8")


def _emit_full_json(full_map: dict[str, dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(full_map, indent=2), encoding="utf-8")


def _greedy_pick_samples(
    rng: random.Random,
    cov: dict[str, int],
    samples: list[str],
    n: int,
) -> list[str]:
    pool = list(samples)
    rng.shuffle(pool)
    pool.sort(key=lambda s: cov[s])
    return pool[:n]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_hits", type=int, default=36)
    parser.add_argument("--n_main", type=int, default=20)
    parser.add_argument("--n_vigilance", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2024)
    parser.add_argument(
        "--viewer_index",
        type=Path,
        default=Path("/Users/kkh4022/Workspace/SPOTex/portable_viewer/data/viewer_index.json"),
    )
    parser.add_argument(
        "--captions_root",
        type=Path,
        default=Path("/Users/kkh4022/Workspace/SPOTex/portable_viewer/data"),
        help="root containing {sample}/caption.json files",
    )
    parser.add_argument(
        "--method_hash_map",
        type=Path,
        default=Path("texture-study/scripts/method_hash_map.json"),
        help="PRIVATE map written by dehydrate_meshes.py: "
             "{sample: {method-or-_corrupt: hash16}}",
    )
    parser.add_argument("--out_trial_json", type=Path, default=Path("texture-study/docs/trialMap.json"))
    parser.add_argument("--out_full_json", type=Path, default=Path("texture-study/scripts/aliasmap_full.json"))
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
        for m in METHODS + CORRUPT_METHODS:
            if m not in hash_map[s]:
                raise SystemExit(f"method_hash_map[{s}] missing entry '{m}'")

    prompts: dict[str, dict[str, Any]] = {s: _load_prompt(args.captions_root, s) for s in samples}

    cov: dict[str, int] = defaultdict(int)
    full_map: dict[str, dict[str, Any]] = {}

    for i in range(args.n_hits):
        hid = f"H_{i + 1:04d}"

        chosen = _greedy_pick_samples(rng, cov, samples, args.n_main)
        for s in chosen:
            cov[s] += 1

        main_trials: list[dict[str, Any]] = [
            _build_main_trial(rng, s, prompts[s], hash_map) for s in chosen
        ]
        vig_trials: list[dict[str, Any]] = [
            _build_vig_trial(rng, rng.choice(samples), prompts[rng.choice(samples)], hash_map)
            for _ in range(args.n_vigilance)
        ]
        for v in vig_trials:
            v["prompt"] = prompts[v["sample"]]

        trials = main_trials + vig_trials
        rng.shuffle(trials)
        for idx, t in enumerate(trials):
            t["i"] = idx

        full_map[hid] = {"trials": trials}

    tut_sample = samples[0]
    tut_main = _build_main_trial(rng, tut_sample, prompts[tut_sample], hash_map)
    tut_main["i"] = 0
    full_map[TUTORIAL_HITID] = {"trials": [tut_main]}

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

    expected_trial_count = args.n_main + args.n_vigilance
    assert len(trial_map[TUTORIAL_HITID]) == 1, "tutorial must have exactly 1 trial"
    for hid in production_hits:
        assert len(trial_map[hid]) == expected_trial_count, (
            f"{hid} has {len(trial_map[hid])} trials, expected {expected_trial_count}"
        )

    forbidden_keys = {"sample", "method", "kind", "corrupt_slot", "target_slot"}
    for hid, trials in trial_map.items():
        for t in trials:
            for fk in forbidden_keys:
                assert fk not in t, (
                    f"INVARIANT #2 VIOLATED: forbidden top-level key '{fk}' in trialMap[{hid}].i={t['i']}"
                )
            assert isinstance(t.get("slots"), list) and len(t["slots"]) == 6, (
                f"trialMap[{hid}].i={t['i']} must have slots[6]"
            )
            for s in t["slots"]:
                assert set(s.keys()) == {"slot", "dir"}, (
                    f"INVARIANT #2 VIOLATED: slot keys {sorted(s.keys())} in trialMap[{hid}].i={t['i']}"
                )

    for m in METHODS:
        assert m not in raw_trial_text, (
            f"INVARIANT #2 VIOLATED: method '{m}' appears in {args.out_trial_json}"
        )
    for cm in CORRUPT_METHODS:
        assert cm not in raw_trial_text, (
            f"INVARIANT #2 VIOLATED: '{cm}' appears in {args.out_trial_json}"
        )
    assert "_corrupt" not in raw_trial_text, (
        f"INVARIANT #2 VIOLATED: '_corrupt' substring appears in {args.out_trial_json}"
    )

    for hid, blob in full_check.items():
        for t in blob["trials"]:
            for s in t["slots"]:
                expected_dir = _dir_for(t["sample"], s["method"], hash_map)
                assert s["dir"] == expected_dir, (
                    f"dir mismatch {hid}.i={t['i']}.{s['slot']}: {s['dir']} != {expected_dir}"
                )
            slot_letters = sorted(s["slot"] for s in t["slots"])
            assert slot_letters == SLOTS, f"slot letters {slot_letters} != {SLOTS}"
            methods_in_trial = [s["method"] for s in t["slots"]]
            if t["kind"] == "main":
                assert sorted(methods_in_trial) == sorted(METHODS), (
                    f"main trial {hid}.i={t['i']} must contain all 6 methods, got {methods_in_trial}"
                )
                assert "target_slot" not in t, "main trial must not have target_slot"
                assert "corrupt_slot" not in t, "main trial must not have corrupt_slot"
            else:
                assert methods_in_trial.count(TARGET_METHOD) == 1, (
                    f"vigilance {hid}.i={t['i']} must have exactly 1 target ({TARGET_METHOD}) slot"
                )
                assert sorted(m for m in methods_in_trial if m != TARGET_METHOD) == sorted(CORRUPT_METHODS), (
                    f"vigilance {hid}.i={t['i']} non-target slots must be all {N_CORRUPTS} CORRUPT_METHODS, "
                    f"got {sorted(m for m in methods_in_trial if m != TARGET_METHOD)}"
                )
                ts = t["target_slot"]
                ts_method = next(s["method"] for s in t["slots"] if s["slot"] == ts)
                assert ts_method == TARGET_METHOD, (
                    f"target_slot {ts} in {hid}.i={t['i']} does not point at {TARGET_METHOD}"
                )

    for hid in all_hits:
        for t in full_check[hid]["trials"]:
            cv = _client_view(t)
            assert cv in trial_map[hid], f"client_view drift for {hid}.i={t['i']}"

    n_main_total = sum(1 for hid in production_hits for t in full_check[hid]["trials"] if t["kind"] == "main")
    n_vig_total = sum(1 for hid in production_hits for t in full_check[hid]["trials"] if t["kind"] == "vigilance")
    print(f"OK: {len(all_hits)} entries ({len(production_hits)} production + 1 tutorial)")
    print(f"  trial.json -> {args.out_trial_json}")
    print(f"  full.json  -> {args.out_full_json}")
    print(f"  main coverage  -> {n_main_total} main trials across {len(cov)} samples "
          f"(min={min(cov.values()) if cov else 0}, max={max(cov.values()) if cov else 0})")
    print(f"  vigilance      -> {n_vig_total} trials")


if __name__ == "__main__":
    main()
