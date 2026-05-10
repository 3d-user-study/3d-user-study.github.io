#!/usr/bin/env python3
"""One-time mesh dehydrator for the static-host (GitHub Pages) architecture.

The original architecture relied on Next.js middleware to map opaque aliases
(A..F) to method names (spotex, goatex, ...) at request time, so URLs never
exposed method names. GitHub Pages has no server-side code, so we instead
RENAME each method directory to an opaque sha256 hash of (sample, method, salt).

Result:
  texture-study/docs/data/{sample}/{hash16}/textured.{obj,mtl,png}
  texture-study/docs/data/{sample}/class_faces_gt.json

The salt is generated once and stored privately at scripts/.dehydrate_salt
(gitignored). With the salt, gen_hits.py can deterministically recompute the
same hashes when emitting the public trialMap.json. Without the salt, an
adversary cannot link a hash back to a method.

Idempotent: re-running with the same salt produces the same hashes; existing
files are left in place, missing files are added.

Usage (run from repo root):
  python3 texture-study/scripts/dehydrate_meshes.py
  python3 texture-study/scripts/dehydrate_meshes.py --mode move    # save disk

Outputs:
  texture-study/docs/data/{sample}/{hash16}/textured.{obj,mtl,png}
  texture-study/docs/data/{sample}/{corrupt_hash16}/textured.{obj,mtl,png}
  texture-study/docs/data/{sample}/class_faces_gt.json
                                                # public part face map
                                                # vigilance bait: shared OBJ
                                                # topology + random-noise PNG
                                                # so the prompted object renders
                                                # with an obviously-broken texture
  texture-study/scripts/method_hash_map.json   # PRIVATE: {sample: {method-or-_corrupt: hash}}
  texture-study/scripts/.dehydrate_salt        # PRIVATE: 256-bit hex secret
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_SALT_PATH = Path("texture-study/scripts/.dehydrate_salt")
DEFAULT_SOURCE = Path("portable_viewer/data")
DEFAULT_DEST = Path("texture-study/docs/data")
DEFAULT_MAP = Path("texture-study/scripts/method_hash_map.json")
HASH_LEN = 16  # 64 bits truncated sha256; collision prob ~5e-15 for 378 cells
PART_FACE_MAP = "class_faces_gt.json"

# Sentinel hashed identically to real methods (same salt guards corrupt dir
# name) but flagged separately so gen_hits.py picks it only for vigilance.
CORRUPT_METHOD = "_corrupt"

# Donor must share OBJ topology with the prompted object. spotex is one of the
# 5 shared-topology methods; mvadapter has its own UV layout and is unsuitable.
CORRUPT_OBJ_DONOR = "spotex"
CORRUPT_PNG_SIZE = 512
CORRUPT_PNG_SEED_BASE = 0xC0FFEE  # XOR with sample-name hash -> per-sample seed


def load_or_create_salt(path: Path) -> str:
    if path.exists():
        salt = path.read_text().strip()
        if len(salt) < 32:
            raise SystemExit(f"FATAL: salt at {path} is too short ({len(salt)} chars)")
        return salt
    salt = secrets.token_hex(32)  # 256-bit
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(salt + "\n")
    path.chmod(0o600)
    print(f"[salt] generated new 256-bit salt at {path}")
    return salt


def method_hash(sample: str, method: str, salt: str) -> str:
    h = hashlib.sha256(f"{sample}:{method}:{salt}".encode("utf-8")).hexdigest()
    return h[:HASH_LEN]


def _make_corrupt_png(sample: str, dest_path: Path) -> None:
    sample_hash = int(hashlib.sha256(sample.encode("utf-8")).hexdigest()[:8], 16)
    seed = (CORRUPT_PNG_SEED_BASE ^ sample_hash) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(CORRUPT_PNG_SIZE, CORRUPT_PNG_SIZE, 3), dtype=np.uint8)
    Image.fromarray(arr, mode="RGB").save(dest_path, format="PNG", optimize=True)


def _build_corrupt_dir(
    sample: str,
    sample_dir: Path,
    dest_dir: Path,
) -> int:
    donor_dir = sample_dir / CORRUPT_OBJ_DONOR
    if not donor_dir.is_dir():
        sys.exit(f"FATAL: donor method '{CORRUPT_OBJ_DONOR}' missing for {sample}")
    donor_obj = donor_dir / "textured.obj"
    donor_mtl = donor_dir / "textured.mtl"
    if not donor_obj.is_file() or not donor_mtl.is_file():
        sys.exit(f"FATAL: donor OBJ/MTL missing in {donor_dir}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for src, dst_name in ((donor_obj, "textured.obj"), (donor_mtl, "textured.mtl")):
        dst = dest_dir / dst_name
        if dst.exists():
            continue
        shutil.copy2(src, dst)
        n_written += 1

    png_path = dest_dir / "textured.png"
    if not png_path.exists():
        _make_corrupt_png(sample, png_path)
        n_written += 1
    return n_written


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                   help="source dir laid out as {sample}/{method}/textured.*")
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                   help="dest dir; will be laid out as {sample}/{hash16}/textured.*")
    p.add_argument("--map", type=Path, default=DEFAULT_MAP,
                   help="JSON output: {sample: {method: hash}}")
    p.add_argument("--salt-file", type=Path, default=DEFAULT_SALT_PATH,
                   help="private salt path; created if missing")
    p.add_argument("--mode", choices=["copy", "move"], default="copy",
                   help="copy = leave originals (safer); move = save disk")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would happen, write nothing")
    args = p.parse_args()

    if not args.source.is_dir():
        sys.exit(f"ERROR: source dir not found: {args.source}")

    salt = load_or_create_salt(args.salt_file)
    print(f"[salt] using salt at {args.salt_file} (len={len(salt)})")

    method_hash_map: dict[str, dict[str, str]] = {}
    samples = sorted([d for d in args.source.iterdir() if d.is_dir()])
    print(f"[scan] {len(samples)} sample dirs in {args.source}")

    n_dirs_planned = 0
    n_files_copied = 0
    n_files_skipped = 0
    seen_hashes: set[tuple[str, str]] = set()

    for sample_dir in samples:
        sample = sample_dir.name
        method_hash_map[sample] = {}
        methods = sorted([d for d in sample_dir.iterdir() if d.is_dir()])
        for method_dir in methods:
            method = method_dir.name
            h = method_hash(sample, method, salt)

            key = (sample, h)
            if key in seen_hashes:
                sys.exit(f"FATAL: hash collision at {sample}/{method} -> {h}")
            seen_hashes.add(key)
            method_hash_map[sample][method] = h

            dest_dir = args.dest / sample / h
            n_dirs_planned += 1
            if args.dry_run:
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            for src_file in sorted(method_dir.iterdir()):
                if not src_file.is_file():
                    continue
                dst_file = dest_dir / src_file.name
                if dst_file.exists():
                    n_files_skipped += 1
                    continue
                if args.mode == "copy":
                    shutil.copy2(src_file, dst_file)
                else:
                    shutil.move(str(src_file), str(dst_file))
                n_files_copied += 1

        corrupt_h = method_hash(sample, CORRUPT_METHOD, salt)
        corrupt_key = (sample, corrupt_h)
        if corrupt_key in seen_hashes:
            sys.exit(f"FATAL: hash collision at {sample}/{CORRUPT_METHOD} -> {corrupt_h}")
        seen_hashes.add(corrupt_key)
        method_hash_map[sample][CORRUPT_METHOD] = corrupt_h

        corrupt_dest = args.dest / sample / corrupt_h
        n_dirs_planned += 1
        if not args.dry_run:
            n_files_copied += _build_corrupt_dir(sample, sample_dir, corrupt_dest)

        src_part_map = sample_dir / PART_FACE_MAP
        if not src_part_map.is_file():
            sys.exit(f"FATAL: required part face map missing for {sample}: {src_part_map}")
        if not args.dry_run:
            dst_part_map = args.dest / sample / PART_FACE_MAP
            dst_part_map.parent.mkdir(parents=True, exist_ok=True)
            if dst_part_map.exists() and dst_part_map.read_bytes() == src_part_map.read_bytes():
                n_files_skipped += 1
            else:
                shutil.copy2(src_part_map, dst_part_map)
                n_files_copied += 1

    args.map.parent.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        args.map.write_text(json.dumps(method_hash_map, indent=2, sort_keys=True))

    print(f"[done] dirs_planned={n_dirs_planned} "
          f"files_copied={n_files_copied} files_skipped={n_files_skipped}")
    print(f"[map]  wrote {args.map} ({len(method_hash_map)} samples)")
    if args.mode == "move" and not args.dry_run:
        print("[note] originals MOVED. Verify dest before deleting empty source dirs.")
    elif not args.dry_run:
        print("[note] originals COPIED. Delete source tree manually after verification.")


if __name__ == "__main__":
    main()
