import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { AssetList, AssetOut, EpisodeDetail } from "@/api/client";

import { AssetsTab } from "./assets-tab";

const EPISODE: EpisodeDetail = {
  id: "00000000-0000-4000-8000-000000000001",
  idea: "A grandfather who writes one line in a notebook every evening",
  title: "One Line Every Evening",
  state: "asset_gen",
  awaiting_approval: true,
  gate: "assets",
  spec_version: 1,
  stale_from_state: null,
  stale_scenes: {},
  resting: false,
  target_duration_s: 45,
  created_at: "2026-11-13T08:00:00Z",
  jobs: [],
};

const SCENES = [
  { id: "s01_hook", kind: "title" },
  { id: "s02_grandpa", kind: "scroll" },
  { id: "s03_habit", kind: "scroll" },
  { id: "s04_leaving", kind: "scroll" },
];

function picture(id: string, fields: Partial<AssetOut> = {}): AssetOut {
  return {
    id,
    kind: "image",
    origin: "generated",
    used_in: ["s03_habit"],
    becomes_clip: false,
    prompt: "A worn blue notebook lies open on an old wooden table, warm lamp light, flat paper-cut shapes.",
    filename: null,
    resolved: true,
    generating: false,
    // No file is behind this address in Storybook: the picture shows its name instead.
    image_url: `/api/v1/files/jobs/gen.image/ab/abcdef/${id}.png`,
    model: "codex image tool",
    uploaded: false,
    versions: 1,
    licence: "Generated on the owner's ChatGPT plan (OpenAI terms of use)",
    rights_status: "needs_review",
    contains_third_party_ip: false,
    ...fields,
  };
}

const LIBRARY = picture("a_lamp_room", {
  origin: "library",
  prompt: null,
  model: null,
  licence: "MIT",
  rights_status: "cleared",
  used_in: ["s02_grandpa"],
});

function list(assets: AssetOut[]): AssetList {
  return { assets, unresolved: assets.filter((asset) => !asset.resolved).length, rights_problems: [] };
}

const meta = {
  title: "Workspace/Assets tab",
  component: AssetsTab,
  args: {
    episode: EPISODE,
    scenes: SCENES,
    reload: () => Promise.resolve(),
    assets: list([LIBRARY, picture("a_notebook_lines"), picture("a_doorway_handover", { used_in: ["s04_leaving"] })]),
  },
  decorators: [
    (Story) => (
      <div className="p-4 sm:p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof AssetsTab>;

export default meta;
type Story = StoryObj<typeof meta>;

const PHONE = { viewport: { value: "phone", isRotated: false } };
const TABLET = { viewport: { value: "tablet", isRotated: false } };

export const Pictures: Story = {};
export const PicturesPhone: Story = { globals: PHONE };
export const PicturesTablet: Story = { globals: TABLET };

/** Before the plan is approved there are no pictures to show. */
export const NotYet: Story = { args: { assets: null } };

const MAKING = list([
  LIBRARY,
  picture("a_notebook_lines", { resolved: false, image_url: null, generating: true, versions: 0 }),
  picture("a_doorway_handover", { resolved: false, image_url: null, versions: 0, used_in: ["s04_leaving"] }),
  picture("a_my_photo", {
    origin: "uploaded",
    prompt: null,
    filename: "my_photo.png",
    resolved: false,
    image_url: null,
    versions: 0,
  }),
]);
export const BeingMade: Story = { args: { assets: MAKING } };
export const BeingMadePhone: Story = { args: { assets: MAKING }, globals: PHONE };
