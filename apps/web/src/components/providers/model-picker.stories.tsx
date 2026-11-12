import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import type { ProviderOut } from "@/api/client";

import { ModelPicker } from "./model-picker";

function usage(calls: number, images = 0) {
  return { calls, images, input_tokens: calls * 900, output_tokens: calls * 300, cost_usd: "0.000000" };
}

function provider(fields: Partial<ProviderOut>): ProviderOut {
  return {
    id: "claude_plan",
    title: "Claude plan",
    billing: "plan",
    state: "ok",
    state_source: "app",
    limited_until: null,
    last_checked_at: "2026-11-12T15:57:00Z",
    last_error: null,
    usage: { five_hours: usage(5), seven_days: usage(40) },
    usage_source: "app",
    budget: { calls_5h: 20, calls_7d: 150, images_5h: 5, images_7d: 30, usd_5h: "0", usd_7d: "0" },
    budget_used: 0.27,
    ...fields,
  };
}

const CHATGPT = provider({
  id: "chatgpt_plan",
  title: "ChatGPT plan",
  usage: { five_hours: usage(2, 1), seven_days: usage(9, 4) },
});

const meta = {
  title: "Providers/Model picker",
  component: ModelPicker,
  args: {
    title: "Model for planning",
    providers: [provider({}), CHATGPT],
    value: "claude_plan",
    onChange: () => undefined,
    checking: false,
    onCheck: () => undefined,
  },
  decorators: [
    (Story) => (
      <div className="p-4 sm:p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ModelPicker>;

export default meta;
type Story = StoryObj<typeof meta>;

const PHONE = { viewport: { value: "phone", isRotated: false } };

export const Ready: Story = {};
export const ReadyPhone: Story = { globals: PHONE };

const NEAR = [
  provider({ state: "near_budget", usage: { five_hours: usage(17), seven_days: usage(60) }, budget_used: 0.85 }),
  CHATGPT,
];
export const NearBudget: Story = { args: { providers: NEAR } };
export const NearBudgetPhone: Story = { args: { providers: NEAR }, globals: PHONE };

const PAUSED = [
  provider({ state: "paused_by_budget", usage: { five_hours: usage(20), seven_days: usage(60) }, budget_used: 1 }),
  CHATGPT,
];
export const Paused: Story = { args: { providers: PAUSED, value: "chatgpt_plan" } };
export const PausedPhone: Story = { args: { providers: PAUSED, value: "chatgpt_plan" }, globals: PHONE };

const LIMITED = [
  provider({}),
  {
    ...CHATGPT,
    state: "limited" as const,
    state_source: "tool" as const,
    limited_until: "2026-11-12T18:40:00Z",
    last_error: "You've hit your usage limit.",
    usage: { five_hours: usage(4, 5), seven_days: usage(30, 19) },
    budget_used: 1,
  },
];
export const Limited: Story = { args: { providers: LIMITED } };
export const LimitedPhone: Story = { args: { providers: LIMITED }, globals: PHONE };

export const Checking: Story = { args: { checking: true } };

export const ShownOnly: Story = { args: { onChange: undefined, value: undefined, title: "Models in use" } };

export const PaidInApiMode: Story = {
  args: {
    providers: [
      provider({
        id: "anthropic_api",
        title: "Anthropic API",
        billing: "api",
        budget: { calls_5h: 0, calls_7d: 0, images_5h: 0, images_7d: 0, usd_5h: "1", usd_7d: "5" },
        usage: {
          five_hours: { ...usage(6), cost_usd: "0.420000" },
          seven_days: { ...usage(21), cost_usd: "1.310000" },
        },
      }),
    ],
    value: "anthropic_api",
  },
};
