// Who writes a video's plan: the tool (Claude or ChatGPT, on the owner's own plans) and
// the model. The API takes it as one text: "claude", "chatgpt:gpt-5.5", or nothing when
// the studio chooses. No React and no requests here.

/** The choices the forms offer, as [value, words]. */
export const WRITERS: readonly (readonly [string, string])[] = [
  ["", "Studio's choice (Claude)"],
  ["claude:claude-fable-5-2", "Claude Fable 5.2"],
  ["claude:claude-opus-5-5", "Claude Opus 5.5"],
  ["claude:claude-sonnet-5-5", "Claude Sonnet 5.5"],
  ["claude:claude-haiku-5-5", "Claude Haiku 5.5"],
  ["chatgpt", "ChatGPT (your plan's own model)"],
  ["claude:other", "Another Claude model…"],
  ["chatgpt:other", "Another ChatGPT model…"],
];

/** A model name as the API takes it. */
const MODEL = /^[A-Za-z0-9][A-Za-z0-9._:[\]-]{0,79}$/;

/** True when the choice asks for a model name to be typed. */
export function needsModel(choice: string): boolean {
  return choice.endsWith(":other");
}

/**
 * The text the API takes for a choice, or null when a model name is asked for and what
 * was typed is not one.
 */
export function writerText(choice: string, typed: string): string | null {
  if (!needsModel(choice)) {
    return choice;
  }
  const model = typed.trim();
  return MODEL.test(model) ? `${choice.slice(0, -"other".length)}${model}` : null;
}

/** The words for a stored writer: the form's own words, or the tool and the model. */
export function writerLabel(writer: string): string {
  const known = WRITERS.find(([value]) => value === writer);
  if (known) {
    return known[1];
  }
  const [tool, model] = writer.split(/:(.*)/s);
  return `${tool === "chatgpt" ? "ChatGPT" : "Claude"} ${model ?? ""}`.trim();
}
