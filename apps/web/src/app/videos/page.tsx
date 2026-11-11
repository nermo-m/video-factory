import type { Metadata } from "next";

import { EmptyState, PageHeader } from "@/components/page";

export const metadata: Metadata = { title: "Videos" };

export default function Page() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Videos" />
      <EmptyState title="No videos yet">Every rendered video appears here for review. You can finish it, adjust it or remake it, and earlier versions stay playable.</EmptyState>
    </div>
  );
}
