import type { Metadata } from "next";

import { EmptyState, PageHeader } from "@/components/page";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Settings" />
      <EmptyState title="Settings are not built yet">The channel template, provider status, export folder and usage limits will be set here.</EmptyState>
    </div>
  );
}
