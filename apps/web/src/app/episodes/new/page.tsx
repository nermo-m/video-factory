import type { Metadata } from "next";

import { EmptyState, PageHeader } from "@/components/page";

export const metadata: Metadata = { title: "New episode" };

export default function Page() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="New episode" />
      <EmptyState title="Not built yet">Starting an episode from an idea arrives with the planning milestone. Until then the studio only runs its foundation.</EmptyState>
    </div>
  );
}
