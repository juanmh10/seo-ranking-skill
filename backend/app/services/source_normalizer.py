from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException
from markdown_it import MarkdownIt

from app.models.source_document import SourceRepresentation

NORMALIZER_VERSION = "1.0.0"

EXTENSION_REPRESENTATIONS = {
    ".html": SourceRepresentation.HTML,
    ".htm": SourceRepresentation.HTML,
    ".txt": SourceRepresentation.TEXT,
    ".md": SourceRepresentation.MARKDOWN,
    ".markdown": SourceRepresentation.MARKDOWN,
    ".json": SourceRepresentation.JSON,
    ".jsonld": SourceRepresentation.JSON_LD,
    ".xml": SourceRepresentation.XML,
}

REPRESENTATION_MIME_TYPES = {
    SourceRepresentation.HTML: "text/html",
    SourceRepresentation.TEXT: "text/plain",
    SourceRepresentation.MARKDOWN: "text/markdown",
    SourceRepresentation.JSON: "application/json",
    SourceRepresentation.JSON_LD: "application/ld+json",
    SourceRepresentation.XML: "application/xml",
}


class SourceValidationError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class NormalizedSource:
    filename: str
    mime_type: str
    content_type: str
    representation: SourceRepresentation
    sha256: str
    byte_size: int
    raw_content: str
    normalized_content: str
    metadata: dict[str, object]


def normalize_source(
    *,
    filename: str,
    data: bytes,
    declared_content_type: str | None = None,
    representation: SourceRepresentation | None = None,
) -> NormalizedSource:
    safe_filename = Path(filename).name.strip()
    if not safe_filename:
        raise SourceValidationError("A source filename is required")
    if b"\x00" in data:
        raise SourceValidationError("Binary files are not supported", status_code=415)

    selected = representation or EXTENSION_REPRESENTATIONS.get(Path(safe_filename).suffix.lower())
    if selected is None:
        raise SourceValidationError("Unsupported source format", status_code=415)

    try:
        raw_content = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceValidationError(
            "Source content must be valid UTF-8", status_code=415
        ) from error

    normalized_content, extracted_metadata = _normalize(raw_content, selected)
    mime_type = REPRESENTATION_MIME_TYPES[selected]
    return NormalizedSource(
        filename=safe_filename,
        mime_type=mime_type,
        content_type=(declared_content_type or mime_type).split(";", maxsplit=1)[0].strip(),
        representation=selected,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        raw_content=raw_content,
        normalized_content=normalized_content,
        metadata={
            "normalizer_version": NORMALIZER_VERSION,
            "encoding": "utf-8",
            **extracted_metadata,
        },
    )


def _normalize(content: str, representation: SourceRepresentation) -> tuple[str, dict[str, object]]:
    if representation is SourceRepresentation.HTML:
        return _normalize_html(content)
    if representation is SourceRepresentation.MARKDOWN:
        return _normalize_markdown(content), {}
    if representation in {SourceRepresentation.JSON, SourceRepresentation.JSON_LD}:
        return _normalize_json(content)
    if representation is SourceRepresentation.XML:
        return _normalize_xml(content)
    return _clean_text(content), {}


def _normalize_html(content: str) -> tuple[str, dict[str, object]]:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    description_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    description = description_tag.get("content") if description_tag else None
    json_ld_blocks: list[object] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            json_ld_blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            json_ld_blocks.append(raw.strip())
    for element in soup(["script", "style", "template", "noscript"]):
        element.decompose()
    sections = [value for value in (title, description, soup.get_text("\n", strip=True)) if value]
    if json_ld_blocks:
        sections.append(
            "Structured data:\n" + json.dumps(json_ld_blocks, ensure_ascii=False, indent=2)
        )
    return _clean_text("\n\n".join(sections)), {
        "title": title,
        "description": description,
        "json_ld_blocks": len(json_ld_blocks),
    }


def _normalize_markdown(content: str) -> str:
    tokens = MarkdownIt("commonmark").parse(content)
    parts: list[str] = []
    for token in tokens:
        if token.type in {"inline", "fence", "code_block", "html_block"} and token.content.strip():
            if token.type == "html_block":
                html_text, _ = _normalize_html(token.content)
                parts.append(html_text)
            else:
                parts.append(token.content)
    return _clean_text("\n".join(parts))


def _normalize_json(content: str) -> tuple[str, dict[str, object]]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise SourceValidationError(
            f"Invalid JSON at line {error.lineno}, column {error.colno}"
        ) from error
    root_type = "array" if isinstance(parsed, list) else type(parsed).__name__
    return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True), {
        "root_type": root_type
    }


def _normalize_xml(content: str) -> tuple[str, dict[str, object]]:
    try:
        root = SafeElementTree.fromstring(content)
    except (DefusedXmlException, SafeElementTree.ParseError) as error:
        raise SourceValidationError("Invalid or unsafe XML content") from error
    parts: list[str] = []
    for element in root.iter():
        attributes = " ".join(f"{key}={value}" for key, value in sorted(element.attrib.items()))
        label = f"{element.tag} {attributes}".strip()
        text = (element.text or "").strip()
        parts.append(f"{label}: {text}" if text else label)
    return _clean_text("\n".join(parts)), {"root_tag": root.tag}


def _clean_text(content: str) -> str:
    normalized_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in content.splitlines()]
    result: list[str] = []
    previous_blank = False
    for line in normalized_lines:
        is_blank = not line
        if is_blank and previous_blank:
            continue
        result.append(line)
        previous_blank = is_blank
    return "\n".join(result).strip()
