import type { Metadata } from "next";

import { EmptyState, PageHeader } from "@/components/page";

export const metadata: Metadata = { title: "Jobs" };

export default function Page() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Jobs" />
      <EmptyState title="No jobs yet">Every piece of work the studio runs is listed here with its status, attempts, duration and cost.</EmptyState>
    </div>
  );
}
