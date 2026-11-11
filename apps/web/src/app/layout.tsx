import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Video Factory Studio",
  description: "Turn one idea into a finished short vertical video.",
};

// Placeholder styling with the design tokens. The app shell card replaces it with the
// real layout, fonts and Tailwind theme.
const bodyStyle = {
  margin: 0,
  minHeight: "100vh",
  background: "#0B0F1A",
  color: "#E8ECF4",
  fontFamily: "system-ui, sans-serif",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={bodyStyle}>{children}</body>
    </html>
  );
}
