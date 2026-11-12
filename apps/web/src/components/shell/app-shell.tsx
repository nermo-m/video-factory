import type { ReactNode } from "react";

import { EpisodesProvider } from "@/components/episodes/episodes-provider";
import { ProvidersProvider } from "@/components/providers/providers-provider";

import { BottomNav, SideNav } from "./main-nav";
import { StatusStrip } from "./status-strip";

/**
 * The frame around every screen (design doc section 11.5): status strip on top, then
 * a sidebar on desktop, an icon rail on tablet or a bottom bar on a phone.
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <ProvidersProvider>
    <EpisodesProvider>
      <div className="flex min-h-dvh flex-col">
        <a
          href="#content"
          className="sr-only z-50 rounded-lg bg-raised px-4 py-3 font-semibold text-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Skip to content
        </a>
        <StatusStrip />
        <div className="flex grow">
          <SideNav />
          {/* The bottom padding keeps content clear of the phone's bottom bar. */}
          <main id="content" className="min-w-0 grow px-4 pt-5 pb-28 sm:px-6 sm:pb-8 lg:px-8 lg:pt-7">
            {children}
          </main>
        </div>
        <BottomNav />
      </div>
    </EpisodesProvider>
    </ProvidersProvider>
  );
}
