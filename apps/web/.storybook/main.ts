import type { StorybookConfig } from "@storybook/nextjs-vite";

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.tsx"],
  framework: { name: "@storybook/nextjs-vite", options: {} },
  // No usage data leaves this machine.
  core: { disableTelemetry: true },
};

export default config;
