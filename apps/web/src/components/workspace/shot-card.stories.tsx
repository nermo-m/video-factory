import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { Change, Character, PlanAsset } from "@/lib/director";
import type { Scene } from "@/lib/workspace";

import { ChangesPanel } from "./changes-panel";
import { LookPanel } from "./look-panel";
import { ShotCard } from "./shot-card";

const KEEPER: Character = {
  id: "keeper",
  name: "The keeper",
  description: "A woman of about sixty, grey braid, yellow oilskin coat, lean and upright.",
};

const SPOKEN: Scene = {
  id: "hill",
  kind: "shot",
  narration: "Every evening she climbed the same hill.",
  narration_from: "owner",
  visual: {
    asset_id: "a_hill",
    clip: true,
    camera: "tilt_up",
    motion: "She walks up the path, the grass moves in the wind.",
  },
  text: [{ content: "Every evening", position: "top" }],
};

const SILENT: Scene = {
  id: "sea",
  kind: "shot",
  narration: "",
  duration_s: 4,
  visual: { asset_id: "a_sea", clip: false, camera: "none" },
};

const PICTURE: PlanAsset = {
  id: "a_hill",
  prompt: "A steep green hill at dusk, a narrow path, a lighthouse at the top, seen from below.",
  characters: ["keeper"],
};

const CHANGES: Change[] = [
  {
    scene: "hill",
    kind: "added",
    what: "Low warm light from the left.",
    why: "The prompt gave no lighting for this scene.",
  },
  {
    scene: "hill",
    kind: "changed",
    what: "The scene lasts as long as its line.",
    why: "The line takes about 4 seconds to speak and the scene was given 2.",
  },
  {
    kind: "not_possible",
    what: "A piano under the last scene.",
    why: "The studio can only play its own soft music bed under the whole video.",
  },
];

const saved = () => Promise.resolve();
const refused = () => Promise.reject(new Error("The change could not be saved. Try again."));

const meta = {
  title: "Workspace/Shot card",
  component: ShotCard,
  args: {
    scene: SPOKEN,
    asset: PICTURE,
    index: 0,
    seconds: 3.7,
    characters: [KEEPER],
    onSave: saved,
  },
  decorators: [
    (Story) => (
      <div className="max-w-3xl p-4 sm:p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ShotCard>;

export default meta;
type Story = StoryObj<typeof meta>;

const PHONE = { viewport: { value: "phone", isRotated: false } };

/** A spoken shot: the owner's line, text on screen, the picture, who is in it, camera, motion. */
export const Spoken: Story = {};

/** A line the studio wrote is marked as such. */
export const WrittenByTheStudio: Story = {
  args: { scene: { ...SPOKEN, narration_from: "studio" } },
};

/** A silent shot has no line and takes its seconds. */
export const Silent: Story = {
  args: { scene: SILENT, asset: { id: "a_sea", prompt: "A flat grey sea at dawn.", characters: [] }, seconds: 4 },
};

/** Saving fails: the form stays open with what was typed and says why. Press Edit scene, then Save. */
export const SaveFails: Story = { args: { onSave: refused } };

/** On a phone the card shows the line, and Details opens the rest. */
export const OnAPhone: Story = { globals: PHONE };

/** Everything the studio added, changed or could not do, in three groups. */
export const WhatTheStudioChanged: Story = {
  render: () => <ChangesPanel changes={CHANGES} scenes={[SPOKEN, SILENT]} />,
};

/** The good case: the plan is the prompt as it was written. */
export const NothingWasChanged: Story = {
  render: () => <ChangesPanel changes={[]} scenes={[SPOKEN, SILENT]} />,
};

/** The style and the characters, written once for the whole video. */
export const LookAndCharacters: Story = {
  render: () => (
    <LookPanel
      style="Soft watercolour, muted blues, grain of rough paper."
      characters={[KEEPER]}
      onSave={saved}
    />
  ),
};

/** A video without characters and without a style. */
export const NoLookYet: Story = {
  render: () => <LookPanel style="" characters={[]} onSave={saved} />,
};
