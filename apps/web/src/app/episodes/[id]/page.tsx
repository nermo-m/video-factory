import type { Metadata } from "next";

import { Workspace } from "@/components/workspace/workspace";

export const metadata: Metadata = { title: "Episode" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Workspace episodeId={id} />;
}
