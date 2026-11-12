import type { Metadata } from "next";

import { SettingsPage } from "@/components/providers/usage-page";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return <SettingsPage />;
}
