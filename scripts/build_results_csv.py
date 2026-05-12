#!/usr/bin/env python3
"""Convert AWS MTurk `list-assignments-for-hit` JSON to the batch-results
CSV shape expected by `reconcile.py`.

This is the offline alternative to downloading the "Results" CSV from
the Requester UI. Useful when you want to drive reconciliation directly
off the AWS CLI / boto3 path without manual UI download.

Inputs:
  --in_json     output of `aws mturk list-assignments-for-hit ... --output json`
                (Assignments[].{AssignmentId,WorkerId,HITId,AssignmentStatus,
                 AcceptTime,SubmitTime,AutoApprovalTime,Answer}).
                If multiple HITs are involved, pass a JSON whose top-level
                key is `Assignments` with rows from any number of HITs.
  --launch_log  scripts/launch_log.csv produced by launch_hits.py;
                provides the mturkHitId -> hitId (H_NNNN) mapping that
                becomes `RequesterAnnotation` on each output row.

Output:
  --out_csv     batch-results-shaped CSV. Columns:
                HITId, RequesterAnnotation, WorkerId, AssignmentId,
                AssignmentStatus, AcceptTime, SubmitTime, AutoApprovalTime,
                Answer.workerId, Answer.hitId, Answer.rank1..Answer.rank25

`Answer.hitId` is set to the same H_NNNN as RequesterAnnotation so
reconcile.py's defense-in-depth (server-side annotation preferred over
form echo) still works.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"q": "http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2005-10-01/QuestionFormAnswers.xsd"}
N_RANKS = 25
RANK_COLS = [f"Answer.rank{i}" for i in range(1, N_RANKS + 1)]
PASS_THROUGH_COLS = [
    "HITId", "RequesterAnnotation", "WorkerId", "AssignmentId",
    "AssignmentStatus", "AcceptTime", "SubmitTime", "AutoApprovalTime",
    "Answer.workerId", "Answer.hitId",
]


def parse_answer_xml(blob: str) -> dict[str, str]:
    """Return {QuestionIdentifier: FreeText} for one Answer XML payload.

    Falls back to a regex if the XML namespace is missing or the blob
    is otherwise malformed.
    """
    fields: dict[str, str] = {}
    try:
        root = ET.fromstring(blob)
        for el in root.findall("q:Answer", NS):
            qid = el.find("q:QuestionIdentifier", NS)
            free = el.find("q:FreeText", NS)
            if qid is not None and qid.text:
                fields[qid.text] = (free.text or "") if free is not None else ""
    except ET.ParseError:
        pass
    if not fields:
        for qid, free in re.findall(
            r"<QuestionIdentifier>([^<]+)</QuestionIdentifier>\s*<FreeText>([^<]*)</FreeText>",
            blob or "",
        ):
            fields[qid] = free
    return fields


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--in_json",    type=Path, required=True)
    p.add_argument("--launch_log", type=Path, required=True,
                   help="scripts/launch_log.csv (mturkHitId -> H_NNNN)")
    p.add_argument("--out_csv",    type=Path, required=True)
    args = p.parse_args()

    mturk_to_internal: dict[str, str] = {}
    with args.launch_log.open(newline="") as f:
        for r in csv.DictReader(f):
            mturk_to_internal[r["mturkHitId"]] = r["hitId"]

    payload = json.loads(args.in_json.read_text())
    assignments = payload.get("Assignments", []) or []

    cols = PASS_THROUGH_COLS + RANK_COLS
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_unmapped = 0
    with args.out_csv.open("w", newline="") as f_out:
        w = csv.DictWriter(f_out, fieldnames=cols)
        w.writeheader()
        for a in assignments:
            mturk_hit = a.get("HITId", "")
            hid = mturk_to_internal.get(mturk_hit, "")
            if not hid:
                n_unmapped += 1
                # Still emit the row but with empty RequesterAnnotation/Answer.hitId
                # so reconcile.py reports "no_hitid" and skips cleanly.
            fields = parse_answer_xml(a.get("Answer", ""))
            row = {
                "HITId":              mturk_hit,
                "RequesterAnnotation": hid,
                "WorkerId":           a.get("WorkerId", ""),
                "AssignmentId":       a.get("AssignmentId", ""),
                "AssignmentStatus":   a.get("AssignmentStatus", ""),
                "AcceptTime":         a.get("AcceptTime", ""),
                "SubmitTime":         a.get("SubmitTime", ""),
                "AutoApprovalTime":   a.get("AutoApprovalTime", ""),
                "Answer.workerId":    fields.get("workerId", a.get("WorkerId", "")),
                "Answer.hitId":       fields.get("hitId", hid),
            }
            for k in RANK_COLS:
                # Form QuestionIdentifier is "rank1".."rank25"; CSV column is "Answer.rank1".."Answer.rank25"
                row[k] = fields.get(k.removeprefix("Answer."), "")
            w.writerow(row)
            n_written += 1

    print(f"Wrote {n_written} rows -> {args.out_csv}"
          + (f"  (warning: {n_unmapped} rows had unmapped HITId)" if n_unmapped else ""))


if __name__ == "__main__":
    main()
