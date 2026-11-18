from chatbot.ingest.anchors import Heading, anchors_of, headings_of, slugify


def test_headings_carry_level_text_and_anchor() -> None:
    md = "## Set up an SLA policy\n\ntext\n\n### Business hours ##\n"
    assert headings_of(md) == [
        Heading(2, "Set up an SLA policy", "set-up-an-sla-policy"),
        Heading(3, "Business hours", "business-hours"),
    ]


def test_hash_lines_inside_code_fences_are_not_headings() -> None:
    md = "## Search operators\n\n```\n#vip\n# owner:me\n```\n\n~~~\n## not a heading\n~~~\n"
    assert anchors_of(md) == ["search-operators"]


def test_slug_is_ascii_lowercase_hyphenated() -> None:
    assert slugify("Customise branding — PDF & Email!") == "customise-branding-pdf-email"
    assert slugify("Café menu") == "cafe-menu"


def test_sections_cut_where_headings_are_and_skip_code() -> None:
    from chatbot.ingest.anchors import sections_of

    md = "Intro.\n\n## A\n\nx\n\n```\n## not a heading\n```\n\n### B\n\ny\n"
    sections = sections_of(md)
    assert [s.heading.anchor if s.heading else None for s in sections] == [None, "a", "b"]
    assert [h.anchor for h in headings_of(md)] == ["a", "b"]
    assert "## not a heading" in sections[1].lines
    assert sections_of("## A\n\nx\n")[0].heading is not None, "no intro section without text"
