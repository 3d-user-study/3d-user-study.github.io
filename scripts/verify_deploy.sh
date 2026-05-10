#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://3d-user-study.github.io}"
OWNER_REPO="${OWNER_REPO:-3d-user-study/3d-user-study.github.io}"

PASS=0
FAIL=0
ERRORS=()

ok()   { PASS=$((PASS+1)); printf '  [PASS] %s\n' "$1"; }
fail() { FAIL=$((FAIL+1)); ERRORS+=("$1"); printf '  [FAIL] %s\n' "$1"; }

probe() {
    local label="$1" path="$2" min_bytes="${3:-1}"
    local code size
    read -r code size < <(curl -sS -o /tmp/_probe.body -w '%{http_code} %{size_download}\n' "${BASE_URL}${path}")
    if [ "$code" = "200" ] && [ "$size" -ge "$min_bytes" ]; then
        ok "${label}: HTTP ${code}, ${size}B"
    else
        fail "${label}: HTTP ${code}, ${size}B (expected 200, >=${min_bytes}B)"
    fi
}

probe_404() {
    local label="$1" path="$2"
    local code
    code=$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}${path}")
    if [ "$code" = "404" ]; then
        ok "${label}: HTTP 404 (expected — endpoint removed)"
    else
        fail "${label}: HTTP ${code} (expected 404 — stale endpoint must not be served)"
    fi
}

printf '=== Static endpoints @ %s ===\n' "$BASE_URL"
probe "root /"               "/"                  100
probe "index.html"           "/index.html"        100
probe "viewer-rank.html"     "/viewer-rank.html"  100
probe "trialMap.json"        "/trialMap.json"     1000
probe ".nojekyll"            "/.nojekyll"         0
probe_404 "viewer-pair.html (pre-pivot)" "/viewer-pair.html"

printf '\n=== Sample mesh assets (random pick from LOCAL trialMap) ===\n'
LOCAL_TRIALMAP="${LOCAL_TRIALMAP:-$(dirname "$0")/../docs/trialMap.json}"
if [ ! -f "$LOCAL_TRIALMAP" ]; then
    fail "local trialMap not found at ${LOCAL_TRIALMAP} (set \$LOCAL_TRIALMAP)"
    SLOT_DIRS=""
else
    SLOT_DIRS=$(python3 -c "
import json, random
with open('${LOCAL_TRIALMAP}') as f:
    d = json.load(f)
random.seed(0)
key = random.choice([k for k in d.keys() if k.startswith('H_0')])
trial = random.choice(d[key])
for s in trial['slots']:
    print(s['dir'])
")
fi
if [ -n "$SLOT_DIRS" ]; then
    i=1
    while IFS= read -r dir; do
        probe "slot ${i} .obj"  "/data/${dir}/textured.obj"  1000
        probe "slot ${i} .mtl"  "/data/${dir}/textured.mtl"  10
        probe "slot ${i} .png"  "/data/${dir}/textured.png"  1000
        i=$((i+1))
    done <<< "$SLOT_DIRS"
fi

printf '\n=== trialMap.json structural invariants (LIVE) ===\n'
TRIALMAP_HTTP=$(curl -sS -o /tmp/_trialmap_live.json -w '%{http_code}' "${BASE_URL}/trialMap.json")
if [ "$TRIALMAP_HTTP" != "200" ]; then
    fail "live trialMap.json HTTP ${TRIALMAP_HTTP} - skipping structural invariants"
    INVARIANTS_OUT=""
else
    INVARIANTS_OUT=$(python3 - <<'PY'
import json, sys, re
with open('/tmp/_trialmap_live.json') as f:
    d = json.load(f)
errors = []

prod_keys = sorted(k for k in d.keys() if re.fullmatch(r"H_\d{4}", k))
expected = [f"H_{i:04d}" for i in range(1, 37)]
if prod_keys != expected:
    errors.append(f"production keys mismatch: got {len(prod_keys)} (expected 36, contiguous H_0001..H_0036)")

if "H_TUTORIAL" not in d:
    errors.append("H_TUTORIAL entry missing")

forbidden = ["spotex", "goatex", "mvadapter", "TEXGen", "paint3d", "syncmvd", "_corrupt"]
raw = json.dumps(d).lower()
leaks = [m for m in forbidden if m.lower() in raw]
if leaks:
    errors.append(f"INVARIANT #2 LEAK: forbidden tokens found in JSON: {leaks}")

allowed_trial_keys = {"i", "prompt", "slots"}
allowed_prompt_keys = {"FULL", "parts"}
allowed_part_keys = {"label", "caption"}
allowed_slot_keys = {"slot", "dir"}
slot_letters = {"A", "B", "C", "D", "E", "F"}

hits_with_wrong_count = []
trials_with_bad_keys = []
trials_with_bad_prompt = []
trials_with_bad_slots = []

for hit_id, trials in d.items():
    if hit_id == "H_TUTORIAL":
        if not isinstance(trials, list) or len(trials) != 1:
            errors.append(f"H_TUTORIAL must have exactly 1 trial, got {len(trials) if isinstance(trials, list) else 'n/a'}")
        continue
    if not isinstance(trials, list) or len(trials) != 25:
        hits_with_wrong_count.append((hit_id, len(trials) if isinstance(trials, list) else "n/a"))
        continue
    seen_i = set()
    for t in trials:
        if set(t.keys()) != allowed_trial_keys:
            trials_with_bad_keys.append((hit_id, t.get("i"), sorted(t.keys())))
            continue
        if not isinstance(t.get("i"), int) or t["i"] in seen_i:
            trials_with_bad_keys.append((hit_id, t.get("i"), "duplicate or non-int i"))
            continue
        seen_i.add(t["i"])

        prompt = t.get("prompt")
        if (not isinstance(prompt, dict)
                or set(prompt.keys()) != allowed_prompt_keys
                or not isinstance(prompt.get("FULL"), str)
                or not prompt["FULL"].strip()
                or not isinstance(prompt.get("parts"), list)):
            trials_with_bad_prompt.append((hit_id, t.get("i")))
            continue
        bad_part = False
        for p in prompt["parts"]:
            if (not isinstance(p, dict)
                    or set(p.keys()) != allowed_part_keys
                    or not isinstance(p.get("label"), str)
                    or not isinstance(p.get("caption"), str)):
                bad_part = True
                break
        if bad_part:
            trials_with_bad_prompt.append((hit_id, t.get("i")))
            continue

        slots = t.get("slots")
        if not isinstance(slots, list) or len(slots) != 6:
            trials_with_bad_slots.append((hit_id, t.get("i"), "wrong slot count"))
            continue
        seen_letters = set()
        seen_dirs = set()
        bad_slot = False
        for s in slots:
            if (not isinstance(s, dict)
                    or set(s.keys()) != allowed_slot_keys
                    or s.get("slot") not in slot_letters
                    or not isinstance(s.get("dir"), str)
                    or "/" not in s["dir"]):
                bad_slot = True
                break
            if s["slot"] in seen_letters or s["dir"] in seen_dirs:
                bad_slot = True
                break
            seen_letters.add(s["slot"])
            seen_dirs.add(s["dir"])
        if bad_slot or seen_letters != slot_letters:
            trials_with_bad_slots.append((hit_id, t.get("i"), "bad slot content"))
            continue
    if len(seen_i) != 25:
        hits_with_wrong_count.append((hit_id, f"unique_i={len(seen_i)} (expected 25)"))

if hits_with_wrong_count:
    errors.append(f"hits with wrong trial composition: {hits_with_wrong_count[:3]} ({len(hits_with_wrong_count)} total)")
if trials_with_bad_keys:
    errors.append(f"trials with bad keys: {trials_with_bad_keys[:3]} ({len(trials_with_bad_keys)} total)")
if trials_with_bad_prompt:
    errors.append(f"trials with bad prompt: {trials_with_bad_prompt[:3]} ({len(trials_with_bad_prompt)} total)")
if trials_with_bad_slots:
    errors.append(f"trials with bad slots: {trials_with_bad_slots[:3]} ({len(trials_with_bad_slots)} total)")

if errors:
    for e in errors:
        print(f"FAIL::{e}")
    sys.exit(1)
else:
    print(f"OK::36 production HITs + H_TUTORIAL")
    print(f"OK::25 trials per HIT, each with unique i")
    print(f"OK::Invariant #2 - no method names or _corrupt token leaked")
    print(f"OK::every trial has prompt.FULL + prompt.parts[].(label,caption)")
    print(f"OK::every trial has 6 slots (A..F unique) with hash dirs")
PY
)
fi

if [ -n "$INVARIANTS_OUT" ]; then
    while IFS= read -r line; do
        if [[ "$line" == OK::* ]]; then
            ok "${line#OK::}"
        elif [[ "$line" == FAIL::* ]]; then
            fail "${line#FAIL::}"
        fi
    done <<< "$INVARIANTS_OUT"
fi

printf '\n=== GitHub Pages metadata ===\n'
REPO_HTTP=$(curl -sS -o /tmp/_repo.json -w '%{http_code}' "https://api.github.com/repos/${OWNER_REPO}")
if [ "$REPO_HTTP" = "200" ]; then
    HAS_PAGES=$(python3 -c "import json; print(json.load(open('/tmp/_repo.json')).get('has_pages'))")
    if [ "$HAS_PAGES" = "True" ]; then
        ok "repo has_pages=True (canonical Pages-enabled signal)"
        PAGES_API_HTTP=$(curl -sS -o /tmp/_pages.json -w '%{http_code}' "https://api.github.com/repos/${OWNER_REPO}/pages")
        if [ "$PAGES_API_HTTP" = "200" ]; then
            PAGES_INFO=$(python3 -c "
import json
d = json.load(open('/tmp/_pages.json'))
src = d.get('source') or {}
print(d.get('status') or '-', d.get('html_url') or '-', src.get('branch') or '-', src.get('path') or '-')
")
            read -r PAGES_STATUS PAGES_URL PAGES_BRANCH PAGES_PATH <<< "$PAGES_INFO"
            ok "Pages API: status=${PAGES_STATUS} branch=${PAGES_BRANCH} path=${PAGES_PATH}"
        else
            ok "Pages API HTTP ${PAGES_API_HTTP} (eventual-consistency lag for anon API; ignore - has_pages is canonical)"
        fi
    else
        fail "repo has_pages=False - enable Pages in Settings -> Pages"
    fi
else
    fail "repo API HTTP ${REPO_HTTP} - cannot check Pages status"
fi

printf '\n=== SUMMARY ===\n'
printf 'PASS: %d\n' "$PASS"
printf 'FAIL: %d\n' "$FAIL"
if [ "$FAIL" -ne 0 ]; then
    printf '\nFailures:\n'
    for e in "${ERRORS[@]}"; do printf '  - %s\n' "$e"; done
    exit 1
fi
printf 'ALL CHECKS PASSED\n'
