#!/usr/bin/env python3
"""Create 240 production HITs (one per H_0001..H_0240) on MTurk.

Reads `scripts/aliasmap_full.json`, filters out the reserved `H_TUTORIAL`
entry, and submits each remaining HitId as an ExternalQuestion that
points at our static-host deployment (GitHub Pages) with `?hitId=<hid>`.
The MTurk-issued HITId is logged to `scripts/launch_log.csv` so the
offline reconciler can join MTurk's results CSV back to our internal
HitId via the `RequesterAnnotation` column.

Required env / boto3 config:
  - AWS profile `mturk` (or override via --profile) with policy
    `AmazonMechanicalTurkFullAccess`.
  - For sandbox dry runs, pass --sandbox (uses
    https://mturk-requester-sandbox.us-east-1.amazonaws.com).

Pre-requisites:
  - `create_hit_type` has been called once and the resulting HITTypeId
    is passed via --hit_type_id (or set $MTURK_HIT_TYPE_ID).
  - The static deployment (GitHub Pages) is live at --base_url. There is
    NO default value: pass it explicitly to force a conscious choice
    between sandbox / production / staging URLs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

PRODUCTION_REGION = "us-east-1"
SANDBOX_ENDPOINT  = "https://mturk-requester-sandbox.us-east-1.amazonaws.com"
LIFETIME_SECONDS  = 24 * 3600
RESERVED_HITIDS   = {"H_TUTORIAL"}


def external_question_xml(base_url: str, hit_id: str) -> str:
    return (
        '<ExternalQuestion xmlns="http://mechanicalturk.amazonaws.com/'
        'AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd">'
        f"<ExternalURL>{base_url}?hitId={hit_id}</ExternalURL>"
        "<FrameHeight>800</FrameHeight>"
        "</ExternalQuestion>"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full_json",   type=Path, default=Path("texture-study/scripts/aliasmap_full.json"))
    parser.add_argument("--out_log",     type=Path, default=Path("texture-study/scripts/launch_log.csv"))
    parser.add_argument("--base_url",    type=str,  required=True,
                        help="GH Pages base URL, e.g. https://<user>.github.io/<repo>/ "
                             "or https://study.yourdomain.com/. No default; must be passed.")
    parser.add_argument("--hit_type_id", type=str,  default=os.getenv("MTURK_HIT_TYPE_ID", ""))
    parser.add_argument("--profile",     type=str,  default="mturk")
    parser.add_argument("--region",      type=str,  default=PRODUCTION_REGION)
    parser.add_argument("--sandbox",     action="store_true")
    parser.add_argument("--dry_run",     action="store_true")
    parser.add_argument("--max_assignments", type=int, default=1)
    parser.add_argument("--lifetime_seconds", type=int, default=LIFETIME_SECONDS)
    args = parser.parse_args()

    if not args.hit_type_id and not args.dry_run:
        sys.exit("--hit_type_id (or $MTURK_HIT_TYPE_ID) required (run create_hit_type first)")

    full_map = json.loads(args.full_json.read_text())
    to_launch = sorted(hid for hid in full_map if hid not in RESERVED_HITIDS)
    expected = sum(1 for k in full_map if k.startswith("H_") and k != "H_TUTORIAL")
    assert len(to_launch) == expected, f"to_launch={len(to_launch)} != expected={expected}"
    if not args.dry_run:
        assert len(to_launch) == 240, f"expected 240 production HITs, got {len(to_launch)}"

    if args.dry_run:
        print(f"[DRY RUN] would launch {len(to_launch)} HITs")
        for hid in to_launch[:3]:
            print(f"  {hid} -> {args.base_url}?hitId={hid}")
        print(f"  lifetime: {args.lifetime_seconds}s ({args.lifetime_seconds / 3600:.1f}h)")
        print(f"  hit type: {args.hit_type_id or '(unset)'}")
        return

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client_kwargs: dict[str, object] = {}
    if args.sandbox:
        client_kwargs["endpoint_url"] = SANDBOX_ENDPOINT
    client = session.client("mturk", **client_kwargs)

    bal = client.get_account_balance()["AvailableBalance"]
    print(f"Account balance: ${bal} (sandbox={args.sandbox})")
    if not args.sandbox and float(bal) < 700:
        sys.exit(f"Refusing to launch: balance ${bal} < $700 minimum")

    args.out_log.parent.mkdir(parents=True, exist_ok=True)
    with args.out_log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["hitId", "mturkHitId", "createdAt"])
        for i, hit_id in enumerate(to_launch, 1):
            resp = client.create_hit_with_hit_type(
                HITTypeId=args.hit_type_id,
                MaxAssignments=args.max_assignments,
                LifetimeInSeconds=args.lifetime_seconds,
                Question=external_question_xml(args.base_url, hit_id),
                RequesterAnnotation=hit_id,
            )
            w.writerow([
                hit_id,
                resp["HIT"]["HITId"],
                datetime.now(timezone.utc).isoformat(),
            ])
            f.flush()
            if i % 20 == 0:
                print(f"  launched {i}/{len(to_launch)}")

    print(f"DONE: {len(to_launch)} HITs launched, log -> {args.out_log}")


if __name__ == "__main__":
    main()
