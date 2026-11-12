import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { EpisodeOut } from "@/api/client";

import { BoardView } from "./board";

function episode(number: number, fields: Partial<EpisodeOut>): EpisodeOut {
  return {
    id: `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`,
    idea: `Idea number ${number}`,
    title: null,
    state: "brief",
    awaiting_approval: false,
    gate: null,
    spec_version: null,
    stale_from_state: null,
    stale_scenes: {},
    resting: false,
    target_duration_s: 45,
    created_at: "2026-11-12T08:00:00Z",
    ...fields,
  };
}

const EPISODES: EpisodeOut[] = [
  episode(1, { title: "The Lighthouse Keeper", state: "direction", awaiting_approval: true, gate: "plan" }),
  episode(2, { title: "Two Chairs", state: "critique", awaiting_approval: true, gate: "review" }),
  episode(3, { title: "The Second Bowl", state: "research" }),
  episode(4, { title: "Small Steps", state: "asset_gen" }),
  episode(5, { title: "Edited later", state: "render", stale_from_state: "voice" }),
  episode(6, { title: "The Long Road Home", state: "done" }),
  episode(7, { idea: "A baker who gives away the first loaf every morning" }),
];

const meta = {
  title: "Screens/Board",
  component: BoardView,
  args: {
    api: { kind: "loading" },
    episodes: { kind: "ready", episodes: EPISODES, total: EPISODES.length, stale: false },
    onRetry: () => undefined,
    onShowMore: () => Promise.resolve(),
  },
  decorators: [
    (Story) => (
      <div className="p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof BoardView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithEpisodes: Story = {};

export const Phone: Story = {
  globals: { viewport: { value: "phone", isRotated: false } },
};

export const Tablet: Story = {
  globals: { viewport: { value: "tablet", isRotated: false } },
};

export const Loading: Story = { args: { episodes: { kind: "loading" } } };

export const Empty: Story = {
  args: { episodes: { kind: "ready", episodes: [], total: 0, stale: false } },
};

export const LoadFailed: Story = {
  args: {
    episodes: {
      kind: "error",
      message: "The database is not answering. Start it and try again.",
    },
  },
};

export const RefreshFailed: Story = {
  args: { episodes: { kind: "ready", episodes: EPISODES, total: EPISODES.length, stale: true } },
};

export const MoreThanOnePage: Story = {
  args: { episodes: { kind: "ready", episodes: EPISODES, total: 120, stale: false } },
};
