#!/usr/bin/env bash
# Usage: ./scripts/status.sh        |  HITID=<other-id> ./scripts/status.sh
set -euo pipefail

HITID="${HITID:-3THR0FZ966OJN02OZCH36TMIWWNLOY}"
AWS_PROFILE="${AWS_PROFILE:-mturk}"
REGION="us-east-1"

export AWS_PROFILE

python3 - "$HITID" "$REGION" <<'PY'
import sys, boto3
from datetime import datetime, timezone
from collections import Counter

hit_id, region = sys.argv[1], sys.argv[2]
session = boto3.Session(region_name=region)
mt = session.client("mturk", endpoint_url=f"https://mturk-requester.{region}.amazonaws.com")

hit = mt.get_hit(HITId=hit_id)["HIT"]
bal = mt.get_account_balance()["AvailableBalance"]

asg = []
nxt = None
while True:
    kw = {"HITId": hit_id, "MaxResults": 100}
    if nxt: kw["NextToken"] = nxt
    r = mt.list_assignments_for_hit(**kw)
    asg.extend(r.get("Assignments", []))
    nxt = r.get("NextToken")
    if not nxt: break

status_counts = Counter(a["AssignmentStatus"] for a in asg)

cap     = hit["MaxAssignments"]
avail   = hit["NumberOfAssignmentsAvailable"]
pend    = hit["NumberOfAssignmentsPending"]
done_hit = hit["NumberOfAssignmentsCompleted"]
sub_n   = status_counts.get("Submitted", 0)
app_n   = status_counts.get("Approved", 0)
rej_n   = status_counts.get("Rejected", 0)

created = datetime.fromisoformat(hit["CreationTime"].isoformat()) if hasattr(hit["CreationTime"], "isoformat") else datetime.fromisoformat(str(hit["CreationTime"]))
expires = datetime.fromisoformat(hit["Expiration"].isoformat()) if hasattr(hit["Expiration"], "isoformat") else datetime.fromisoformat(str(hit["Expiration"]))
now = datetime.now(timezone.utc)
elapsed_h = (now - created).total_seconds() / 3600
left_h    = (expires - now).total_seconds() / 3600

print(f"=== HIT: {hit_id} ===")
print(f"Title          : {hit['Title']}")
print(f"HITTypeId      : {hit['HITTypeId']}")
print(f"HITGroupId     : {hit['HITGroupId']}")
print(f"Reward         : ${hit['Reward']}")
print(f"HIT Status     : {hit['HITStatus']}")
print(f"Created        : {created.isoformat()}")
print(f"Expires        : {expires.isoformat()}")
print(f"Elapsed        : {elapsed_h:6.2f}h")
print(f"Time left      : {left_h:6.2f}h")
print()
print(f"Capacity       : {cap}")
print(f"Available      : {avail:3d}/{cap}  (open, awaiting accept)")
print(f"Pending        : {pend:3d}/{cap}  (accepted, in progress)")
print(f"Submitted      : {sub_n:3d}/{cap}  (submitted, awaiting approval)")
print(f"Approved       : {app_n:3d}/{cap}")
print(f"Rejected       : {rej_n:3d}/{cap}")
finished = sub_n + app_n + rej_n
print(f"Finished total : {finished:3d}/{cap}  ({100*finished/cap:.1f}%)")
print()
if elapsed_h > 0 and finished > 0:
    rate = finished / elapsed_h
    print(f"Submit rate    : {rate:.1f} assignments/hour")
    remaining = cap - finished
    if rate > 0 and remaining > 0:
        print(f"ETA all done   : {remaining/rate:.2f}h (extrapolated)")
print()
print("=== Per-assignment timing (most recent 20 by SubmitTime) ===")
if not asg:
    print("(no submissions yet)")
else:
    asg.sort(key=lambda a: a.get("SubmitTime") or datetime.min, reverse=True)
    print(f"{'WorkerId':<16}  {'Status':<10}  {'AcceptTime':<20}  {'SubmitTime':<20}  Duration")
    for a in asg[:20]:
        accept = a.get("AcceptTime")
        submit = a.get("SubmitTime")
        accept_s = accept.isoformat()[:19] if accept else ""
        submit_s = submit.isoformat()[:19] if submit else ""
        dur = f"{(submit - accept).total_seconds()/60:.1f}min" if (accept and submit) else ""
        print(f"{a['WorkerId'][:16]:<16}  {a['AssignmentStatus']:<10}  {accept_s:<20}  {submit_s:<20}  {dur}")
print()
print(f"Balance        : ${bal}")
PY
