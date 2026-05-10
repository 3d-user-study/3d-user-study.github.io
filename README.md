# texture-study

MTurk-driven user study to rank 6 part-aware 3D mesh texture-generation methods (`spotex` (ours), `goatex`, `mvadapter`, `TEXGen`, `paint3d`, `syncmvd`) across 54 samples using **Plackett-Luce full-ranking** (drag-to-reorder 6-method list per trial).

This is a **pure static site** served from GitHub Pages (no server, no Next.js, no Node). The study shell lives in `docs/index.html` + `docs/viewer-rank.html` + `docs/trialMap.json` + 1134 mesh files under `docs/data/{sample}/{hash16}/` (54 samples × (6 real methods + 1 corrupt vigilance variant) × 3 files). Mesh directories are hash-anonymized (sha256 truncated to 16 hex chars, salted with a private secret) so method identity never leaks to the client. The corrupt-mesh vigilance variant uses spotex's mesh topology with a deterministic random RGB-noise PNG and is hashed identically to real methods so it is indistinguishable from a real slot to the client. MTurk delivers worker query params (`hitId`, `assignmentId`, `workerId`, `turkSubmitTo`) in the iframe URL; the static page consumes them, gates consent, runs 25 trials (each a drag-to-rank of 6 textured meshes A–F with a generation prompt), and POSTs the per-trial 6-char `A..F` permutations to the standard MTurk `externalSubmit` endpoint.

> This README is owner-only documentation. It lives at the repo root, **outside** `docs/`, so GitHub Pages will not publish it.

---

## Pipeline overview

```
    +--------------------+      +-----------------+      +--------------------+      +------------------+
    | dehydrate_meshes.py|----->|   gen_hits.py   |----->|  create_hit_type   |----->|  launch_hits.py  |
    |  (one-time prep)   |      |  (offline prep) |      |  (one-time per run)|      |  (36 HITs)       |
    +--------------------+      +-----------------+      +--------------------+      +------------------+
            |                            |                                                     |
            v                            v                                                     v
    +-----------------------+   +---------------------+                            +------------------+
    | docs/data/{sample}/   |   | scripts/            |                            |  MTurk workers   |
    |   {hash16}/textured.* |   |   method_hash_map   |                            |  (24h lifetime)  |
    | (real + corrupt vig)  |   |   .dehydrate_salt   |                            +--------+---------+
    | scripts/.dehydrate    |   |   aliasmap_full     |                                     |
    |   _salt (PRIVATE)     |   | docs/trialMap.json  |                                     v
    | scripts/method_hash   |   |   (PUBLIC, no leak) |                            +-----------------+
    |   _map (PRIVATE)      |   +---------------------+                            | Batch_xxxx.csv  |
    +-----------------------+                                                      +--------+--------+
                                                                                            |
    +------------------+      +------------+      +-----------------+                       |
    |   aggregate.py   | <--- |  fit_pl.py | <--- |  reconcile.py   | <---------------------+
    | (paired bootstrap)      | (per-sample PL)   | (CSV -> rankings)
    +------------------+      +------------+      +-----------------+
```

Phases: `dehydrate_meshes` (once) → `gen_hits` (offline) → `git push` → enable GH Pages → `create_hit_type` (MTurk) → `launch_hits` (MTurk) → workers complete → download `Batch_results.csv` → `reconcile` → `fit_pl` → `aggregate`.

---

## Prerequisites

- **git** ≥ 2.30 + a GitHub account (public repo required for free Pages tier)
- **Python** ≥ 3.10 (we tested on 3.13.12)
- **AWS** account with MTurk Requester linked at <https://requester.mturk.com/>
- **MTurk balance** sized for the chosen reward × 36 HITs + 40% fee + buffer (e.g. $2.00 reward → ~$110, $5.00 reward → ~$260; ranking is more cognitive load than pairwise so reward should reflect that)
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

- `texture-study/docs/data/{sample}/{hash16}/textured.{obj,mtl,png}` — 378 hash dirs (54 samples × (6 real + 1 corrupt-vigilance) methods), 1134 files, ~1014 MB
- `texture-study/scripts/.dehydrate_salt` — **PRIVATE** 256-bit hex salt (chmod 600, gitignored)
- `texture-study/scripts/method_hash_map.json` — **PRIVATE** `{sample: {method: hash16}}` lookup including a `_corrupt` key per sample (gitignored)

The corrupt-vigilance variant per sample uses spotex's mesh topology with a deterministic random RGB-noise PNG (seeded from `SEED_BASE ^ sha256(sample)`) so the corrupt slot is hashed identically to real methods and is structurally indistinguishable from the client side.

Re-running with the same salt is idempotent — hashes stay stable. Deleting `.dehydrate_salt` and re-running rotates all hashes (and invalidates any in-flight HITs).

### 3. Generate HIT inputs (offline, deterministic)

```bash
python3 texture-study/scripts/gen_hits.py
```

This writes 2 artifacts:

- `texture-study/docs/trialMap.json` — **PUBLIC**; trial defs as `{i, prompt: {FULL, parts: [{label, caption}]}, slots: [{slot: 'A'..'F', dir}]}` per HIT. Method names and the `kind` flag (main vs vigilance) are both absent so the worker cannot distinguish vigilance from real trials.
- `texture-study/scripts/aliasmap_full.json` — **OFFLINE**; private form `{trials: [{i, kind, sample, prompt, slots: [{slot, method, dir}], corrupt_slot?}]}` per HIT. Used by `reconcile.py` for vigilance scoring (`corrupt_slot` must be ranked last) and ranking-to-method expansion.

Default knobs (override only if you understand the implications):

```
--n_hits      36   # 54 samples * ~13-14 votes / 20 main per HIT
--n_main      20   # main ranking trials per HIT (each: 6 real methods, full ranking)
--n_vigilance  5   # vigilance ranking trials per HIT (each: 5 real + 1 corrupt slot, full ranking; corrupt must be ranked last)
--seed      2024
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

#### Mode D — Direct ranking viewer (skip consent, render 6 meshes only)

The fastest way to verify Three.js + the asset pipeline + the drag-to-reorder UI are working. Bypasses `index.html` entirely. The viewer reads its trial spec from `?hitId=<H_0001..H_0036>&i=<0..24>` and looks up `trialMap.json` directly:

```
http://localhost:3000/viewer-rank.html?hitId=H_0001&i=0
```

When loaded inside an iframe (the production path), the viewer posts `viewer-rank-ready` and `rank-update` messages back to the parent (`index.html`); when loaded standalone (this Mode D path) it suppresses postMessage but still renders + lets you drag rows so you can verify the asset pipeline visually. You should see six side-by-side textured meshes within ~5 seconds and a 6-row draggable list under them. To find the corrupt slot for a vigilance trial, cross-reference `scripts/aliasmap_full.json` for that `(hitId, i)` and look at `corrupt_slot`.

#### Valid `hitId` values

- `H_0001` … `H_0036` — real HITs (20 main + 5 vigilance trials each, 25 trials total)
- `H_TUTORIAL` — tutorial entry only (1 trial, used internally; do **not** pass as a worker `hitId` — the trial-count check rejects it as `Invalid HIT ID`).

`H_TEST` does **not** exist (deliberately excluded per invariant #2).

### 6. Smoke test

Minimum sanity checks against the local server:

```bash
# 1. index.html + viewer-rank.html serve
curl -sI http://localhost:3000/index.html       | head -1   # expect 200
curl -sI http://localhost:3000/viewer-rank.html | head -1   # expect 200

# 2. trialMap.json serves and contains no method names or _corrupt token
curl -s http://localhost:3000/trialMap.json | grep -E "spotex|goatex|mvadapter|TEXGen|paint3d|syncmvd|_corrupt"
# expect: NO MATCHES (empty output, exit code 1)

# 3. Mesh assets serve (use any dir from trialMap.json's slots[].dir)
curl -sI "http://localhost:3000/data/19_1d3ad2a23c444d5abfabf1a48eeb8c84/e9f070389851d69f/textured.obj" | head -1   # expect 200

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

> **The first push is ~1014 MB** (mostly `docs/data/` — 6 real + 1 corrupt-vigilance variant per sample). At 10 Mbps upload that is ~14 minutes. GitHub's hard per-file limit is 100 MB; our largest file is ~1.4 MB so you are well under. Repo soft cap is 1 GB; we sit just above it but Pages-hosted repos are not strictly enforced at 1 GB — incremental pushes are fine. If push is rejected for size, drop the corrupt-vigilance variants for samples not in the active HIT set (advanced; talk to the owner first).

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

# 2. Method-name and _corrupt leak check
curl -s "$DEPLOY_URL/trialMap.json" | grep -cE "spotex|goatex|mvadapter|TEXGen|paint3d|syncmvd|_corrupt"
# expect 0

# 3. Mesh asset reachable (use any slots[].dir from trialMap.json)
curl -sI "$DEPLOY_URL/data/19_1d3ad2a23c444d5abfabf1a48eeb8c84/e9f070389851d69f/textured.obj" | head -1
# expect 200

# 4. Private artifacts must 404 (they were never under /docs)
curl -s -o /dev/null -w "%{http_code}\n" "$DEPLOY_URL/scripts/method_hash_map.json"   # expect 404
curl -s -o /dev/null -w "%{http_code}\n" "$DEPLOY_URL/scripts/.dehydrate_salt"        # expect 404

# 5. Full Mode-B URL renders the consent screen (visual check in browser)
open "$DEPLOY_URL/?hitId=H_0001&workerId=PREVIEW&assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE"
```

Run `bash texture-study/scripts/verify_deploy.sh` against `$DEPLOY_URL` before launching real HITs — it covers static endpoints, structural invariants on the live `trialMap.json` (36 production HITs + tutorial, 25 trials per HIT, 6 unique slots, prompt schema, no method/_corrupt leak), sample mesh reachability, and Pages metadata.

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
# Production endpoint balance (size to chosen reward × 36 HITs × 1.4 fee multiplier)
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

# 3. Real sandbox launch (regenerate with `gen_hits.py --n_hits 3` for a tiny pilot,
#    or just launch all 36 — sandbox is free play money)
python3 texture-study/scripts/launch_hits.py \
    --sandbox \
    --base_url <DEPLOY_URL>
```

Visit <https://workersandbox.mturk.com/> with a separate sandbox worker account and complete a HIT end-to-end.

### Phase 5 — production launch

```bash
# 1. Create the production HIT type. PICK THE REWARD CAREFULLY.
#    Ranking 6 textured meshes per trial × 25 trials is more cognitive load
#    than pairwise; expect ~10 min per HIT. Match the reward accordingly.
#    The script intentionally has NO --reward default to force an explicit choice.
python3 texture-study/scripts/create_hit_type.py \
    --reward 5.00 \
    --profile mturk
# -> export MTURK_HIT_TYPE_ID=...

# 2. Dry-run against production endpoint (no API calls)
python3 texture-study/scripts/launch_hits.py \
    --dry_run \
    --base_url <DEPLOY_URL>

# 3. Real production launch (36 HITs, MaxAssignments=1, 24h lifetime)
python3 texture-study/scripts/launch_hits.py \
    --base_url <DEPLOY_URL>
# -> writes texture-study/scripts/launch_log.csv
```

### Phase 6 — monitor

- Day 1-2: check assignment completion in <https://requester.mturk.com/>.
- Watch for vigilance-fail clusters; reject vigilance score < 1.0 (i.e. any of the 5 vigilance trials with the corrupt slot NOT placed at rank 6 / last).

### Phase 7 — analysis

After the HIT lifetime expires (or all 36 HITs are submitted), download the results CSV from the Requester console (`Batch_xxxx_batch_results.csv`).

```bash
# 1. Reconcile MTurk results -> per-trial rankings table
#    Add `--worker_cap 1` for production to enforce 1 approval per workerId
#    (default `--worker_cap=0` is fine for sandbox pilot).
python3 texture-study/scripts/reconcile.py \
    --results_csv path/to/Batch_xxxx_batch_results.csv
# -> writes texture-study/analysis/rankings.csv
#    + texture-study/analysis/approvals.csv
#    + texture-study/analysis/rejections.csv
#    + texture-study/analysis/reconcile_summary.txt

# 2. Per-sample Plackett-Luce MLE + bootstrap CIs
python3 texture-study/scripts/fit_pl.py
# -> texture-study/analysis/pl_per_sample.csv

# (Optional) Add `--include_vigilance` to fit_pl.py to also use vigilance trials
# as 5-method partial rankings (the corrupt slot is stripped). Default is
# main trials only; the vigilance pass criterion already proves the corrupt
# slot was placed last so the remaining 5 methods form a clean ranking.

# 3. Aggregate ranking via paired bootstrap over samples
python3 texture-study/scripts/aggregate.py
# -> texture-study/analysis/pl_aggregate.csv
```

End-to-end synthetic-data validation (already run): with ground-truth Plackett-Luce log-strengths `[1.0, 0.6, 0.2, -0.2, -0.6, -1.0]` for `[spotex, goatex, mvadapter, TEXGen, paint3d, syncmvd]` and 14 rankings per sample × 54 samples, the aggregate ranking exactly matched truth (Spearman ρ = 1.0, all CI bounds sane).

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
│   ├── viewer-rank.html            # iframe-embedded Three.js 6-mesh ranking viewer (drag-to-reorder)
│   ├── trialMap.json               # PUBLIC method-free trial defs (gen_hits output)
│   ├── data/                       # 54 × 7 = 378 hash dirs (6 real + 1 corrupt-vig per sample), 1134 files, ~1014 MB
│   │   └── {sample}/{hash16}/textured.{obj,mtl,png}
│   └── CNAME                       # (optional) custom domain hostname
│
└── scripts/                        # offline-only — NOT under /docs, never published
    ├── requirements.txt
    ├── dehydrate_meshes.py         # one-time mesh hashing pass (real + corrupt variants)
    ├── .dehydrate_salt             # PRIVATE 256-bit hex salt (chmod 600, gitignored)
    ├── method_hash_map.json        # PRIVATE {sample: {method: hash16}} incl. _corrupt key (gitignored)
    ├── gen_hits.py                 # offline prep (2 artifacts; ranking trial schema)
    ├── aliasmap_full.json          # OFFLINE expanded HIT/trial map with corrupt_slot (gitignored)
    ├── create_hit_type.py          # MTurk HITType creator (--reward REQUIRED)
    ├── launch_hits.py              # MTurk HIT launcher (boto3)
    ├── launch_log.csv              # written by launch_hits.py (gitignored)
    ├── reconcile.py                # Batch_results.csv -> rankings.csv (vigilance: corrupt last)
    ├── fit_pl.py                   # per-sample Plackett-Luce MLE + bootstrap CIs
    ├── aggregate.py                # paired-bootstrap aggregate ranking
    └── verify_deploy.sh            # live deploy structural-invariant probe
```

---

## Critical invariants — DO NOT BREAK

1. **Method identity never reaches the client.** Mesh dirs use `{sample}/{hash16}` where `hash16 = sha256(f"{sample}:{method}:{salt}").hexdigest()[:16]` (with `method = "_corrupt"` for the vigilance variant). `docs/trialMap.json` contains only hash dirs, prompts, and the trial index `i`; never raw method names, never the `_corrupt` token, and never a `kind` flag (so the worker cannot distinguish vigilance from main trials). Verified by `verify_deploy.sh`. If you change `dehydrate_meshes.py` or `gen_hits.py`, re-run that script.

2. **`scripts/` lives OUTSIDE `docs/`.** This is not cosmetic — it is the security boundary. GitHub Pages publishes only `/docs`, so `scripts/.dehydrate_salt` and `scripts/method_hash_map.json` are not reachable over HTTP. Do **not** move any script or private artifact under `docs/`.

3. **`scripts/.dehydrate_salt` is the master secret.** If it leaks, an attacker can recompute every `(sample, method) → hash16` mapping (including `_corrupt`) and break both method anonymization and vigilance. Treat it like a private key. It is `chmod 600` and gitignored.

4. **`scripts/aliasmap_full.json`, `scripts/method_hash_map.json`, `scripts/launch_log.csv` must NEVER ship to git.** `.gitignore` enforces this. Verify with `git check-ignore scripts/.dehydrate_salt scripts/method_hash_map.json scripts/aliasmap_full.json` — all three should print their paths.

5. **`create_hit_type.py --reward` is intentionally required (no default).** This forces a conscious sandbox-vs-production choice. $0.01 is sandbox-only; the production reward should reflect ranking 6 meshes × 25 trials cognitive load (e.g. ~$5).

6. **`random.seed(2024)`** in `gen_hits.py`, `fit_pl.py`, and `aggregate.py` is reproducibility-locked. Do not change without re-validating the synthetic PL recovery test.

7. **Coverage math:** 54 samples × ~13–14 votes ÷ 20 main trials per HIT = 36 HITs. Changing `--n_main` or `--n_vigilance` invalidates this; budget and schedule both downstream.

8. **Vigilance criterion is full-pass only:** all 5 vigilance trials must place the corrupt slot at rank 6. Threshold is 1.0 (not majority). Fewer than 5 correct = reject.

---

## Limitations & residual risk

### Hash equivalence-class attack (accepted)

A worker who completes many HITs can cluster the dirs they see by hash and infer "all dirs with hash X for sample Y are the same method," even without knowing which method. This degrades to a 7-class clustering attack per sample (6 real + 1 corrupt). We accept this because: (a) MTurk per-HIT `MaxAssignments=1` plus the localStorage UT gate (below) limit any single worker to ~1 HIT in our pool, and (b) the absolute method-name leak (which would let an attacker bias votes toward `spotex` to inflate our paper) is structurally impossible with hashing.

### UniqueTurker replacement (best-effort + post-hoc)

The original UniqueTurker service (`uniqueturker.myleott.com`) shut down in 2022. We replaced it with a localStorage-based gate in `docs/index.html`:

- On HIT submit, the page sets `localStorage["ut:<UT_ID>:<workerId>"] = "1"`.
- On any subsequent HIT load with the same `workerId`, the page refuses with `You have already participated in this study.`

This is **bypassable** by clearing browser storage, using incognito, or switching browser/device. For true enforcement, `scripts/reconcile.py` ships with an opt-in `--worker_cap N` flag that applies a post-hoc per-worker cap on accepted submissions (sorted by `SubmitTime`, with `AssignmentId` tiebreaker; excess submissions are demoted to `rejections.csv` with the `worker_cap_exceeded` feedback line). The default `--worker_cap=0` is **disabled** (preserves prior behavior — adequate for sandbox pilot). For the production launch, run `python3 texture-study/scripts/reconcile.py --results_csv ... --worker_cap 1` to guarantee at most one approved submission per `workerId`.

### `H_TUTORIAL` exposure (accepted)

Anyone who reads `docs/trialMap.json` sees a `H_TUTORIAL` entry. Workers cannot accept this as a real HIT (MTurk only serves IDs you actually launch via `launch_hits.py`), and the consent screen rejects it as `Invalid HIT ID` if anyone manually navigates with `?hitId=H_TUTORIAL`. The tutorial trial is rendered as part of every real HIT before trial 1 begins.

### Vigilance via corrupt-mesh slot (no client-side flag)

Unlike the prior pairwise design, vigilance trials in this ranking design are NOT flagged in the public trial map. Each vigilance trial slots a corrupt-texture mesh (random RGB noise PNG on spotex's mesh topology) into one of the 6 positions A–F. The worker must place this slot at rank 6 (last) for the trial to count as a vigilance pass. Because:

- the corrupt slot is hashed identically to real slots (`sha256(sample:_corrupt:salt)[:16]`),
- the public `trialMap.json` has no `kind` flag, no `corrupt_slot` field, and never contains the `_corrupt` token,
- the corrupt mesh shares spotex's topology so OBJ headers cannot distinguish it,

a malicious client that scrapes the trial map cannot identify which trials are vigilance or which slot is corrupt without pixel-level inspection of every PNG (and even then, "noise" is the cue — workers who do not actually look at textures will fail vigilance). We accept residual risk from determined adversaries who DO look at textures because the cost per bad worker is bounded by the per-HIT reward.

---

## Troubleshooting

- **`http://localhost:3000/` shows "Missing hitId"**: expected. Use one of the URLs in [section 5 — Local testing URLs](#5-local-testing-urls).
- **`Invalid HIT ID` on `H_TUTORIAL`**: expected. `H_TUTORIAL` is a single-trial entry, not a 25-trial HIT. Use `H_0001` and the tutorial renders before trial 1 automatically.
- **Meshes do not render in the iframe**: open DevTools (F12) → Console + Network tabs:
  - `/data/{sample}/{hash16}/textured.obj` returns **404**: the dehydrated tree is missing or stale. Re-run `python3 texture-study/scripts/dehydrate_meshes.py`. If you previously deleted `.dehydrate_salt`, you must also re-run `gen_hits.py` and re-launch HITs (the hashes changed).
  - **`three.module.js` fails to load** (no Three.js, blank canvas): the network blocks `cdn.jsdelivr.net`. Use a different network or vendor Three.js locally under `docs/vendor/three/` and patch `viewer-rank.html`.
  - **`Load failed` status with no network errors**: the OBJ has no normals or its MTL is malformed. Inspect `console.error` — the viewer logs the real exception.
- **Drag-to-reorder feels unresponsive in the parent page**: the iframe and the parent communicate over `postMessage`. Open DevTools and look for `viewer-rank-ready` and `rank-update` messages. If absent, the iframe's `window.parent !== window` check is failing and standalone-mode suppression is active — you are probably loading `viewer-rank.html` directly instead of through `index.html`.
- **`gen_hits.py` exits with `method_hash_map.json not found`**: run `dehydrate_meshes.py` first; `gen_hits.py` depends on its output.
- **`gen_hits.py` writes 0 entries**: cwd is wrong. Run from repo root, not from `texture-study/`.
- **`reconcile.py` rejects every worker**: inspect `texture-study/analysis/rejections.csv` for the per-row `feedback` column and `texture-study/analysis/reconcile_summary.txt` for the `vigilance histogram` line. If most rows show `vigilanceScore: 0.00`, the most likely cause is a stale `aliasmap_full.json` from before the last `gen_hits.py` run — re-run `gen_hits.py` and re-launch HITs. If the histogram shows mostly 4/5 (one off), the worker is likely a careless human placing the corrupt slot at rank 5 instead of 6 — threshold is intentionally strict (1.0) per plan.
- **`get-account-balance` returns `RequestError`**: link your AWS account to <https://requester.mturk.com/developer>.
- **`git push` exceeds 1 GB**: confirm you removed any large pre-existing artifacts (`node_modules/`, `.next/`, `public/_internal/`) from history. Run `du -sh texture-study/.git` — if huge, you may need a `git filter-repo` pass.
- **GH Pages serves an old version**: the deploy is async — give it 1–2 minutes after `git push` and then hard-reload (`Cmd+Shift+R`). Settings → Pages shows the deploy status.
- **GH Pages 404 on a custom subdomain after the CNAME file is in place**: re-tick the **Enforce HTTPS** box in Settings → Pages once the DNS check has passed; the cert provision can take 5–15 min.

---

## Contact

Owner: `kkh23834022@gmail.com`. Study UT_ID: `spotex_texture_v1_20260509`.
