#!/usr/bin/env python3
"""Deterministically package or verify the geo-llm-ranking skill zip archive."""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT_DIR / ".agents" / "skills" / "geo-llm-ranking"
ZIP_PATH = ROOT_DIR / "packages" / "geo-llm-ranking-skill.zip"
ARCHIVE_ROOT = "geo-llm-ranking"
FIXED_ZIP_TIME = (2026, 11, 1, 0, 0, 0)
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".DS_Store"}


def collect_skill_files(skill_dir: Path) -> list[Path]:
    """Return sorted publishable files inside the skill directory."""
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill directory not found: {skill_dir}")
    files: list[Path] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts) or path.suffix == ".pyc":
            continue
        files.append(path)
    if not files:
        raise RuntimeError(f"No files found inside skill directory: {skill_dir}")
    return files


def build_zip(skill_dir: Path = SKILL_DIR, zip_path: Path = ZIP_PATH) -> Path:
    """Create a deterministic zip archive from the skill directory."""
    files = collect_skill_files(skill_dir)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in files:
            rel_path = file_path.relative_to(skill_dir).as_posix()
            arcname = f"{ARCHIVE_ROOT}/{rel_path}"
            info = zipfile.ZipInfo(filename=arcname, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o755 << 16 if file_path.suffix == ".py" else 0o644 << 16
            zf.writestr(info, file_path.read_bytes())
    return zip_path


def verify_zip(skill_dir: Path = SKILL_DIR, zip_path: Path = ZIP_PATH) -> tuple[bool, list[str]]:
    """Verify that the packaged zip matches the skill directory file-for-file."""
    errors: list[str] = []
    if not zip_path.is_file():
        return False, [f"Skill zip archive missing: {zip_path}"]

    expected_files = {
        f"{ARCHIVE_ROOT}/{path.relative_to(skill_dir).as_posix()}": hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in collect_skill_files(skill_dir)
    }

    with zipfile.ZipFile(zip_path, "r") as zf:
        actual_files: dict[str, str] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            actual_files[info.filename] = hashlib.sha256(zf.read(info.filename)).hexdigest()

    missing = sorted(set(expected_files) - set(actual_files))
    extra = sorted(set(actual_files) - set(expected_files))
    if missing:
        errors.append(f"Missing files in zip: {missing}")
    if extra:
        errors.append(f"Unexpected extra files in zip: {extra}")

    for name in sorted(set(expected_files) & set(actual_files)):
        if expected_files[name] != actual_files[name]:
            errors.append(f"Content mismatch for {name}")

    return len(errors) == 0, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that packages/geo-llm-ranking-skill.zip matches .agents/skills/geo-llm-ranking",
    )
    args = parser.parse_args()

    if args.check:
        ok, errors = verify_zip()
        if not ok:
            for err in errors:
                print(f"[FAIL] {err}")
            return 1
        print(f"[PASS] {ZIP_PATH.relative_to(ROOT_DIR)} matches {SKILL_DIR.relative_to(ROOT_DIR)}")
        return 0

    out_path = build_zip()
    print(f"[OK] Packaged {out_path.relative_to(ROOT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
