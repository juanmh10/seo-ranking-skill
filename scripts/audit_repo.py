#!/usr/bin/env python3
"""Audit skill integrity, eval artifacts, zip parity, and exposure hygiene across the repo."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT_DIR / ".agents" / "skills" / "geo-llm-ranking"

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    "data",
    ".playwright-cli",
    "dist",
    "output",
    "input",
    "deprecated",
    "trash",
}

TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".html",
    ".css",
    ".svg",
    ".ini",
    ".mako",
}

EXPOSURE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("unix_home_path", re.compile(r"/home/[A-Za-z0-9_.-]+")),
    ("macos_user_path", re.compile(r"/Users/[A-Za-z0-9_.-]+")),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+")),
    ("file_uri", re.compile(r"file:///(?:home|Users|[A-Za-z]:)")),
    ("gcp_project_leak", re.compile(r"llm-api-\d+")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{20,}")),
    ("github_token", re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}")),
    ("private_key_header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]


def audit_skill_structure() -> list[str]:
    """Validate SKILL.md frontmatter, linked resources, and validator script behavior."""
    errors: list[str] = []
    skill_md = SKILL_DIR / "SKILL.md"
    if not skill_md.is_file():
        return [f"Missing SKILL.md at {skill_md}"]

    content = skill_md.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not fm_match:
        errors.append("SKILL.md is missing valid YAML frontmatter")
    else:
        fm = fm_match.group(1)
        if "name: geo-llm-ranking" not in fm:
            errors.append("SKILL.md frontmatter missing 'name: geo-llm-ranking'")
        if "description:" not in fm:
            errors.append("SKILL.md frontmatter missing 'description'")

    for rel in (
        "resources/winning-candidate-template.md",
        "examples/winning-vs-losing-examples.md",
        "scripts/validate_geo_candidate.py",
    ):
        if not (SKILL_DIR / rel).is_file():
            errors.append(f"Missing skill asset: {rel}")

    sys.path.insert(0, str(SKILL_DIR / "scripts"))
    from validate_geo_candidate import (
        validate_content,  # type: ignore[import-not-found]
    )

    examples_path = SKILL_DIR / "examples" / "winning-vs-losing-examples.md"
    if examples_path.is_file():
        blocks = re.findall(r"```markdown\n(.*?)```", examples_path.read_text("utf-8"), re.DOTALL)
        if len(blocks) < 3:
            errors.append("Expected at least 3 markdown example blocks in winning-vs-losing-examples.md")
        else:
            ok_a, errs_a, _ = validate_content(blocks[0])
            ok_b, errs_b, _ = validate_content(blocks[1])
            ok_win, errs_win, _ = validate_content(blocks[2])
            if ok_a or not errs_a:
                errors.append("Validator unexpectedly passed Losing Pattern A")
            if ok_b or not any("ANTI_PATTERN_PROMPT_INJECTION" in e for e in errs_b):
                errors.append("Validator failed to flag prompt injection in Losing Pattern B")
            if not ok_win or errs_win:
                errors.append(f"Validator failed on canonical Winning Pattern: {errs_win}")

    return errors


def audit_evals() -> list[str]:
    """Validate syntax and integrity of versioned eval JSON files."""
    errors: list[str] = []
    expected_json_files = [
        ROOT_DIR / "evals" / "counterfactual-study" / "metrics.json",
        ROOT_DIR / "evals" / "counterfactual-study" / "manifest.json",
        ROOT_DIR / "evals" / "30-niche-evals" / "results_30_evals.json",
        ROOT_DIR / "evals" / "30-niche-evals" / "samples_batch_1.json",
        ROOT_DIR / "evals" / "30-niche-evals" / "samples_batch_2.json",
        ROOT_DIR / "examples" / "sample_packs" / "veterinary-recommendation" / "manifest.json",
    ]
    for path in expected_json_files:
        if not path.is_file():
            errors.append(f"Missing eval/sample JSON file: {path.relative_to(ROOT_DIR)}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"Invalid JSON in {path.relative_to(ROOT_DIR)}: {exc}")
            continue
        if path.name == "results_30_evals.json" and (not isinstance(data, list) or len(data) != 30):
            errors.append("results_30_evals.json must contain 30 entries")
        if path.name.startswith("samples_batch_") and len(data.get("samples", [])) != 15:
            errors.append(f"{path.name} must contain 15 samples")
    return errors


def audit_zip_parity() -> list[str]:
    """Verify the packaged skill zip matches the canonical skill directory."""
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    from package_skill import verify_zip  # type: ignore[import-not-found]

    ok, errors = verify_zip()
    return [] if ok else errors


def list_candidate_files() -> list[Path]:
    """Return tracked and non-ignored candidate files when in git, otherwise walk workspace."""
    git_dir = ROOT_DIR / ".git"
    if git_dir.exists():
        res = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT_DIR,
            capture_output=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            rel_paths = [p for p in res.stdout.decode("utf-8").split("\0") if p]
            return [ROOT_DIR / p for p in rel_paths if (ROOT_DIR / p).is_file()]

    files: list[Path] = []
    for path in sorted(ROOT_DIR.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def audit_exposure() -> list[str]:
    """Scan repository files for local paths, credentials, Zone.Identifier, or .env leaks."""
    errors: list[str] = []
    for path in list_candidate_files():
        rel = path.relative_to(ROOT_DIR).as_posix()
        if path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example":
            errors.append(f"Forbidden env file tracked/present: {rel}")
            continue
        if "Zone.Identifier" in path.name or path.suffix in {".db", ".sqlite", ".sqlite3"}:
            errors.append(f"Forbidden local artifact tracked/present: {rel}")
            continue
        if path.suffix not in TEXT_EXTENSIONS and path.name not in {".env.example", ".gitignore"}:
            continue
        if rel == "scripts/audit_repo.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in EXPOSURE_PATTERNS:
            match = pattern.search(text)
            if match:
                errors.append(f"Exposure check '{label}' matched in {rel}: {match.group(0)}")
    return errors


def main() -> int:
    checks = [
        ("Skill structure & validator", audit_skill_structure),
        ("Skill zip parity", audit_zip_parity),
        ("Eval artifacts", audit_evals),
        ("Exposure & hygiene", audit_exposure),
    ]
    all_errors: list[str] = []
    for name, fn in checks:
        errs = fn()
        if errs:
            print(f"[FAIL] {name}:")
            for err in errs:
                print(f"  - {err}")
            all_errors.extend(errs)
        else:
            print(f"[PASS] {name}")

    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
