import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { TooltipProvider } from "@/components/ui/tooltip";

import { BottomNav, SideNav } from "./main-nav";

function Navigation() {
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex min-h-dvh">
        <SideNav />
        <p className="p-6 text-muted-foreground">
          The navigation follows the width: sidebar, icon rail or bottom bar.
        </p>
      </div>
      <BottomNav />
    </TooltipProvider>
  );
}

const meta = {
  title: "Shell/Navigation",
  component: Navigation,
  parameters: { nextjs: { appDirectory: true, navigation: { pathname: "/" } } },
} satisfies Meta<typeof Navigation>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DesktopSidebar: Story = {
  globals: { viewport: { value: "desktop", isRotated: false } },
};

export const TabletRail: Story = {
  globals: { viewport: { value: "tablet", isRotated: false } },
};

export const PhoneBottomBar: Story = {
  globals: { viewport: { value: "phone", isRotated: false } },
};

export const PhoneOnJobs: Story = {
  parameters: { nextjs: { appDirectory: true, navigation: { pathname: "/jobs" } } },
  globals: { viewport: { value: "phone", isRotated: false } },
};
