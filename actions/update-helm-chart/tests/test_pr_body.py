from settings_sync.flatten import LeafType
from settings_sync.pr_body import (
    render_release_line,
    render_settings_section,
)


def test_release_line_uses_markdown_link():
    line = render_release_line(
        app_name="Player API",
        source_repo="cmu-sei/Player.Api",
        release_tag="v2.6.0",
    )
    assert line == (
        "Automated update for Player API to version "
        "[v2.6.0](https://github.com/cmu-sei/Player.Api/releases/tag/v2.6.0)."
    )


def test_settings_section_none_when_no_changes():
    section = render_settings_section(
        source_repo="cmu-sei/Player.Api",
        release_tag="v2.6.0",
        readme_path="charts/player/README.md",
        added={},
        removed=[],
    )
    assert section is None


def test_settings_section_added_only():
    section = render_settings_section(
        source_repo="cmu-sei/Player.Api",
        release_tag="v2.6.0",
        readme_path="charts/player/README.md",
        added={"B__Key": LeafType.STRING, "A__Key": LeafType.STRING},
        removed=[],
    )
    assert section is not None
    assert "## Settings changes to review" in section
    assert (
        "The following settings were introduced in "
        "[v2.6.0](https://github.com/cmu-sei/Player.Api/releases/tag/v2.6.0)."
        in section
    )
    assert "README updates may be needed in charts/player/README.md." in section
    assert "### Added" in section
    assert section.index("`A__Key`") < section.index("`B__Key`")
    assert "### Removed" not in section


def test_settings_section_removed_only_omits_added_header():
    section = render_settings_section(
        source_repo="cmu-sei/Player.Api",
        release_tag="v2.6.0",
        readme_path=None,
        added={},
        removed=["X__Key"],
    )
    assert section is not None
    assert "### Added" not in section
    assert "### Removed" in section
    assert "`X__Key`" in section
    assert "README updates may be needed" not in section


def test_settings_section_both_added_and_removed():
    section = render_settings_section(
        source_repo="cmu-sei/Player.Api",
        release_tag="v2.6.0",
        readme_path="charts/player/README.md",
        added={"New__Key": LeafType.STRING},
        removed=["Old__Key"],
    )
    assert section is not None
    assert "### Added" in section
    assert "### Removed" in section
    assert section.index("### Added") < section.index("### Removed")
