from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC_PATH = REPO_ROOT / "docs" / "filecoin_architecture_positioning.rst"

SECTION_HEADINGS = [
    "How py-libp2p fits in Filecoin architecture today",
    "Where py-libp2p is production-viable today",
    "Where Lotus/Forest (full implementations) are still required",
    "Suggested use cases: tooling, analytics, testnets, research",
    "Decision boundaries and anti-goals",
]


def _section_body(content: str, heading: str, next_heading: str | None) -> str:
    start = content.index(heading) + len(heading)
    end = content.index(next_heading, start) if next_heading else len(content)
    return content[start:end]


def test_architecture_positioning_doc_has_required_sections() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    for heading in SECTION_HEADINGS:
        assert heading in content


def test_architecture_positioning_sections_have_normative_links() -> None:
    content = DOC_PATH.read_text(encoding="utf-8")

    for index, heading in enumerate(SECTION_HEADINGS):
        next_heading = (
            SECTION_HEADINGS[index + 1] if index + 1 < len(SECTION_HEADINGS) else None
        )
        body = _section_body(content, heading, next_heading)
        assert "https://" in body, (
            f"missing normative source link in section: {heading}"
        )
