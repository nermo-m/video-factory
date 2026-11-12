import type { Metadata } from "next";

import { Board } from "@/components/board/board";
import { NewEpisodeDialog } from "@/components/episodes/new-episode-dialog";

export const metadata: Metadata = { title: "New episode" };

/** The Board with the New episode dialog open over it. */
export default function Page() {
  return (
    <>
      <Board />
      <NewEpisodeDialog />
    </>
  );
}
