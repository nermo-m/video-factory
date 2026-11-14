# Director Mode Part 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One free prompt becomes an editable shot list that the studio follows word for word, drawn full-frame in a plain look, with research, captions and music as switches, and videos can be deleted.

**Architecture:** One skill, `shotlist`, replaces `brief`, `script`, `direct` and `assets`. Its answer is checked in code against the owner's prompt, and ordinary code (`build_spec`) turns it into the render plan, now schema version 2.1 with a `shot` scene kind. A second theme folder, `plain`, draws a shot as a full-frame picture with a camera move. The pipeline's states stay; states without a job are passed over.

**Tech Stack:** Python 3.12 (uv, SQLAlchemy, Alembic, FastAPI, Pillow, jsonschema), PostgreSQL, Next.js with TypeScript, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-14-director-mode-design.md`

## Global Constraints

- One task is one board card and one pull request, on a branch made from `origin/main`, merged with `gh pr merge <branch> --squash --auto`. `main` is protected with 12 required checks.
- Tests first. `make check` green before every commit, `make test-integration` for anything touching the database, `make render-test` for anything touching `packages/render`, `make e2e` for anything touching `apps/web`. Line coverage stays at 80 percent or more (`make coverage`).
- Tests and CI run with `PROVIDER_MODE=demo`. No test makes a model call.
- Nothing in the repository names the company. Nothing in the repository (skills, examples, recordings, fixtures, tests, stories) names a character, brand, song or story that belongs to someone else. Use the lighthouse keeper sample or invented material.
- No prompt wording meant to get a picture past the image model's own filter.
- No GPL dependency. No new dependency unless a task names it. Every new font or media file gets a row in `ASSETS.md` (`make check-assets`).
- A video is vertical 1080 by 1920, 15 to 180 seconds, at most 30 scenes.
- After any change to API routes run `make generate-api` and commit the result.
- Each pull request updates `PROGRESS.json` (then `node tools/sync-progress.mjs`) and adds its decisions to `docs/decisions-log.md`.
- Words shown to the owner are plain English, in the tone of the existing screens.
- On this PC `uv` and `make` need the PATH line from the dev-environment notes, also for `git commit`.

## Review Focus

1. **A prompt with no spoken lines at all** (pictures and seconds only): the video is made silent with music, the voice step has nothing to do, nothing fails. Test in Task 4 and Task 5.
2. **A video deleted while one of its pictures is being made:** the delete answers at once, the video is gone from the Board, and the picture job's result is thrown away without a failed job or a leftover file. Test in Task 1.
3. **A prompt whose lines use curly quotes, capitals or double spaces differently from the model's answer:** the lines still count as the owner's. Test in Task 4.
4. **The owner removes a character that a scene still lists, or renames its id, while editing the plan:** saving is refused with a message that names the scene, the plan is not half-saved. Test in Task 2.
5. **An uploaded picture that is not vertical** (landscape or square) in a shot: it fills the frame cropped from the centre, no bars, no stretch. Test in Task 3.

---

### Task 1: Delete videos

**Files:**
- Create: `packages/core/db/migrations/versions/0005_episode_deleted_at.py`, `packages/core/removal.py`, `packages/core/tests/test_removal.py`, `apps/web/src/components/ui/confirm-dialog.tsx`, `apps/web/e2e/delete.spec.ts`
- Modify: `packages/core/db/models.py` (Episode), `packages/core/storage.py` and `packages/adapters/storage/local.py` (remove files), `apps/worker/runner.py`, `apps/api/episodes.py`, `apps/api/tests/test_episodes_integration.py`, `apps/web/src/components/board/board.tsx`, `apps/web/src/components/board/episode-card.tsx`, `apps/web/src/components/workspace/workspace.tsx`, `apps/web/src/components/episodes/episodes-provider.tsx`

**Interfaces:**
- Produces: `Episode.deleted_at: datetime | None`; `removal.mark_deleted(session, episode_id) -> bool` (false when there is no such episode); `removal.purge(session, storage, episode_id) -> None`; `StorageAdapter.remove_tree(prefix: str) -> None`; `DELETE /api/v1/episodes/{episode_id}` answering 204.

- [ ] **Step 1: Failing tests in `packages/core/tests/test_removal.py`** (integration marker, own channel per test):
  - `test_mark_deleted_cancels_queued_jobs_and_hides_the_episode`: queued jobs become `cancelled`, `deleted_at` is set, returns `True`.
  - `test_mark_deleted_twice_is_the_same_as_once`: second call returns `True`, `deleted_at` unchanged.
  - `test_mark_deleted_of_an_unknown_id_returns_false`.
  - `test_purge_removes_rows_and_files_but_keeps_library_pictures_and_usage`: after `purge`, no `episode`, `spec_version`, `job`, `render`, episode-keyed `asset` or `asset_version` row is left, the episode's folders in storage are gone, a library asset of the channel and its file remain, and the `model_call` rows remain with their job reference empty.
  - `test_purge_waits_while_a_job_is_running`: with one `running` job `purge` removes nothing.
- [ ] **Step 2: Run** `uv run --env-file .env pytest -m integration packages/core/tests/test_removal.py`. Expected: fails on import.
- [ ] **Step 3: Migration `0005`** adds `episode.deleted_at TIMESTAMPTZ NULL` with an index, and makes the usage table's job reference nullable with `ON DELETE SET NULL` if it is not already.
- [ ] **Step 4: Implement `removal.py` and `remove_tree`.** `mark_deleted` locks the episode row. `purge` returns early while any job of the episode is `running`, otherwise deletes child rows in foreign-key order inside the caller's transaction and removes the files after the rows (episode-keyed asset files, `scenes_path(episode_id)`, the job output folders that carry the episode id). `remove_tree` refuses a prefix that is empty or leaves the data folder.
- [ ] **Step 5: Worker.** In `apps/worker/runner.py`, where a finished job is recorded: when the job's episode has `deleted_at`, the result is not passed to `pipeline.job_succeeded`, the job is marked `cancelled`, and `removal.purge` runs. Test `test_a_job_that_ends_after_its_video_was_deleted_is_thrown_away` in `apps/worker/tests/test_worker.py` (Review Focus 2).
- [ ] **Step 6: API.** `EpisodeService.delete(episode_id) -> None` calls `mark_deleted` then `purge` in one transaction. The route answers 204 whether or not the episode existed. Every read (`page`, `_episode`) leaves out episodes with `deleted_at`. Tests in `test_episodes_integration.py`: `test_delete_removes_the_episode_from_the_board`, `test_delete_twice_answers_204`, `test_a_deleted_episode_answers_404_everywhere`.
- [ ] **Step 7: Web.** `ConfirmDialog` props: `title`, `body`, `confirmLabel`, `onConfirm`, `onCancel`, `busy`; focus starts on Cancel, Escape cancels. Board card gets a "Delete" action. Board gets "Select", which turns cards into checkboxes with "Delete N videos". The workspace header gets "Delete video", which returns to the Board. Copy: title `Delete "<title>"?` or `Delete N videos?`, body `The plan, pictures, voice and rendered files are removed for good.`, confirm `Delete`. After success a status line `Deleted.`, after failure `<title> could not be deleted. Try again.` and the card stays.
- [ ] **Step 8: `delete.spec.ts`:** create two episodes, delete one from its card and confirm it is gone after reload, select and delete the other, cancel keeps a video.
- [ ] **Step 9:** `make generate-api`, `make check`, `make test-integration`, `make e2e`. Commit `feat: delete videos from the Board and the video page`.

### Task 2: Plan schema 2.1

**Files:**
- Modify: `schemas/episode_spec.schema.json`, `schemas/README.md`, `packages/core/specs.py`, `packages/render/theme/__init__.py` (`check_capabilities`), `packages/core/tests/test_schemas.py`, `packages/core/tests/test_specs.py`, `packages/render/tests/test_theme.py`
- Create: `schemas/fixtures/episode_spec/valid/shots.json`, `schemas/fixtures/episode_spec/invalid/shot_without_visual.json`, `shot_with_unknown_position.json`, `change_with_unknown_kind.json`, `character_without_description.json`

**Interfaces:**
- Produces, in the schema:
  - `spec_version`: `"2.0"` or `"2.1"`.
  - Top level, optional: `style` (string, 1 to 2000), `characters` (0 to 12 of `{id: scene-id pattern, name: 1 to 80, description: 1 to 2000}`), `changes` (0 to 100 of `{scene?: scene id, kind: "added" | "changed" | "not_possible", what: 1 to 300, why: 1 to 300}`), `captions` (boolean, default true), `music` (boolean, default true).
  - Scene kind `shot`: requires `visual`; allows `narration`, `narration_from` (`"owner"` or `"studio"`), `text`, `duration_s`, `pad_before_s`, `pad_after_s`, `transition_out`; forbids `title`, `label`, `sublabel`, `stat`, `steps`, `overlays`, `sound`, `hold_s`, `retention_device`.
  - `visual` gains `camera` (name) and `motion` (string, 1 to 1000). `text_item` gains optional `position` (`"top" | "middle" | "bottom"`).
  - `asset` gains `characters` (array of character ids) and `text_in_picture` (boolean, default false). `asset.prompt` maximum becomes 4000.
- Produces, in code: `specs.reference_problems(body) -> list[str]`, called wherever a spec is stored; `check_capabilities` also checks `visual.camera` against `capabilities["cameras"]` and `text[].position` against `capabilities["text_positions"]` when the theme lists them.

- [ ] **Step 1: Fixtures and failing tests.** The fixture tests already walk the folders. Add to `test_specs.py`: `test_a_scene_asset_that_lists_an_unknown_character_is_refused` (message contains the asset id and the character id, nothing is stored: Review Focus 4), `test_two_characters_with_one_id_are_refused`, `test_a_change_that_names_an_unknown_scene_is_refused`. Add to `test_theme.py`: `test_a_camera_the_theme_does_not_have_is_reported`, `test_a_text_position_the_theme_does_not_have_is_reported`.
- [ ] **Step 2: Run** `uv run pytest packages/core/tests/test_schemas.py packages/core/tests/test_specs.py packages/render/tests/test_theme.py`. Expected: the new ones fail.
- [ ] **Step 3: Extend the schema** as listed. Every existing valid 2.0 fixture must stay valid and every invalid one invalid.
- [ ] **Step 4: Implement `reference_problems` and the two capability checks.**
- [ ] **Step 5:** `make check`. Commit `feat: plan schema 2.1 with shots, characters and the change list`.

### Task 3: The plain look

**Files:**
- Create: `packages/render/theme/plain/__init__.py`, `theme.json`, `capabilities.json`, `assets/fonts/Inter-Variable.ttf`, `assets/fonts/Inter-OFL.txt`, `packages/render/tests/test_plain.py`, golden frames under the existing golden folder
- Modify: `packages/render/theme/__init__.py` (`load_theme`), `packages/render/primitives.py`, `packages/render/compositor.py`, `packages/render/resolver.py`, `packages/render/audio.py`, `packages/render/tests/test_resolver.py`, `packages/render/tests/test_golden.py`, `ASSETS.md`

**Interfaces:**
- Consumes: schema 2.1 from Task 2.
- Produces: `load_theme("plain")`; `capabilities.json` exactly:
  `{"theme": "plain", "scene_kinds": ["shot"], "text_styles": ["plain"], "overlay_types": [], "stamp_colors": [], "sprites": {}, "sound_cues": [], "transitions": ["cut", "fade"], "cameras": ["none", "push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down"], "text_positions": ["top", "middle", "bottom"]}`;
  `primitives.camera_frame(image: Image.Image, size: tuple[int, int], camera: str, progress: float) -> Image.Image`.

Values the tests pin:
- Cover crop: scale the picture so it covers the frame, crop from the centre.
- `push_in` scales from 1.00 to 1.08 over the scene, `pull_out` from 1.08 to 1.00. Pans and tilts hold scale 1.08 and travel across the spare 8 percent, start to end. `none` is scale 1.00. A scene without `camera` uses `push_in`. Movement is linear in `progress` from 0 to 1.
- `fade`: 0.3 seconds, the outgoing scene fades to black and the incoming one fades from black.
- Text style `plain`: Inter weight 700, white, 4 pixel dark edge, inside the safe area, at most 3 lines per item. `top`, `middle`, `bottom` are layout boxes in `theme.json`. `bottom` sits above the caption row.
- Captions use the same font. They are not drawn when the resolved spec has `captions` false. The music bed is silent when it has `music` false.
- `load_theme` accepts a theme without `backgrounds`, `scroll`, `sprites`, `sounds` and `pin`.
- Resolver: a `shot` scene lasts the longer of its narration with pads and its `duration_s`. A shot with no narration and no `duration_s` lasts 3 seconds. For a 2.1 spec the total is not compared with `format.target_duration_s`: no `DurationError` and no pause fitting.

- [ ] **Step 1: Failing unit tests in `test_plain.py`:** `test_the_plain_theme_loads`, `test_a_landscape_picture_fills_the_frame_from_the_centre` (a 400 by 200 picture with a marked centre pixel: output is the frame size, no black column, the centre pixel is at the centre: Review Focus 5), `test_push_in_ends_8_percent_closer`, `test_pan_left_moves_the_picture_left`, `test_none_does_not_move`, `test_captions_off_draws_no_caption_box` (the `record` list has no `caption` entry), `test_text_positions_do_not_overlap_the_caption_row`. In `test_resolver.py`: `test_a_shot_lasts_as_long_as_its_line`, `test_a_silent_shot_takes_its_seconds`, `test_a_silent_shot_without_seconds_takes_three`, `test_a_2_1_spec_is_not_held_to_its_target_length`. In the audio tests: `test_music_off_gives_a_silent_music_stem`.
- [ ] **Step 2: Run** `uv run pytest packages/render/tests/test_plain.py packages/render/tests/test_resolver.py`. Expected: fail.
- [ ] **Step 3: Theme folder, loader, `camera_frame`.**
- [ ] **Step 4: Compositor.** `Compositor.render` draws a `shot` scene through a new `_shot` method on a black canvas and skips the background layers, particles, sprites, tags and stamps when the theme has none. `night_scrolls` frames must not change by one pixel.
- [ ] **Step 5: Resolver and audio** as listed.
- [ ] **Step 6: Golden frames.** Add a three-scene plain sample (push_in with top text, pan_left with captions, fade into a silent shot) to `test_golden.py`. Run `make render-golden-update`, look at each new frame, then `make render-test`. Expected: pass, and the existing night_scrolls golden frames are unchanged in Git.
- [ ] **Step 7:** `ASSETS.md` rows for the two font files. `make check`. Commit `feat: the plain look draws a shot on the whole frame`.

### Task 4: The shot list skill

**Files:**
- Create: `packages/skills/shotlist/__init__.py`, `SKILL.md`, `input.schema.json`, `output.schema.json`, `examples/lighthouse_keeper.input.json`, `examples/lighthouse_keeper.output.json`, `tests/__init__.py`, `tests/test_shotlist.py`, `packages/skills/build.py`, `packages/skills/tests/test_build.py`, `samples/recordings/shotlist.json`
- Modify: `packages/skills/planner.py` (`SKILL_NAMES`), `packages/skills/rules.py`, `packages/skills/tests/test_planner.py`, `samples/README.md`

**Interfaces:**
- Consumes: schema 2.1, the plain capabilities.
- Produces:
  - Skill `shotlist`, version `"1.0"`, `effort: high`. Input: `idea`, `capabilities`, `voice_speed`, `claims`. Output: `title` (1 to 200), `style` (1 to 2000), `characters`, `target_duration_s` (optional, only when the owner stated a total), `scenes` (1 to 30), `changes`. A scene: `id`, `narration` (0 to 600), `narration_from`, `on_screen_text` (0 to 4 of `{content, position}`), `duration_s` (optional), `image_prompt` (40 to 3500), `characters` (ids), `motion_prompt` (1 to 1000), `clip` (boolean), `camera`, `third_party` (boolean), `text_in_picture` (boolean).
  - `rules.marked_lines(idea: str) -> list[str]`: every passage inside straight or curly double quotes, and the rest of every line after a label `VO`, `V.O.`, `Voiceover`, `Voice over`, `Narration` or `Narrator` followed by a colon, case aside, in the order they stand. Passages of fewer than `MIN_WORDS_OF_A_LINE` words are left out.
  - `rules.shotlist_follows_the_owner(inputs, output, response) -> list[str]` (a planner `Check`).
  - `rules.needed_seconds(scenes, speed) -> float`.
  - `build.build_spec(shotlist, *, episode_id: uuid.UUID, voice_id: str, voice_speed: float, captions: bool, music: bool, claims: list[dict]) -> dict` returning a 2.1 spec, and `build.TooLongError(needed_s: int)`.

What `shotlist_follows_the_owner` reports, one sentence each, naming the scene:
- a scene marked `owner` whose narration, compared with `rules._plain`, does not stand in the idea;
- a scene marked `studio` that has narration and no `changes` entry with that `scene`;
- a marked line that stands in no scene's narration, or marked lines that appear out of order;
- a `characters` id on a scene that is not in `characters`; two scenes or two characters with one id;
- a `camera` that is not in `capabilities["cameras"]`, a `position` not in `capabilities["text_positions"]`.

What `build_spec` does:
- One asset per scene: id `a_<scene id>`, kind `image`, origin `generated`, `prompt` the scene's `image_prompt`, `characters`, `text_in_picture`, `contains_third_party_ip` from `third_party`, `rights_status` `needs_review`.
- Scene kind `shot`, `visual` with `asset_id`, `clip`, `camera`, `motion`; `on_screen_text` becomes `text` items with style `plain`.
- A scene's `duration_s` shorter than `rules.scene_seconds(narration, speed)` is dropped and a `changed` entry is appended: `what` "Scene lasts as long as its line", `why` "The line takes N seconds to speak and the scene was given M."
- `format.target_duration_s` is the sum of the scenes, at least 15. When the owner's `target_duration_s` is shorter than that sum by more than 2 seconds a `changed` entry is appended. When the sum is above 180 it raises `TooLongError`.
- `theme` `plain`, `seed` `episode_id.int % 2**32`, width 1080, height 1920, fps as `apps/worker/handlers/plan.py` uses today.

`SKILL.md` must say, in its own words: the owner's prompt is the plan; keep its scenes, order, lines, names, places and style; fill in only what is missing; never shorten, soften or replace; every `image_prompt` stands on its own and carries every detail the owner gave for that scene, its background and its mood, then subject, pose, expression, outfit, setting, lighting, camera angle and lens; do not repeat a character's description in `image_prompt`, list the character's id instead; everything added, changed or not possible goes into `changes`; a move, sound or music the look cannot do is `not_possible`; names stay as written, and `third_party` is true when a picture shows a character, brand or real person that is not the owner's.

- [ ] **Step 1: Failing tests.** `test_shotlist.py`: `test_the_example_passes_its_schemas_and_rules`, `test_the_recording_matches_the_skill_version`. `test_planner.py` additions for the rules: `test_marked_lines_finds_quotes_and_labels_in_order`, `test_curly_quotes_capitals_and_double_spaces_still_match` (Review Focus 3), `test_a_dropped_marked_line_is_reported`, `test_an_owner_line_that_is_not_in_the_prompt_is_reported`, `test_a_studio_line_without_a_change_entry_is_reported`, `test_a_prompt_without_spoken_lines_has_nothing_to_report` (all scenes silent: Review Focus 1). `test_build.py`: `test_one_generated_picture_per_scene`, `test_the_built_spec_fits_schema_2_1_and_the_plain_theme`, `test_a_scene_shorter_than_its_line_is_lengthened_and_listed`, `test_a_stated_length_shorter_than_the_lines_is_listed`, `test_more_than_180_seconds_raises_too_long`, `test_a_silent_shot_list_builds` (Review Focus 1), `test_the_same_episode_gets_the_same_seed`.
- [ ] **Step 2: Run** `uv run pytest packages/skills`. Expected: the new ones fail.
- [ ] **Step 3: Write the skill folder, the example (the lighthouse keeper story as a five-scene shot list with one character) and the recording**, whose `output` is the example output.
- [ ] **Step 4: Implement the rules and `build_spec`.**
- [ ] **Step 5:** `make check`. Commit `feat: the shot list skill and the code that builds the plan from it`.

### Task 5: The pipeline runs the shot list

**Files:**
- Create: `packages/core/db/migrations/versions/0006_episode_options.py`, `packages/core/prompts.py`, `packages/core/tests/test_prompts.py`
- Modify: `packages/core/db/models.py`, `packages/core/stages.py`, `packages/core/pipeline.py`, `packages/core/assets.py`, `packages/core/stale.py`, `packages/core/specs.py`, `packages/core/settings.py`, `apps/worker/handlers/plan.py`, `apps/worker/handlers/pictures.py`, `packages/skills/planner.py`, `packages/skills/rules.py`, `packages/skills/research/*`, `samples/recordings/research.json`, their tests, `apps/worker/demo_render.py` and `samples/` if they depend on a removed skill
- Delete: `packages/skills/brief`, `script`, `direct`, `assets`, their recordings in `samples/recordings`, and the rules and tests only they used

**Interfaces:**
- Consumes: Tasks 2 to 4.
- Produces:
  - `Episode.options: dict` (JSONB, default `{}`), read through `options_of(episode) -> EpisodeOptions(research: bool = False, captions: bool = True, music: bool = True)` in `packages/core/db/models.py` or beside it.
  - `stages.plan_stage(..., research: bool = False)`. `_ONE_JOB`: `RESEARCH: "plan.research"` only when `research`, `DIRECTION: "plan.shotlist"`, no entry for `BRIEF`, `SCRIPT`, `ASSET_PLAN`. The clip stage of `ASSET_GEN` returns no jobs.
  - `assets.sync_from_spec(session, episode, spec) -> None`: a row for every generated or uploaded picture of the spec, existing rows and owner-set rights kept.
  - `prompts.compose(spec: Mapping, asset: Mapping) -> str`: for a 2.1 spec the style, then `<name>: <description>` for each listed character, then the asset's prompt, separated by blank lines. For a 2.0 spec the asset's prompt as it is.
  - `specs.is_editable(body) -> bool`: true for 2.1.

- [ ] **Step 1: Failing tests.**
  - `packages/core/tests/test_stages.py`: `test_planning_is_one_shot_list_job`, `test_research_runs_only_when_asked`, `test_brief_script_and_asset_plan_have_no_jobs`, `test_no_clip_job_is_queued_for_a_clip_scene`.
  - `packages/core/tests/test_pipeline.py` (integration): `test_a_new_episode_goes_from_idea_to_the_plan_gate_with_one_job`, `test_an_old_episode_resting_in_brief_is_planned_by_the_shot_list`.
  - `test_prompts.py`: `test_the_style_and_the_characters_come_before_the_scene`, `test_a_scene_without_characters_gets_none`, `test_an_old_plan_keeps_its_prompt`.
  - `packages/core/tests/test_stale.py`: `test_editing_a_character_marks_the_scenes_that_show_it`, `test_editing_the_style_marks_every_picture_scene`.
  - `apps/worker/tests/test_plan_handlers.py`: `test_the_shot_list_job_stores_a_2_1_plan_names_the_episode_and_creates_its_picture_rows`, `test_lines_longer_than_180_seconds_stop_the_job_for_the_owner` (error class `needs_owner`, message `Your lines need about N seconds and a video can be 180 at most. Shorten the prompt or split it into two videos.`), `test_a_silent_prompt_reaches_the_plan_gate` (Review Focus 1).
  - `apps/worker/tests/test_picture_handlers.py`: `test_the_picture_prompt_carries_style_and_characters`, `test_no_text_rule_is_left_out_when_the_picture_asks_for_text`, `test_the_channel_style_block_is_not_added_to_a_2_1_plan`.
- [ ] **Step 2: Run** the unit tests and `make test-integration`. Expected: the new ones fail.
- [ ] **Step 3: Migration `0006`, model, `options_of`.** `critic_enabled` defaults to false in `packages/core/settings.py` and `.env.example`.
- [ ] **Step 4: Stages and pipeline.** `pipeline._start_stage` passes `options_of(episode).research`.
- [ ] **Step 5: Handler `plan.shotlist`** in `apps/worker/handlers/plan.py`: inputs as Task 4 lists (claims from the research job when it ran, otherwise an empty list), check `rules.shotlist_follows_the_owner`, then `build_spec`, `store_spec`, title, `episode.target_duration_s`, `assets.sync_from_spec`, `assets.ensure_library`. `TooLongError` becomes a `JobError` of class `needs_owner`. Remove the handlers and helpers of the removed skills. `research` takes `{"idea": ...}`, version `1.1`, with its recording updated.
- [ ] **Step 6: Pictures.** `apps/worker/handlers/pictures.py` builds the prompt with `prompts.compose`, and `full_prompt` leaves out `NO_TEXT` when the asset has `text_in_picture`.
- [ ] **Step 7: Stale marking and editing.** `stale._shown` includes the composed prompt, so a changed character or style marks its scenes. Wherever the API stores an edited 2.1 spec, `assets.sync_from_spec` runs in the same transaction.
- [ ] **Step 8: Remove the four skill folders** and what only they used. `grep -rn "plan.brief\|plan.script\|plan.direct\|plan.assets\|follows_owner_lines\|script_fits\|spec_follows_the_plan\|manifest_covers_the_spec"` over `apps packages samples docs/architecture.md` finds nothing but history notes.
- [ ] **Step 9:** `make check`, `make test-integration`, `make render-test`, `make demo-render`. Commit `feat: one shot list step plans a video in place of the seven-step chain`.

### Task 6: The screens

**Files:**
- Create: `apps/web/src/components/workspace/changes-panel.tsx`, `characters-panel.tsx`, `shot-card.tsx`, stories for each
- Modify: `apps/api/episodes.py`, `apps/api/tests/test_episodes.py`, `test_episodes_integration.py`, `test_contract.py`, `apps/web/src/components/episodes/new-episode-dialog.tsx`, `apps/web/src/components/workspace/plan-tab.tsx`, `scene-card.tsx`, `use-workspace.ts`, `apps/web/src/lib/workspace.ts`, `apps/web/e2e/demo.spec.ts`, `workspace.spec.ts`, `workspace-support.ts`, `board.spec.ts`

**Interfaces:**
- Consumes: Task 5.
- Produces: `EpisodeCreate {idea, options?: {research?: bool, captions?: bool, music?: bool}, start}` (`target_duration_s` is no longer taken); `EpisodeOut.options`; `PlanOut` gains `editable: bool`, `style`, `characters`, `changes`; `PUT /episodes/{id}/spec`, `POST .../revise` and `POST .../revise/{job}/apply` answer 409 with reason `plan_read_only` for a 2.0 plan.

Copy the screens use:
- New episode: heading `Write your video`, hint `Write it the way you want it: story, characters, look, scenes, lines, music, length. The studio follows what you write and lists anything it had to add.` Options (closed by default): `Check facts with sources` (off), `Captions` (on), `Music` (on).
- Plan tab, top panel `What the studio changed`: groups `Added`, `Changed`, `Not possible yet`; empty `Nothing was changed. The plan is your prompt as you wrote it.`
- `Characters` panel: name and description, editable; hint `Described once, used in every picture that shows them.`
- `Style` field.
- Shot card fields: `Spoken line` (with a small mark `yours` or `written by the studio`), `On-screen text`, `Seconds`, `Picture`, `Who is in it`, `Camera`, `Motion`, `Make it a moving clip` with the note `Clips arrive with the next step. Until then this scene shows its picture with the camera move.`
- An old plan: banner `This video was planned the old way. You can still render it and change its pictures. To edit it, plan it again from its idea.` with the button `Plan again`, which calls rerun for `direction` after a confirmation `Planning again replaces this plan and its pictures.`

- [ ] **Step 1: Failing API tests:** `test_create_takes_options_and_stores_them`, `test_create_with_unknown_option_is_refused`, `test_plan_out_carries_changes_characters_and_style`, `test_editing_an_old_plan_answers_409_plan_read_only`, `test_saving_a_plan_with_a_removed_character_still_used_is_refused_whole` (Review Focus 4).
- [ ] **Step 2: Implement the API changes,** `make generate-api`.
- [ ] **Step 3: New episode dialog** as described, the length choice removed.
- [ ] **Step 4: Plan tab.** `plan-tab.tsx` shows the three panels and one `ShotCard` per scene for a 2.1 plan, and the existing read-only scene cards under the banner for a 2.0 plan. Every edit saves through the existing spec save in `use-workspace.ts`, with the existing saved and failed states. A failed load shows the error state with Retry, never an empty plan.
- [ ] **Step 5: Stories** for each new component: filled, empty, saving, failed.
- [ ] **Step 6: Browser tests.** `demo.spec.ts`: write a prompt, reach the plan gate, see `Nothing was changed` or the recorded changes, edit one picture prompt and one character, approve, pictures, render, video present through the API. `workspace.spec.ts`: an old-plan episode shows the banner and no edit fields.
- [ ] **Step 7:** `make check`, `make test-integration`, `make e2e`. Commit `feat: write your video, see what was changed, edit every field of the shot list`.

### Task 7: Records and the live run

**Files:**
- Create: `docs/adr/0011-one-shot-list-step-replaces-the-planning-chain.md`
- Modify: `docs/adr/README.md`, `docs/architecture.md`, `README.md`, `docs/questions.md` (close Q-077, add what came up), `docs/decisions-log.md`, `packages/skills/README.md`, `apps/worker/README.md`, `PROGRESS.json`

- [ ] **Step 1:** Write the ADR (context: the owner's words of 2026-11-14; decision; what was removed; consequences for old episodes) and bring the listed documents in line with the code as it now is.
- [ ] **Step 2:** Add a changelog entry to the Notion design document and move the board cards.
- [ ] **Step 3: Live run** in subscription mode on the owner's plans with one of the owner's own shot lists from an earlier episode's idea: start the stack as the dev-environment notes say, make the video through the browser, then compare the stored plan with the prompt line by line. Every marked line spoken as written, every difference on the change list, every picture prompt carrying the scene's details. Record the result, the number of calls and pictures used, and anything that was off as a new card, in the Owner inbox comment.
- [ ] **Step 4:** `make check`. Commit `docs: record Director mode part 1 and its first live video`.
