import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Banner, EmptyState, PageHeader } from "./page";

function Screen() {
  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader title="Board" note="0 episodes" />
      <Banner>Demo mode is on. Models, images and clips are simulated with bundled samples.</Banner>
      <EmptyState title="No episodes yet">
        An episode starts as one idea and ends as a finished vertical video.
      </EmptyState>
    </div>
  );
}

const meta = { title: "Screens/Empty state", component: Screen } satisfies Meta<typeof Screen>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Desktop: Story = {};

export const Phone: Story = {
  globals: { viewport: { value: "phone", isRotated: false } },
};

export const Tablet: Story = {
  globals: { viewport: { value: "tablet", isRotated: false } },
};
