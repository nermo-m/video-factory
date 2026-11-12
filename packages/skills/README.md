# packages/skills

Planner skills (design doc section 6). A skill is one model call with a checked,
versioned answer.

Each skill is a folder:

| File | What it is |
| --- | --- |
| `SKILL.md` | The instructions for the model. The block on top names the skill, its version, and whether it may search the web |
| `input.schema.json` | What the skill is given |
| `output.schema.json` | What it must answer with. `{"$ref": "brief.schema.json"}` stands for a shared schema in `schemas/` |
| `examples/` | An input and the answer wanted for it, from the sample episode |
| `tests/` | Tests of the skill's instructions |

`planner.py` is the planner service. `run_skill` checks the input, asks the language
model it is handed, checks the answer against the output schema and the skill's own
rules, and asks once more with the problems appended when the answer fails (section 4.4).
After a second failure the job fails as invalid output. Every model call is returned, so
the caller can store them all.

`rules.py` holds what a schema cannot say:

- **research:** a claim is kept only if its source is one of the pages the search really
  retrieved (FR-02). Other claims are dropped and named in the result. An empty list with
  a note is a good answer.
- **script:** the word budget. `(target seconds + 2 - 0.7 per scene) x 2.3 x voice speed`,
  which is 96 words for 45 seconds in 7 scenes. A script more than 5 percent over is sent
  back. It may also only use claims that research returned.

So far: `brief`, `research`, `script`. Changing a skill's instructions in a way that
changes its answers means raising its version and recording
`samples/recordings/<skill>.json` again: demo mode refuses a recording made for another
version.
