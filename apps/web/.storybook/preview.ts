import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/jetbrains-mono";
import "../src/app/globals.css";

import type { Preview } from "@storybook/nextjs-vite";

// The three sizes every component is shown at (design doc section 11.5).
export const SIZES = {
  phone: { name: "Phone 390", styles: { width: "390px", height: "844px" } },
  tablet: { name: "Tablet 820", styles: { width: "820px", height: "1180px" } },
  desktop: { name: "Desktop 1440", styles: { width: "1440px", height: "900px" } },
};

const preview: Preview = {
  parameters: {
    layout: "fullscreen",
    nextjs: { appDirectory: true },
    viewport: { options: SIZES },
  },
  initialGlobals: {
    viewport: { value: "desktop", isRotated: false },
  },
};

export default preview;
