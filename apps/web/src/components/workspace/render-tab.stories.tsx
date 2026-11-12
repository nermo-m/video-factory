import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { EpisodeDetail, JobOut, RenderOut } from "@/api/client";

import { RenderTab, StepFailed } from "./render-tab";

function job(type: string, status: JobOut["status"], fields: Partial<JobOut> = {}): JobOut {
  return {
    id: `00000000-0000-4000-8000-${Math.random().toString(16).slice(2, 14).padEnd(12, "0")}`,
    type,
    status,
    error_class: null,
    error_message: null,
    attempts: 1,
    created_at: "2026-11-12T08:05:00Z",
    started_at: "2026-11-12T08:05:01Z",
    finished_at: status === "succeeded" || status === "failed" ? "2026-11-12T08:05:09Z" : null,
    ...fields,
  };
}

function episode(fields: Partial<EpisodeDetail>): EpisodeDetail {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    idea: "A keeper who climbs the hill every morning",
    title: "The Lighthouse Keeper",
    state: "render",
    awaiting_approval: false,
    gate: null,
    spec_version: 1,
    stale_from_state: null,
    stale_scenes: {},
    resting: false,
    target_duration_s: 45,
    created_at: "2026-11-12T08:00:00Z",
    jobs: [],
    ...fields,
  };
}

const RENDER: RenderOut = {
  id: "00000000-0000-4000-8000-0000000000f1",
  kind: "draft",
  created_at: "2026-11-12T08:09:00Z",
  duration_s: 44.25,
  // No file is behind this address in Storybook: the player shows its empty state.
  video_url: "/api/v1/files/jobs/render.join/ab/abcdef/video.mp4",
  contact_sheet_url: "/api/v1/files/jobs/render.join/ab/abcdef/video_contact_sheet.jpg",
  spec_version: 1,
};

const many = (type: string, statuses: JobOut["status"][]) => statuses.map((status) => job(type, status));

const meta = {
  title: "Workspace/Render tab",
  component: RenderTab,
  args: { episode: episode({ state: "direction", awaiting_approval: true, gate: "plan" }), render: null },
  decorators: [
    (Story) => (
      <div className="p-4 sm:p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof RenderTab>;

export default meta;
type Story = StoryObj<typeof meta>;

const PHONE = { viewport: { value: "phone", isRotated: false } };
const TABLET = { viewport: { value: "tablet", isRotated: false } };

export const Empty: Story = {};

const VOICE = episode({
  state: "voice",
  jobs: many("gen.voice", ["running", "queued", "queued", "queued", "succeeded", "succeeded", "succeeded"]),
});
export const RecordingTheVoice: Story = { args: { episode: VOICE } };
export const RecordingTheVoicePhone: Story = { args: { episode: VOICE }, globals: PHONE };

export const EncodingScenes: Story = {
  args: {
    episode: episode({
      jobs: many("render.scene", ["running", "running", "succeeded", "succeeded", "succeeded", "succeeded", "succeeded"]),
    }),
  },
};

export const Joining: Story = {
  args: {
    episode: episode({ jobs: [job("render.join", "running"), ...many("render.scene", Array(7).fill("succeeded"))] }),
  },
};

const DONE = { episode: episode({ resting: true, jobs: [job("render.join", "succeeded")] }), render: RENDER };
export const Video: Story = { args: DONE };
export const VideoPhone: Story = { args: DONE, globals: PHONE };
export const VideoTablet: Story = { args: DONE, globals: TABLET };

const STOPPED = episode({
  state: "voice",
  jobs: [
    job("gen.voice", "failed", {
      error_class: "needs_owner",
      error_message:
        "The voice model files are missing and there is no bundled sample for this narration. Download the voice model with: make models",
    }),
    ...many("gen.voice", ["succeeded", "succeeded"]),
  ],
});

/** The reason a step stopped. It is shown above the tabs, whatever tab is open. */
export const StepStopped: Story = {
  args: { episode: STOPPED },
  render: (args) => <StepFailed episode={args.episode} reload={() => Promise.resolve()} />,
};
export const StepStoppedPhone: Story = { ...StepStopped, globals: PHONE };
