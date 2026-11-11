import type { Metadata } from "next";

import { EmptyState, PageHeader } from "@/components/page";

export const metadata: Metadata = { title: "Library" };

export default function Page() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Library" />
      <EmptyState title="The library is empty">Reusable images, sprites and sounds live here with their tags, origin and licence.</EmptyState>
    </div>
  );
}
