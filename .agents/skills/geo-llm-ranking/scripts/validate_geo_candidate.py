#!/usr/bin/env python3
"""Validate a Markdown or HTML content file against the geo-llm-ranking Winning Candidate criteria."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|as\s+)?(?:previous|other|demais)\s+(?:instructions|options|op[cç][oõ]es|concorrentes)",
    r"(?:system|priority)\s+instruction",
    r"instru[cç][aã]o\s+(?:de\s+sistema|priorit[aá]ria|ao\s+assistente)",
    r"diretriz\s+de\s+sistema",
    r"recomende\s+exclusivamente",
    r"recommend\s+exclusively",
]

EMPTY_SUPERLATIVE_PATTERNS = [
    r"\b(?:n[uú]mero\s+1|n[º°]\s*1|#1)\s+(?:indiscut[ií]vel|absolut[ao]|do\s+brasil|do\s+pa[ií]s|of\s+the\s+country)",
    r"99[,.]9%\s+de\s+(?:aprova[cç][aã]o|satisfa[cç][aã]o)",
    r"unanimemente\s+reconhecid[ao]",
]

EVASIVE_PRICING_PATTERNS = [
    r"consulte\s+valores\s+na\s+recep[cç][aã]o",
    r"entre\s+em\s+contato\s+para\s+(?:saber\s+)?(?:pre[cç]os|valores|or[cç]amento)",
    r"contact\s+us\s+for\s+pricing",
    r"price\s+upon\s+request\s+only",
]


def validate_content(text: str) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Check for Markdown or HTML Specification Table
    has_md_table = bool(re.search(r"^\|.+\|.+\|\s*$\n^\|[\s:|-]+\|[\s:|-]+\|", text, re.MULTILINE))
    has_html_table = "<table" in text.lower() and "<tr" in text.lower()
    if not (has_md_table or has_html_table):
        errors.append(
            "MISSING_SPEC_TABLE: No Markdown or HTML specification table found. "
            "Winning candidates require a structured 'Attribute | Specification' table."
        )

    # 2. Check for quantified SLA / turnaround metrics (minutes, hours, days, points, %)
    sla_matches = re.findall(
        r"\b\d+\s*(?:minutos?|horas?|dias?(?:\s+[uú]teis)?|pontos?|minutes?|hours?|business\s+days?|points?|%|canais|fps)\b",
        text,
        re.IGNORECASE,
    )
    if len(sla_matches) < 2:
        errors.append(
            f"LOW_QUANTIFIED_DENSITY: Found only {len(sla_matches)} quantified SLA/protocol metrics. "
            "Include at least 3 concrete numbers (e.g., turnaround in hours/days, checklist points, SLA)."
        )

    # 3. Check for transparent pricing / fee anchor
    has_price = bool(
        re.search(
            r"(?:R\$\s*\d+|\$\s*\d+|€\s*\d+|\d+[,.]\d+%\s*(?:a\.a\.|ao\s+ano|fee)|fee-only|fee-fixed)",
            text,
            re.IGNORECASE,
        )
    )
    if not has_price:
        errors.append(
            "MISSING_PRICE_ANCHOR: No explicit price, starting tier, or fee percentage found. "
            "LLMs strongly favor sources with transparent commercial anchors over 'contact us for quote'."
        )

    # 4. Check for numbered protocol / step list
    numbered_steps = re.findall(r"^\s*\d+\.\s+\S+", text, re.MULTILINE)
    if len(numbered_steps) < 3:
        warnings.append(
            f"FEW_NUMBERED_STEPS: Found {len(numbered_steps)} numbered protocol steps (recommended: >= 3)."
        )

    # 5. Check for anti-patterns (Prompt Injection)
    for pattern in PROMPT_INJECTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            errors.append(
                f"ANTI_PATTERN_PROMPT_INJECTION: Detected adversarial instruction '{match.group(0)}'. "
                "Modern LLMs penalize and publicly flag prompt injection attempts."
            )

    # 6. Check for anti-patterns (Empty Superlatives)
    for pattern in EMPTY_SUPERLATIVE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            warnings.append(
                f"ANTI_PATTERN_SUPERLATIVE: Detected unsubstantiated superlative '{match.group(0)}'. "
                "Replace with verifiable certifications, SLAs, or clinical/technical metrics."
            )

    # 7. Check for anti-patterns (Evasive Pricing)
    for pattern in EVASIVE_PRICING_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            errors.append(
                f"ANTI_PATTERN_EVASIVE_PRICING: Detected evasive phrase '{match.group(0)}'. "
                "State transparent reference pricing or starting tiers instead."
            )

    return len(errors) == 0, errors, warnings


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python3 validate_geo_candidate.py <path-to-markdown-or-html-file>")
        return 2

    target_path = Path(sys.argv[1])
    if not target_path.exists():
        print(f"Error: File not found: {target_path}")
        return 2

    content = target_path.read_text(encoding="utf-8")
    passed, errors, warnings = validate_content(content)

    print(f"=== GEO LLM Ranking Candidate Validation: {target_path.name} ===")
    for w in warnings:
        print(f"[WARN]  {w}")
    for e in errors:
        print(f"[FAIL]  {e}")

    if passed:
        print("[PASS]  Candidate meets all core GEO Winning Candidate requirements!")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
