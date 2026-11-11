# Assets

Everything in this repository is original or permissively licensed. No third-party
characters, logos, footage, stills or commercial music are allowed anywhere, including
samples, theme art, fonts, sounds, test fixtures, golden frames, screenshots and demo videos.

Every file under `samples/` and every media file (image, font, audio, video) anywhere in
the repository needs a row in the table below. `scripts/check_assets.py` enforces this in
pre-commit and in CI: a file without a row fails the build, and so does a row that matches
no file.

## How to add a row

- **Path**: the file's path from the repository root. Globs are allowed: `*` and `?` stay
  inside one folder, `**` crosses folders.
- **Origin**: `original` (made by hand for this project), `generated` (model output made
  for this project) or `third-party`.
- **Licence**: an SPDX identifier from the permissive list in `scripts/check_assets.py`
  (for example `MIT`, `OFL-1.1`, `CC0-1.0`, `CC-BY-4.0`).
- **Source**: who made it or where it came from, with a link for third-party files.

## Registry

| Path | Origin | Licence | Source |
| --- | --- | --- | --- |
