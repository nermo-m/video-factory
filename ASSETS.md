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
| `apps/web/e2e/__screenshots__/*.png` | original | MIT | Playwright screenshots of this app, made by `make e2e-update` |
| `packages/render/tests/golden/*.png` | original | MIT | Frames drawn by this project's render engine, made by `make render-golden-update` |
| `packages/render/theme/night_scrolls/assets/backgrounds/*.png` | original | MIT | Drawn in code by `packages/render/theme/night_scrolls/build_assets.py` for this project |
| `packages/render/theme/night_scrolls/assets/scroll/*.png` | original | MIT | Drawn in code by `packages/render/theme/night_scrolls/build_assets.py` for this project |
| `packages/render/theme/night_scrolls/assets/sprites/*.png` | original | MIT | Drawn in code by `packages/render/theme/night_scrolls/build_assets.py` for this project |
| `packages/render/theme/night_scrolls/assets/sounds/*.wav` | original | MIT | Synthesised in code by `packages/render/theme/night_scrolls/build_assets.py` for this project |
| `packages/render/theme/night_scrolls/assets/fonts/Anton-Regular.ttf` | third-party | OFL-1.1 | Anton by The Anton Project Authors, https://github.com/google/fonts/tree/main/ofl/anton |
| `packages/render/theme/night_scrolls/assets/fonts/Inter-Variable.ttf` | third-party | OFL-1.1 | Inter by The Inter Project Authors, https://github.com/google/fonts/tree/main/ofl/inter |
| `packages/render/theme/night_scrolls/assets/fonts/Kalam-Bold.ttf` | third-party | OFL-1.1 | Kalam by Indian Type Foundry, https://github.com/google/fonts/tree/main/ofl/kalam |
