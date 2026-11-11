"""Tests for scripts/check_assets.py.

Design doc section 13, rule 2: every sample and media file needs an ASSETS.md row
with origin, licence and source, and the check must fail when one is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_assets

HEADER = "| Path | Origin | Licence | Source |\n| --- | --- | --- | --- |\n"


def registry(*rows: str) -> str:
    return (
        "# Assets\n\nSome prose that is not a table row.\n\n"
        + HEADER
        + "".join(f"{row}\n" for row in rows)
    )


def test_rule2_sample_file_without_row_fails() -> None:
    problems = check_assets.check(["samples/episode/hill_dawn.png"], registry())

    assert problems == ["samples/episode/hill_dawn.png: no row in ASSETS.md"]


def test_rule2_sample_file_with_row_passes() -> None:
    text = registry("| `samples/episode/hill_dawn.png` | original | MIT | Drawn for this project |")

    assert check_assets.check(["samples/episode/hill_dawn.png"], text) == []


def test_rule2_every_file_type_under_samples_needs_a_row() -> None:
    problems = check_assets.check(["samples/spec/lighthouse_keeper.json"], registry())

    assert problems == ["samples/spec/lighthouse_keeper.json: no row in ASSETS.md"]


def test_rule2_media_outside_samples_needs_a_row() -> None:
    files = [
        "packages/render/theme/night_scrolls/fonts/title.ttf",
        "docs/design/board.png",
        "apps/web/public/logo.svg",
    ]

    problems = check_assets.check(files, registry())

    assert problems == [f"{path}: no row in ASSETS.md" for path in sorted(files)]


def test_code_and_text_outside_samples_need_no_row() -> None:
    files = [
        "README.md",
        "ASSETS.md",
        "scripts/check_assets.py",
        "packages/render/theme/night_scrolls/capabilities.json",
        "apps/web/src/app/page.tsx",
    ]

    assert check_assets.check(files, registry()) == []


def test_readme_inside_samples_is_exempt() -> None:
    assert check_assets.check(["samples/README.md"], registry()) == []


def test_media_suffix_is_matched_case_insensitively() -> None:
    assert check_assets.check(["docs/Screenshot.PNG"], registry()) == [
        "docs/Screenshot.PNG: no row in ASSETS.md"
    ]


def test_recursive_glob_row_covers_a_whole_folder() -> None:
    text = registry("| `samples/recordings/**` | generated | MIT | Recorded from mock runs |")
    files = ["samples/recordings/brief/0001.json", "samples/recordings/agents/critic/run.json"]

    assert check_assets.check(files, text) == []


def test_single_star_does_not_cross_folders() -> None:
    text = registry("| `samples/*.png` | original | MIT | Drawn for this project |")
    files = ["samples/top.png", "samples/nested/deep.png"]

    assert check_assets.check(files, text) == ["samples/nested/deep.png: no row in ASSETS.md"]


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("samples/a.png", "samples/a.png", True),
        ("samples/a.png", "samples/a.png.bak", False),
        ("samples/**/*.wav", "samples/audio/s01.wav", True),
        ("samples/**/*.wav", "samples/s01.wav", True),
        ("samples/s0?.wav", "samples/s01.wav", True),
        ("samples/s0?.wav", "samples/s012.wav", False),
        ("samples/a+b (1).png", "samples/a+b (1).png", True),
    ],
)
def test_pattern_matching(pattern: str, path: str, expected: bool) -> None:
    assert check_assets.matches(pattern, path) is expected


def test_row_with_unknown_origin_fails() -> None:
    text = registry("| `samples/a.png` | found-online | MIT | Somewhere |")

    assert check_assets.check(["samples/a.png"], text) == [
        "ASSETS.md line 7: origin 'found-online' is not one of generated, original, third-party"
    ]


def test_row_with_non_permissive_licence_fails() -> None:
    text = registry("| `samples/a.png` | third-party | CC-BY-NC-4.0 | https://example.org/a |")

    problems = check_assets.check(["samples/a.png"], text)

    assert problems == ["ASSETS.md line 7: licence 'CC-BY-NC-4.0' is not on the permissive list"]


def test_row_with_empty_source_fails() -> None:
    text = registry("| `samples/a.png` | original | MIT |  |")

    assert check_assets.check(["samples/a.png"], text) == ["ASSETS.md line 7: source is empty"]


def test_row_with_wrong_number_of_cells_fails() -> None:
    text = registry("| `samples/a.png` | original | MIT |")

    assert check_assets.check(["samples/a.png"], text) == [
        "ASSETS.md line 7: expected 4 cells (path, origin, licence, source), found 3",
        "samples/a.png: no row in ASSETS.md",
    ]


def test_stale_row_that_matches_no_file_fails() -> None:
    text = registry("| `samples/gone.png` | original | MIT | Drawn for this project |")

    assert check_assets.check([], text) == ["ASSETS.md line 7: 'samples/gone.png' matches no file"]


def test_registry_without_table_reports_it() -> None:
    assert check_assets.check([], "# Assets\n\nNothing here yet.\n") == [
        "ASSETS.md: no table with the header | Path | Origin | Licence | Source |"
    ]


def test_cli_fails_when_a_sample_file_has_no_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "orphan.png").write_bytes(b"\x89PNG")
    (tmp_path / "ASSETS.md").write_text(registry(), encoding="utf-8")

    exit_code = check_assets.main(["--root", str(tmp_path)])

    assert exit_code == 1
    assert "samples/orphan.png: no row in ASSETS.md" in capsys.readouterr().err


def test_cli_passes_when_every_asset_has_a_row(tmp_path: Path) -> None:
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "hill.png").write_bytes(b"\x89PNG")
    (tmp_path / "ASSETS.md").write_text(
        registry("| `samples/hill.png` | original | MIT | Drawn for this project |"),
        encoding="utf-8",
    )

    assert check_assets.main(["--root", str(tmp_path)]) == 0


def test_cli_fails_when_registry_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_assets.main(["--root", str(tmp_path)]) == 1
    assert "ASSETS.md not found" in capsys.readouterr().err


def test_rule2_this_repository_passes_its_own_check() -> None:
    assert check_assets.main([]) == 0
