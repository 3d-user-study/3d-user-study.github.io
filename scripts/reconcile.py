#!/usr/bin/env python3
"""Join MTurk results CSV with `scripts/aliasmap_full.json` and produce:

  - judgments.csv   one row per accepted real-trial vote (sample, methodL,
                    methodR, choice, workerId, hitId, assignmentId)
  - approvals.csv   AssignmentIds to approve in MTurk (vigilance >= 1.0
                    AND within --worker_cap)
  - rejections.csv  AssignmentIds to reject (vigilance < 1.0 OR exceeded
                    --worker_cap) plus rejection feedback string

CSV column expectations:

  - HITId, WorkerId, AssignmentId, AssignmentStatus
  - SubmitTime           used to determine "first submission" per worker
                         when --worker_cap is enabled; if unparseable we
                         fall back to AssignmentId as deterministic order
  - Answer.selection1..Answer.selection25 (each "a" or "b")
  - Answer.hitId         echoed by index.html submit form (== our H_0001..H_0240)
  - RequesterAnnotation  set by scripts/launch_hits.py (== our H_0001..H_0240)

Reconciliation rules (plan §1.2):
  1. Vigilance threshold = 1.0 (worker must get ALL 5 vigilance correct).
     Failures get the long REJECT_LINE matching APAP's wording.
  2. (Optional, --worker_cap N >= 1) Per-worker cap: among the
     vigilance-passing submissions, keep only the first N per workerId
     (sorted by SubmitTime, AssignmentId tiebreaker). The rest are demoted
     to rejection with REJECT_LINE_WORKER_CAP feedback.
     Default --worker_cap=0 disables this cap (preserves prior behavior).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

VIGILANCE_THRESHOLD = 1.0
N_TRIALS = 25
N_VIGILANCE = 5

REJECT_LINE = (
    "We would like to extend our deepest gratitude for your time and efforts "
    "taken to participate in our survey. However, the vigilance tests embedded "
    "within the survey are designed to ensure the accuracy and reliability of "
    "the data collected. These tests were unfortunately not passed with the "
    "necessary accuracy in your submission. With this in mind, we regret to "
    "inform you that we are unable to include your submission in our data set."
)

REJECT_LINE_WORKER_CAP = (
    "Thank you for your participation. To preserve the statistical validity "
    "of this study, our protocol limits the number of submissions counted per "
    "worker. Your earlier submission(s) have already been accepted; this "
    "additional submission falls outside the per-worker cap and we are unable "
    "to include it in our dataset."
)


def _resolve_hitid(row: dict[str, str]) -> str | None:
    """Pull our internal HitId out of the MTurk CSV row.

    Prefer `RequesterAnnotation` (set by launch_hits.py) over `Answer.hitId`
    (echoed via the form): the annotation is set server-side at HIT
    creation and cannot be tampered with by a malicious client.
    """
    for key in ("RequesterAnnotation", "Answer.hitId"):
        v = row.get(key)
        if v and v.startswith("H_"):
            return v
    return None


def _parse_submit_time(raw: str) -> float:
    """Best-effort parse of MTurk SubmitTime to float epoch seconds.

    Returns 0.0 if unparseable; AssignmentId is then used as the
    deterministic tiebreaker for "first submission" ordering.

    MTurk batch results commonly use "Tue Jan 03 12:34:56 PST 2023" but
    occasionally ISO-8601. We try ISO first, then the legacy format with
    timezone stripped (Python's %Z is unreliable across PST/PDT/EST/EDT).
    """
    if not raw:
        return 0.0
    s = raw.strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    parts = s.split()
    if len(parts) >= 6:
        # "Tue Jan 03 12:34:56 PST 2023" -> "Tue Jan 03 12:34:56 2023"
        no_tz = " ".join(parts[:4] + [parts[5]])
        try:
            return datetime.strptime(no_tz, "%a %b %d %H:%M:%S %Y").timestamp()
        except ValueError:
            pass
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results_csv", type=Path, required=True,
                        help="MTurk batch results CSV downloaded from console")
    parser.add_argument("--full_json",   type=Path,
                        default=Path("texture-study/scripts/aliasmap_full.json"))
    parser.add_argument("--out_dir",     type=Path,
                        default=Path("texture-study/analysis"))
    parser.add_argument("--worker_cap",  type=int, default=0,
                        help="Per-workerId cap on accepted submissions. "
                             "0 = disabled (default, matches sandbox-pilot "
                             "behavior). >=1 enables hard guarantee for "
                             "production: only the first N submissions per "
                             "workerId are approved; rest are rejected with "
                             "REJECT_LINE_WORKER_CAP. Recommended N=1.")
    args = parser.parse_args()

    if args.worker_cap < 0:
        sys.exit(f"--worker_cap must be >= 0 (got {args.worker_cap})")

    full_map = json.loads(args.full_json.read_text())

    args.out_dir.mkdir(parents=True, exist_ok=True)
    judgments_path  = args.out_dir / "judgments.csv"
    approvals_path  = args.out_dir / "approvals.csv"
    rejections_path = args.out_dir / "rejections.csv"
    summary_path    = args.out_dir / "reconcile_summary.txt"

    n_rows         = 0
    n_skipped      = 0
    n_rejected_vig = 0
    n_rejected_cap = 0
    vig_score_dist: Counter[int] = Counter()
    reasons: Counter[str] = Counter()

    # Pass 1: stream the CSV; write vigilance rejections immediately,
    # buffer vigilance-passing rows for the cap pass.
    pending_pass: list[dict] = []
    rejections_buf: list[list[str]] = []

    with args.results_csv.open(newline="") as f_in:
        reader = csv.DictReader(f_in)
        for row in reader:
            n_rows += 1
            status = row.get("AssignmentStatus", "")
            if status not in ("Submitted", "Approved", "Rejected"):
                n_skipped += 1
                reasons[f"status={status}"] += 1
                continue

            hit_id = _resolve_hitid(row)
            if not hit_id:
                n_skipped += 1
                reasons["no_hitid"] += 1
                continue

            blob = full_map.get(hit_id)
            if blob is None:
                n_skipped += 1
                reasons["unknown_hitid"] += 1
                continue

            assignment_id = row.get("AssignmentId", "")
            worker_id     = row.get("WorkerId", "")

            trials = blob["trials"]
            if len(trials) != N_TRIALS:
                n_skipped += 1
                reasons["bad_trial_count"] += 1
                continue

            selections: list[str] = []
            missing = False
            for t in trials:
                col = f"Answer.selection{t['i'] + 1}"
                v = (row.get(col) or "").strip().lower()
                if v not in ("a", "b"):
                    missing = True
                    break
                selections.append(v)
            if missing:
                n_skipped += 1
                reasons["missing_selections"] += 1
                continue

            correct = 0
            n_vig = 0
            for t in trials:
                if t["kind"] != "vigilance":
                    continue
                n_vig += 1
                if selections[t["i"]] == t["expected"]:
                    correct += 1
            if n_vig != N_VIGILANCE:
                n_skipped += 1
                reasons["bad_vig_count"] += 1
                continue

            vig_score_dist[correct] += 1
            score = correct / N_VIGILANCE

            if score < VIGILANCE_THRESHOLD:
                n_rejected_vig += 1
                rejections_buf.append([
                    assignment_id, worker_id, hit_id, f"{score:.2f}", REJECT_LINE,
                ])
                continue

            pending_pass.append({
                "assignment_id": assignment_id,
                "worker_id":     worker_id,
                "hit_id":        hit_id,
                "submit_time":   _parse_submit_time(row.get("SubmitTime", "")),
                "trials":        trials,
                "selections":    selections,
                "score":         score,
            })

    # Pass 2: apply per-worker cap among vigilance-passing rows.
    final_passes: list[dict] = []
    if args.worker_cap > 0:
        by_worker: dict[str, list[dict]] = defaultdict(list)
        for entry in pending_pass:
            by_worker[entry["worker_id"]].append(entry)
        for entries in by_worker.values():
            # Deterministic order: SubmitTime ascending, AssignmentId tiebreaker.
            entries.sort(key=lambda e: (e["submit_time"], e["assignment_id"]))
            kept = entries[:args.worker_cap]
            excess = entries[args.worker_cap:]
            final_passes.extend(kept)
            for e in excess:
                n_rejected_cap += 1
                rejections_buf.append([
                    e["assignment_id"], e["worker_id"], e["hit_id"], "n/a",
                    REJECT_LINE_WORKER_CAP,
                ])
    else:
        final_passes = pending_pass

    n_passed    = len(final_passes)
    n_judgments = 0

    with judgments_path.open("w", newline="") as f_jud:
        jud_writer = csv.writer(f_jud)
        jud_writer.writerow([
            "sample", "methodL", "methodR", "choice",
            "workerId", "hitId", "assignmentId", "trialIdx",
        ])
        for entry in final_passes:
            for t in entry["trials"]:
                if t["kind"] != "real":
                    continue
                sel = entry["selections"][t["i"]]
                choice = "L" if sel == "a" else "R"
                jud_writer.writerow([
                    t["sample"], t["methodL"], t["methodR"], choice,
                    entry["worker_id"], entry["hit_id"],
                    entry["assignment_id"], t["i"],
                ])
                n_judgments += 1

    with approvals_path.open("w", newline="") as f_app:
        app_writer = csv.writer(f_app)
        app_writer.writerow(["assignmentId", "workerId", "hitId"])
        for entry in final_passes:
            app_writer.writerow([
                entry["assignment_id"], entry["worker_id"], entry["hit_id"],
            ])

    with rejections_path.open("w", newline="") as f_rej:
        rej_writer = csv.writer(f_rej)
        rej_writer.writerow([
            "assignmentId", "workerId", "hitId", "vigilanceScore", "feedback",
        ])
        for r in rejections_buf:
            rej_writer.writerow(r)

    summary = [
        f"rows in CSV          : {n_rows}",
        f"skipped              : {n_skipped}  ({dict(reasons)})",
        f"passed vigilance     : {len(pending_pass)}",
        f"  -> approved (final): {n_passed}",
        f"  -> rejected by cap : {n_rejected_cap}  (--worker_cap={args.worker_cap})",
        f"rejected (vig<1.0)   : {n_rejected_vig}",
        f"real judgments emit  : {n_judgments}",
        f"vigilance histogram  : {dict(sorted(vig_score_dist.items()))}",
        f"-> judgments  -> {judgments_path}",
        f"-> approvals  -> {approvals_path}",
        f"-> rejections -> {rejections_path}",
    ]
    summary_path.write_text("\n".join(summary) + "\n")
    print("\n".join(summary))

    if n_rows == 0:
        sys.exit("No rows processed; is --results_csv correct?")


if __name__ == "__main__":
    main()
