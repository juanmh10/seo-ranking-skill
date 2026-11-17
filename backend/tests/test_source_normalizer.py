import pytest

from app.models.source_document import SourceRepresentation
from app.services.source_normalizer import SourceValidationError, normalize_source


def test_html_normalization_preserves_structured_data_without_scripts() -> None:
    source = normalize_source(
        filename="clinic.html",
        data=(
            b"<html><head><title>Clinic A</title>"
            b'<script type="application/ld+json">{"name":"Clinic A"}</script>'
            b"<script>alert(1)</script></head>"
            b"<body><h1>Trusted care</h1></body></html>"
        ),
        declared_content_type="text/html",
    )

    assert source.representation is SourceRepresentation.HTML
    assert "Trusted care" in source.normalized_content
    assert "Structured data" in source.normalized_content
    assert "alert(1)" not in source.normalized_content
    assert source.metadata["json_ld_blocks"] == 1


def test_json_normalization_is_canonical() -> None:
    source = normalize_source(filename="source.json", data=b'{"z": 1, "a": 2}')

    assert source.normalized_content.index('"a"') < source.normalized_content.index('"z"')


def test_unsafe_xml_is_rejected() -> None:
    with pytest.raises(SourceValidationError, match="unsafe XML"):
        normalize_source(
            filename="source.xml",
            data=b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>',
        )
