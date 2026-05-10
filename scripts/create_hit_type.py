#!/usr/bin/env python3
"""Create one MTurk HIT type (sandbox or production).

Run ONCE per environment before launch_hits.py. Print the resulting
HITTypeId and an `export MTURK_HIT_TYPE_ID=...` line that launch_hits.py
picks up automatically.

  Sandbox pilot:     ./create_hit_type.py --reward 0.01 --sandbox
  Production launch: ./create_hit_type.py --reward 2.00

Qualifications (per plan v6 §4 Phase 5):
  - Locale  in {US, CA, GB, AU, NZ, IE}        (English-fluent)
  - HITs approved >= --min_hits_approved        (default 1000)
  - Approval rate >= --min_percent_approved     (default 97)

Reward MUST be passed explicitly (no default) to force a conscious
choice between sandbox-cheap and production-fair pricing.
"""

from __future__ import annotations

import argparse
import json

import boto3

LOCALE_QUAL_TYPE_ID           = "00000000000000000071"
HITS_APPROVED_QUAL_TYPE_ID    = "00000000000000000040"
PERCENT_APPROVED_QUAL_TYPE_ID = "000000000000000000L0"

SANDBOX_ENDPOINT = "https://mturk-requester-sandbox.us-east-1.amazonaws.com"

ENGLISH_LOCALES: list[dict[str, str]] = [
    {"Country": c} for c in ("US", "CA", "GB", "AU", "NZ", "IE")
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--title",                       default="Rank 3D mesh textures (~10 min, 25 trials)")
    p.add_argument("--description",                 default="For each trial, drag and rank six 3D textured meshes (A–F) from best to worst by how well their texture matches a written prompt.")
    p.add_argument("--keywords",                    default="3d, mesh, texture, comparison, ranking, drag-and-drop")
    p.add_argument("--reward",                      required=True, help='USD per HIT as string, e.g. "2.00" or "0.01"')
    p.add_argument("--auto_approve_seconds",        type=int, default=3 * 24 * 3600)
    p.add_argument("--assignment_duration_seconds", type=int, default=60 * 60)
    p.add_argument("--min_hits_approved",           type=int, default=1000)
    p.add_argument("--min_percent_approved",        type=int, default=97)
    p.add_argument("--profile",                     default="mturk")
    p.add_argument("--region",                      default="us-east-1")
    p.add_argument("--sandbox",                     action="store_true")
    p.add_argument("--dry_run",                     action="store_true")
    args = p.parse_args()

    quals = [
        {
            "QualificationTypeId": HITS_APPROVED_QUAL_TYPE_ID,
            "Comparator":          "GreaterThanOrEqualTo",
            "IntegerValues":       [args.min_hits_approved],
            "ActionsGuarded":      "Accept",
        },
        {
            "QualificationTypeId": PERCENT_APPROVED_QUAL_TYPE_ID,
            "Comparator":          "GreaterThanOrEqualTo",
            "IntegerValues":       [args.min_percent_approved],
            "ActionsGuarded":      "Accept",
        },
        {
            "QualificationTypeId": LOCALE_QUAL_TYPE_ID,
            "Comparator":          "In",
            "LocaleValues":        ENGLISH_LOCALES,
            "ActionsGuarded":      "Accept",
        },
    ]

    payload = {
        "AutoApprovalDelayInSeconds":  args.auto_approve_seconds,
        "AssignmentDurationInSeconds": args.assignment_duration_seconds,
        "Reward":                      args.reward,
        "Title":                       args.title,
        "Keywords":                    args.keywords,
        "Description":                 args.description,
        "QualificationRequirements":   quals,
    }

    env = "sandbox" if args.sandbox else "PRODUCTION"

    if args.dry_run:
        print(f"[DRY RUN] env={env}  reward=${args.reward}")
        print(json.dumps(payload, indent=2, default=str))
        return

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client_kwargs: dict[str, object] = {}
    if args.sandbox:
        client_kwargs["endpoint_url"] = SANDBOX_ENDPOINT
    client = session.client("mturk", **client_kwargs)

    resp = client.create_hit_type(**payload)
    hit_type_id = resp["HITTypeId"]

    print(f"HIT type created on {env}")
    print(f"  HITTypeId : {hit_type_id}")
    print(f"  Reward    : ${args.reward}")
    print(f"  Quals     : >= {args.min_hits_approved} HITs, >= {args.min_percent_approved}% approval, locale in {[l['Country'] for l in ENGLISH_LOCALES]}")
    print()
    print(f"Pass to launch_hits.py via:")
    print(f"  export MTURK_HIT_TYPE_ID={hit_type_id}")


if __name__ == "__main__":
    main()
