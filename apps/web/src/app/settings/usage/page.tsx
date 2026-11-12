import type { Metadata } from "next";

import { UsagePage } from "@/components/providers/usage-page";

export const metadata: Metadata = { title: "Usage and limits" };

export default function Page() {
  return <UsagePage />;
}
