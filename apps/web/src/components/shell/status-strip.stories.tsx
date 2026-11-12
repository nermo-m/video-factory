import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { HealthResponse } from "@/api/client";

import { StatusStripView } from "./status-strip";

function health(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: "ok",
    provider_mode: "subscription",
    demo_mode: false,
    checks: {
      database: { status: "ok", message: null },
      storage: { status: "ok", message: null },
      comfyui: { status: "ok", message: null },
    },
    ...overrides,
  };
}

const meta = {
  title: "Shell/Status strip",
  component: StatusStripView,
  args: { state: { kind: "ready", health: health() }, runningJobs: 0, waitingForOwner: 0 },
} satisfies Meta<typeof StatusStripView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const GpuReady: Story = {};

export const Working: Story = {
  args: { runningJobs: 2, waitingForOwner: 2 },
};

export const DemoMode: Story = {
  args: {
    state: {
      kind: "ready",
      health: health({
        provider_mode: "demo",
        demo_mode: true,
        checks: {
          database: { status: "ok", message: null },
          storage: { status: "ok", message: null },
          comfyui: { status: "not_needed", message: null },
        },
      }),
    },
  },
};

export const GpuOffline: Story = {
  args: {
    state: {
      kind: "ready",
      health: health({
        checks: {
          database: { status: "ok", message: null },
          storage: { status: "ok", message: null },
          comfyui: { status: "offline", message: "ComfyUI is not running." },
        },
      }),
    },
  },
};

export const ProviderNearBudget: Story = {
  args: { providerWarning: { label: "Claude plan near budget", severe: false } },
};

export const ProviderLimited: Story = {
  args: { providerWarning: { label: "ChatGPT plan limited", severe: true } },
};

export const ProviderLimitedOnPhone: Story = {
  args: { runningJobs: 2, waitingForOwner: 2, providerWarning: { label: "ChatGPT plan limited", severe: true } },
  globals: { viewport: { value: "phone", isRotated: false } },
};

export const Loading: Story = { args: { state: { kind: "loading" } } };

export const ApiUnreachable: Story = { args: { state: { kind: "unreachable" } } };

export const WorkingOnPhone: Story = {
  args: { runningJobs: 2, waitingForOwner: 2 },
  globals: { viewport: { value: "phone", isRotated: false } },
};

export const WorkingOnTablet: Story = {
  args: { runningJobs: 2, waitingForOwner: 2 },
  globals: { viewport: { value: "tablet", isRotated: false } },
};
