# texture-study

MTurk-driven user study to rank 6 part-aware 3D mesh texture-generation methods (`spotex` (ours), `goatex`, `mvadapter`, `TEXGen`, `paint3d`, `syncmvd`) across 54 samples using Bradley-Terry pairwise comparison.

This is a **pure static site** served from GitHub Pages (no server, no Next.js, no Node). The study shell lives in `docs/index.html` + `docs/viewer-pair.html` + `docs/trialMap.json` + 972 mesh files under `docs/data/{sample}/{hash16}/`. Mesh directories are hash-anonymized (sha256 truncated to 16 hex chars, salted with a private secret) so method identity never leaks to the client. MTurk delivers worker query params (`hitId`, `assignmentId`, `workerId`, `turkSubmitTo`) in the iframe URL; the static page consumes them, gates consent, runs 25 trials, and POSTs selections to the standard MTurk `externalSubmit` endpoint.

> This README is owner-only documentation. It lives at the repo root, **outside** `docs/`, so GitHub Pages will not publish it.

---

## Pipeline overview

```
    +--------------------+      +-----------------+      +--------------------+      +------------------+
    | dehydrate_meshes.py|----->|   gen_hits.py   |----->|  create_hit_type   |----->|  launch_hits.py  |
    |  (one-time prep)   |      |  (offline prep) |      |  (one-time per run)|      |  (240 HITs)      |
    +--------------------+      +-----------------+      +--------------------+      +------------------+
            |                            |                                                     |
            v                            v                                                     v
    +-----------------------+   +---------------------+                            +------------------+
    | docs/data/{sample}/   |   | scripts/            |                            |  MTurk workers   |
    |   {hash16}/textured.* |   |   method_hash_map   |                            |  (24h lifetime)  |
    | scripts/.dehydrate    |   |   .dehydrate_salt   |                            +--------+---------+
    |   _salt (PRIVATE)     |   |   aliasmap_full     |                                     |
    | scripts/method_hash   |   | docs/trialMap.json  |                                     v
    |   _map (PRIVATE)      |   |   (PUBLIC, no leak) |                            +-----------------+
    +-----------------------+   +---------------------+                            | Batch_xxxx.csv  |
                                                                                   +--------+--------+
                                                                                            |
    +------------------+      +------------+      +-----------------+                       |
    |   aggregate.py   | <--- |  fit_bt.py | <--- |  reconcile.py   | <---------------------+
    | (paired bootstrap)      | (per-sample BT)   | (CSV -> judgments)
    +------------------+      +------------+      +-----------------+
```

Phases: `dehydrate_meshes` (once) → `gen_hits` (offline) → `git push` → enable GH Pages → `create_hit_type` (MTurk) → `launch_hits` (MTurk) → workers complete → download `Batch_results.csv` → `reconcile` → `fit_bt` → `aggregate`.

---

## Prerequisites

- **git** ≥ 2.30 + a GitHub account (public repo required for free Pages tier)
- **Python** ≥ 3.10 (we tested on 3.13.12)
- **AWS** account with MTurk Requester linked at <https://requester.mturk.com/>
- **MTurk balance** ≥ ~$700 to cover 240 HITs at $2.00 reward + 40% fee + safety buffer
- (Optional) Custom subdomain DNS access if you do not want the default `https://<user>.github.io/<repo>/` URL

No Node.js, no npm, no Next.js, no Vercel. Static-only.

---

## Local development

All scripts assume **cwd = repo root** (`/path/to/SPOTex/`), not `texture-study/`. The static server runs from `texture-study/docs/`.

### 1. Install Python deps

```bash
pip3 install -r texture-study/scripts/requirements.txt
```

This pulls `boto3`, `choix`, `numpy`, `pandas`, `scipy`.

### 2. Build the dehydrated mesh tree (one-time)

```bash
python3 texture-study/scripts/dehydrate_meshes.py
```

This reads `portable_viewer/data/viewer_index.json` (54 samples × 6 methods) and writes:

- `texture-study/docs/data/{sample}/{hash16}/textured.{obj,mtl,png}` — 324 hash dirs, 972 files, ~892 MB
- `texture-study/scripts/.dehydrate_salt` — **PRIVATE** 256-bit hex salt (chmod 600, gitignored)
- `texture-study/scripts/method_hash_map.json` — **PRIVATE** `{sample: {method: hash16}}` lookup (gitignored)

Re-running with the same salt is idempotent — hashes stay stable. Deleting `.dehydrate_salt` and re-running rotates all hashes (and invalidates any in-flight HITs).

### 3. Generate HIT inputs (offline, deterministic)

```bash
python3 texture-study/scripts/gen_hits.py
```

This writes 2 artifacts:

- `texture-study/docs/trialMap.json` — **PUBLIC**; trial defs as `{i, kind, dirL, dirR, vig?}` per HIT. Method names absent.
- `texture-study/scripts/aliasmap_full.json` — **OFFLINE**; expanded form `{methodL, methodR, sample, dirL, dirR, vig?, expected?}` per HIT. Used by `reconcile.py` for vigilance scoring + judgment expansion. Filename retained for backward compat; no longer contains aliases.

Default knobs (override only if you understand the implications):

```
--n_hits     240    # 54 samples * 15 pairs * ~6 votes / 20 main per HIT
--n_real     20     # main trials per HIT
--n_vigilance 5     # textured-vs-flat-gray vigilance trials per HIT
--seed       2024
```

### 4. Run the local static server

GitHub Pages publishes from `texture-study/docs/`. Serve the same directory locally with Python's built-in HTTP server:

```bash
cd texture-study/docs
python3 -m http.server 3000
```

Then open the URLs below in any browser. Paths and behavior match production GH Pages 1:1.

> **Bare `http://localhost:3000/` will always render `Missing hitId. Please return this HIT and accept it from MTurk.`** This is intentional — the same code runs in MTurk's iframe, so the study shell hard-requires the worker query params. Use one of the URLs below.

### 5. Local testing URLs

The study shell parses `hitId`, `assignmentId`, `workerId`, and (optionally) `turkSubmitTo` from the query string — exactly the way MTurk's ExternalQuestion iframe delivers them. There is no fallback "demo mode."

#### Mode A — Preview (no submit, just view the questions)

What MTurk shows workers **before** they accept the HIT. `ASSIGNMENT_ID_NOT_AVAILABLE` is the literal string MTurk uses for preview mode; the page renders a "preview" notice and disables the Start button.

```
http://localhost:3000/index.html?hitId=H_0001&workerId=PREVIEW&assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE
```

#### Mode B — Accepted (full flow, submit-enabled)

What MTurk shows after a worker clicks **Accept**. Use any non-special string for `assignmentId`. Override `turkSubmitTo` to a local stub so the final form POST does not try to reach the real MTurk endpoint.

```
http://localhost:3000/index.html?hitId=H_0001&workerId=DEV_WORKER_001&assignmentId=DEV_ASN_001&turkSubmitTo=http://localhost:3000/__stub
```

#### Mode C — Repeat-participation block test

Open Mode B, click through all 25 trials + click **Submit HIT**. Then open the URL below (same `workerId`, different `hitId`):

```
http://localhost:3000/index.html?hitId=H_0002&workerId=DEV_WORKER_001&assignmentId=DEV_ASN_002
```

You should see `You have already participated in this study. Please return this HIT.` This is the localStorage best-effort gate replacing the now-defunct UniqueTurker service. To reset for further testing, run `localStorage.clear()` in DevTools.

#### Mode D — Direct viewer (skip consent, render meshes only)

The fastest way to verify Three.js + the asset pipeline are working. Bypasses `index.html` entirely. The `dirL` / `dirR` params are `{sample}/{hash16}` paths — pull two real ones from `texture-study/docs/trialMap.json` for any sample, e.g.:

```
http://localhost:3000/viewer-pair.html?dirL=01_0aa910f8ec974330a9a89a5c7cf4e3dd/fca0c4bf5e4cf0ea&dirR=01_0aa910f8ec974330a9a89a5c7cf4e3dd/6f41c14a46739703
```

Append `&vig=L` (or `&vig=R`) with **identical** `dirL == dirR` to verify the vigilance gray-override:

```
http://localhost:3000/viewer-pair.html?dirL=01_.../fca0c4bf5e4cf0ea&dirR=01_.../fca0c4bf5e4cf0ea&vig=L
```

You should see two side-by-side meshes within ~5 seconds. The status bar at the bottom-left reads `Loaded 2 panels` on success or `Load failed` on error (open DevTools console for the real exception).

#### Valid `hitId` values

- `H_0001` … `H_0240` — real HITs (20 main + 5 vigilance trials each)
- `H_TUTORIAL` — tutorial entry only (1 trial, used internally; do **not** pass as a worker `hitId` — the trial-count check rejects it as `Invalid HIT ID`).

`H_TEST` does **not** exist (deliberately excluded per invariant #2).

### 6. Smoke test

The full 19-test smoke suite (HTTP layer) lives in your local notes. Minimum sanity checks against the local server:

```bash
# 1. index.html serves
curl -sI http://localhost:3000/index.html | head -1   # expect 200

# 2. trialMap.json serves and contains no method names
curl -s http://localhost:3000/trialMap.json | grep -E "spotex|goatex|mvadapter|TEXGen|paint3d|syncmvd"
# expect: NO MATCHES (empty output, exit code 1)

# 3. Mesh assets serve
curl -sI "http://localhost:3000/data/01_0aa910f8ec974330a9a89a5c7cf4e3dd/fca0c4bf5e4cf0ea/textured.obj" | head -1   # expect 200

# 4. Private artifacts must NOT be reachable from docs/
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/scripts/method_hash_map.json   # expect 404
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/scripts/.dehydrate_salt        # expect 404
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/scripts/gen_hits.py            # expect 404
```

The last three checks pass automatically because `python3 -m http.server` only serves files under its cwd (`docs/`); `scripts/` is one level up and not exposed. GH Pages enforces the same boundary by publishing only `/docs`.

---

## GitHub Pages deploy

GitHub Pages serves static files from any branch + a chosen subdirectory. We publish from `main` + `/docs` so that `scripts/` (containing the salt and method-hash map) stays outside the publish boundary.

### One-time repo setup

```bash
cd texture-study

# Initialize repo if not already
git init
git add .
git commit -m "Initial study site"

# Create the GitHub repo (public — required for free Pages)
# Then add it as remote:
git remote add origin https://github.com/<YOUR_USERNAME>/<REPO_NAME>.git
git branch -M main
git push -u origin main
```

> **The first push is ~892 MB** (mostly `docs/data/`). At 10 Mbps upload that is ~12 minutes. GitHub's hard per-file limit is 100 MB; our largest file is ~1.4 MB so you are well under. Repo soft cap is 1 GB; we sit at ~900 MB.

### Enable Pages

1. Go to your repo → **Settings** → **Pages** (left sidebar).
2. **Source**: `Deploy from a branch`.
3. **Branch**: `main`, folder: `/docs`. Click **Save**.
4. Wait ~1–2 minutes. The page refreshes with `Your site is live at https://<YOUR_USERNAME>.github.io/<REPO_NAME>/`.

### Custom subdomain (optional)

If you want a friendlier URL like `https://study.yourdomain.com/` instead of `https://<user>.github.io/<repo>/`:

1. Add a `CNAME` file at `docs/CNAME` containing **only** the bare hostname:
   ```bash
   echo "study.yourdomain.com" > texture-study/docs/CNAME
   git add docs/CNAME && git commit -m "Add custom domain" && git push
   ```
2. At your DNS registrar, add a CNAME record:
   ```
   study.yourdomain.com  CNAME  <YOUR_USERNAME>.github.io.
   ```
3. Back in **Settings → Pages**, the custom-domain field will auto-fill from the CNAME file. Wait for the DNS check to pass (1–60 minutes).
4. Tick **Enforce HTTPS**. GitHub provisions a Let's Encrypt cert automatically (5–15 min the first time).

### Post-deploy smoke test

```bash
DEPLOY_URL=https://<YOUR_USERNAME>.github.io/<REPO_NAME>   # or your custom subdomain

# 1. Index serves
curl -sI "$DEPLOY_URL/" | head -1                                                   # expect 200

# 2. Method-name leak check
curl -s "$DEPLOY_URL/trialMap.json" | grep -cE "spotex|goatex|mvadapter|TEXGen|paint3d|syncmvd"
# expect 0

# 3. Mesh asset reachable
curl -sI "$DEPLOY_URL/data/01_0aa910f8ec974330a9a89a5c7cf4e3dd/fca0c4bf5e4cf0ea/textured.obj" | head -1
# expect 200

# 4. Private artifacts must 404 (they were never under /docs)
curl -s -o /dev/null -w "%{http_code}\n" "$DEPLOY_URL/scripts/method_hash_map.json"   # expect 404
curl -s -o /dev/null -w "%{http_code}\n" "$DEPLOY_URL/scripts/.dehydrate_salt"        # expect 404

# 5. Full Mode-B URL renders the consent screen (visual check in browser)
open "$DEPLOY_URL/?hitId=H_0001&workerId=PREVIEW&assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE"
```

Run the full 19-test smoke suite (in your local notes) against `$DEPLOY_URL` before launching real HITs.

---

## AWS: install CLI + configure MTurk profile

MTurk uses standard AWS IAM credentials; the boto3 calls in `create_hit_type.py` and `launch_hits.py` resolve the `mturk` named profile via `~/.aws/credentials`.

### Install AWS CLI v2

#### macOS

Pick one:

```bash
# (a) Homebrew (recommended if you already use brew)
brew install awscli
aws --version

# (b) Official .pkg installer
curl "https://awscli.amazonaws.com/AWSCLIV2.pkg" -o "AWSCLIV2.pkg"
sudo installer -pkg AWSCLIV2.pkg -target /
aws --version
rm AWSCLIV2.pkg
```

#### Linux x86_64

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
aws --version
rm -rf awscliv2.zip aws
```

#### Linux ARM (aarch64)

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
aws --version
rm -rf awscliv2.zip aws
```

### Create the IAM user (one-time)

In the AWS console:

1. IAM → Users → **Add user** → name `mturk-requester`.
2. Access type: **Programmatic access**.
3. Attach policy: `AmazonMechanicalTurkFullAccess`.
4. Save the **Access key ID** and **Secret access key** — shown only once.

### Configure the `mturk` profile

```bash
aws configure --profile mturk
# AWS Access Key ID:     <paste>
# AWS Secret Access Key: <paste>
# Default region:        us-east-1
# Default output:        json
```

Sanity check:

```bash
# Production endpoint balance (must be >= ~$700)
aws --profile mturk mturk get-account-balance --region us-east-1

# Sandbox endpoint balance (free $10000 play money, used for pilot)
aws --profile mturk mturk get-account-balance \
    --region us-east-1 \
    --endpoint-url https://mturk-requester-sandbox.us-east-1.amazonaws.com
```

If `get-account-balance` fails with `RequestError` on production, your AWS account is not yet linked to your Requester account at <https://requester.mturk.com/developer> — link it first.

---

## Running the full study pipeline

All commands run from **repo root** (`/path/to/SPOTex/`). Replace `<DEPLOY_URL>` with your GH Pages URL (e.g. `https://yourname.github.io/texture-study/` or `https://study.yourdomain.com/`).

### Phase 4 — sandbox pilot

```bash
# 1. Create a sandbox HIT type (cheap reward is fine here)
python3 texture-study/scripts/create_hit_type.py \
    --reward 0.01 \
    --sandbox \
    --profile mturk
# -> prints `export MTURK_HIT_TYPE_ID=...`
# Copy and run that export in your shell.

# 2. Dry-run launch (no API calls)
python3 texture-study/scripts/launch_hits.py \
    --sandbox \
    --dry_run \
    --base_url <DEPLOY_URL>

# 3. Real sandbox launch (a handful of HITs are enough; --n_hits limit not built-in,
#    so for a small pilot regenerate with `gen_hits.py --n_hits 3` first or
#    just kill launch_hits.py after a few HITs)
python3 texture-study/scripts/launch_hits.py \
    --sandbox \
    --base_url <DEPLOY_URL>
```

Visit <https://workersandbox.mturk.com/> with a separate sandbox worker account and complete a HIT end-to-end.

### Phase 5 — production launch

```bash
# 1. Create the production HIT type. PICK THE REWARD CAREFULLY.
#    Plan-locked reward is $2.00 (~$626 budget). $0.01 is technically valid but
#    will trigger 4x HIT inflation, vigilance failure rate spikes, and MTurk
#    forum blowback. The script intentionally has NO --reward default to force
#    an explicit choice.
python3 texture-study/scripts/create_hit_type.py \
    --reward 2.00 \
    --profile mturk
# -> export MTURK_HIT_TYPE_ID=...

# 2. Dry-run against production endpoint (no API calls)
python3 texture-study/scripts/launch_hits.py \
    --dry_run \
    --base_url <DEPLOY_URL>

# 3. Real production launch (240 HITs, MaxAssignments=1, 24h lifetime)
python3 texture-study/scripts/launch_hits.py \
    --base_url <DEPLOY_URL>
# -> writes texture-study/scripts/launch_log.csv
```

### Phase 6 — monitor

- Day 3: check assignment completion in <https://requester.mturk.com/>.
- Watch for vigilance-fail clusters; reject `vigilance_score < 1.0` per plan.

### Phase 7 — analysis

After the HIT lifetime expires (or all 240 HITs are submitted), download the results CSV from the Requester console (`Batch_xxxx_batch_results.csv`).

```bash
# 1. Reconcile MTurk results -> per-judgment table
#    Add `--worker_cap 1` for production to enforce 1 approval per workerId
#    (default `--worker_cap=0` is fine for sandbox pilot).
python3 texture-study/scripts/reconcile.py \
    --results_csv path/to/Batch_xxxx_batch_results.csv
# -> writes texture-study/analysis/judgments.csv
#    + texture-study/analysis/approvals.csv
#    + texture-study/analysis/rejections.csv
#    + texture-study/analysis/reconcile_summary.txt

# 2. Per-sample Bradley-Terry MLE + bootstrap CIs
python3 texture-study/scripts/fit_bt.py
# -> texture-study/analysis/bt_per_sample.csv

# 3. Aggregate ranking via paired bootstrap over samples
python3 texture-study/scripts/aggregate.py
# -> texture-study/analysis/bt_aggregate.csv
```

End-to-end synthetic-data validation (already run): with ground-truth strengths `{spotex:5, goatex:4, mvadapter:3, TEXGen:2, paint3d:1.5, syncmvd:1}`, `spotex` was recovered as rank 1 in 45/54 samples and the aggregate ranking matched the true order within bootstrap CI.

---

## File layout

```
texture-study/
├── README.md                       # this file (NOT under /docs, so GH Pages won't publish it)
├── .gitignore                      # shields scripts/.dehydrate_salt + method_hash_map.json + aliasmap_full.json + analysis/
│
├── docs/                           # ← GitHub Pages publish source (`/docs` on `main`)
│   ├── .nojekyll                   # disables Jekyll processing (keep filenames as-is)
│   ├── index.html                  # study shell — consent → tutorial → 25 trials → submit
│   ├── viewer-pair.html            # iframe-embedded Three.js pair viewer
│   ├── trialMap.json               # PUBLIC method-free trial defs (gen_hits output)
│   ├── data/                       # 54 × 6 = 324 hash dirs, 972 mesh files, ~892 MB
│   │   └── {sample}/{hash16}/textured.{obj,mtl,png}
│   └── CNAME                       # (optional) custom domain hostname
│
└── scripts/                        # offline-only — NOT under /docs, never published
    ├── requirements.txt
    ├── dehydrate_meshes.py         # one-time mesh hashing pass
    ├── .dehydrate_salt             # PRIVATE 256-bit hex salt (chmod 600, gitignored)
    ├── method_hash_map.json        # PRIVATE {sample: {method: hash16}} (gitignored)
    ├── gen_hits.py                 # offline prep (2 artifacts)
    ├── aliasmap_full.json          # OFFLINE expanded HIT/trial map (gitignored)
    ├── create_hit_type.py          # MTurk HITType creator (--reward REQUIRED)
    ├── launch_hits.py              # MTurk HIT launcher (boto3)
    ├── launch_log.csv              # written by launch_hits.py (gitignored)
    ├── reconcile.py                # Batch_results.csv -> judgments.csv
    ├── fit_bt.py                   # per-sample Bradley-Terry MLE
    └── aggregate.py                # paired-bootstrap aggregate ranking
```

---

## Critical invariants — DO NOT BREAK

1. **Method identity never reaches the client.** Mesh dirs use `{sample}/{hash16}` where `hash16 = sha256(f"{sample}:{method}:{salt}").hexdigest()[:16]`. `docs/trialMap.json` contains only hash dirs and trial-level metadata (`vig`, `kind`, `i`); never raw method names. Verified by the smoke suite. If you change `dehydrate_meshes.py` or `gen_hits.py`, re-run those tests.

2. **`scripts/` lives OUTSIDE `docs/`.** This is not cosmetic — it is the security boundary. GitHub Pages publishes only `/docs`, so `scripts/.dehydrate_salt` and `scripts/method_hash_map.json` are not reachable over HTTP. Do **not** move any script or private artifact under `docs/`.

3. **`scripts/.dehydrate_salt` is the master secret.** If it leaks, an attacker can recompute every `(sample, method) → hash16` mapping and break method anonymization. Treat it like a private key. It is `chmod 600` and gitignored.

4. **`scripts/aliasmap_full.json`, `scripts/method_hash_map.json`, `scripts/launch_log.csv` must NEVER ship to git.** `.gitignore` enforces this. Verify with `git check-ignore scripts/.dehydrate_salt scripts/method_hash_map.json scripts/aliasmap_full.json` — all three should print their paths.

5. **`create_hit_type.py --reward` is intentionally required (no default).** This forces a conscious sandbox-vs-production choice. $0.01 is sandbox-only; $2.00 is the plan-locked production value.

6. **`random.seed(2024)`** in `gen_hits.py`, `fit_bt.py`, and `aggregate.py` is reproducibility-locked. Do not change without re-validating the synthetic BT recovery test.

7. **Coverage math:** 54 samples × 15 pairs × ~6 votes ÷ 20 main trials per HIT = 240 HITs. Changing `--n_real` or `--n_vigilance` invalidates this; budget and schedule both downstream.

---

## Limitations & residual risk

### Hash equivalence-class attack (accepted)

A worker who completes many HITs can cluster the dirs they see by hash and infer "all dirs with hash X for sample Y are the same method," even without knowing which method. This degrades to a 6-class clustering attack per sample. We accept this because: (a) MTurk per-HIT `MaxAssignments=1` plus the localStorage UT gate (below) limit any single worker to ~1 HIT in our pool, and (b) the absolute method-name leak (which would let an attacker bias votes toward `spotex` to inflate our paper) is structurally impossible with hashing.

### UniqueTurker replacement (best-effort + post-hoc)

The original UniqueTurker service (`uniqueturker.myleott.com`) shut down in 2022. We replaced it with a localStorage-based gate in `docs/index.html`:

- On HIT submit, the page sets `localStorage["ut:<UT_ID>:<workerId>"] = "1"`.
- On any subsequent HIT load with the same `workerId`, the page refuses with `You have already participated in this study.`

This is **bypassable** by clearing browser storage, using incognito, or switching browser/device. For true enforcement, `scripts/reconcile.py` ships with an opt-in `--worker_cap N` flag that applies a post-hoc per-worker cap on accepted submissions (sorted by `SubmitTime`, with `AssignmentId` tiebreaker; excess submissions are demoted to `rejections.csv` with the `worker_cap_exceeded` feedback line). The default `--worker_cap=0` is **disabled** (preserves prior behavior — adequate for sandbox pilot). For the production launch, run `python3 texture-study/scripts/reconcile.py --results_csv ... --worker_cap 1` to guarantee at most one approved submission per `workerId`.

### `H_TUTORIAL` exposure (accepted)

Anyone who reads `docs/trialMap.json` sees a `H_TUTORIAL` entry. Workers cannot accept this as a real HIT (MTurk only serves IDs you actually launch via `launch_hits.py`), and the consent screen rejects it as `Invalid HIT ID` if anyone manually navigates with `?hitId=H_TUTORIAL`. The tutorial trial is rendered as part of every real HIT before trial 1 begins.

### Vigilance flag exposure (R17, accepted)

`docs/trialMap.json` and the iframe URL both expose `vig: 'L' | 'R'` for vigilance trials. A determined adversary could hard-code "always pick the side that is **not** L when `vig=L`." We accept this because: (a) such adversaries also fail real-trial quality at random and get caught by `vigilance_score < 1.0`, (b) implementing per-trial server-signed tokens would require a backend (defeating the static-host design), and (c) the cost of a single bad worker is bounded at $2.

---

## Troubleshooting

- **`http://localhost:3000/` shows "Missing hitId"**: expected. Use one of the URLs in [section 5 — Local testing URLs](#5-local-testing-urls).
- **`Invalid HIT ID` on `H_TUTORIAL`**: expected. `H_TUTORIAL` is a single-trial entry, not a 25-trial HIT. Use `H_0001` and the tutorial renders before trial 1 automatically.
- **Meshes do not render in the iframe**: open DevTools (F12) → Console + Network tabs:
  - `/data/{sample}/{hash16}/textured.obj` returns **404**: the dehydrated tree is missing or stale. Re-run `python3 texture-study/scripts/dehydrate_meshes.py`. If you previously deleted `.dehydrate_salt`, you must also re-run `gen_hits.py` and re-launch HITs (the hashes changed).
  - **`three.module.js` fails to load** (no Three.js, blank canvas): the network blocks `cdn.jsdelivr.net`. Use a different network or vendor Three.js locally under `docs/vendor/three/` and patch `viewer-pair.html`.
  - **`Load failed` status with no network errors**: the OBJ has no normals or its MTL is malformed. Inspect `console.error` — the viewer logs the real exception.
- **Vigilance trial does not show one gray side**: confirm the URL has `&vig=L` or `&vig=R` and that `dirL == dirR`. If `dirL != dirR`, the gray override is silently skipped (treated as a real trial).
- **`gen_hits.py` exits with `method_hash_map.json not found`**: run `dehydrate_meshes.py` first; `gen_hits.py` depends on its output.
- **`gen_hits.py` writes 0 entries**: cwd is wrong. Run from repo root, not from `texture-study/`.
- **`reconcile.py` rejects every worker**: inspect `texture-study/analysis/rejections.csv` for the per-row `feedback` column and `texture-study/analysis/reconcile_summary.txt` for the `vigilance histogram` line. If most rows show `vigilanceScore: 0.00`, the most likely cause is a stale `aliasmap_full.json` from before the last `gen_hits.py` run — re-run `gen_hits.py` and re-launch HITs.
- **`get-account-balance` returns `RequestError`**: link your AWS account to <https://requester.mturk.com/developer>.
- **`git push` exceeds 1 GB**: confirm you removed any large pre-existing artifacts (`node_modules/`, `.next/`, `public/_internal/`) from history. Run `du -sh texture-study/.git` — if huge, you may need a `git filter-repo` pass.
- **GH Pages serves an old version**: the deploy is async — give it 1–2 minutes after `git push` and then hard-reload (`Cmd+Shift+R`). Settings → Pages shows the deploy status.
- **GH Pages 404 on a custom subdomain after the CNAME file is in place**: re-tick the **Enforce HTTPS** box in Settings → Pages once the DNS check has passed; the cert provision can take 5–15 min.

---

## Contact

Owner: `kkh23834022@gmail.com`. Study UT_ID: `spotex_texture_v1_20260509`.
