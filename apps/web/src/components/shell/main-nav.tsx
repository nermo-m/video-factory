"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import {
  BOTTOM_BAR_HREFS,
  CollapseIcon,
  FLOATING_BUTTON_PATHS,
  MORE_HREFS,
  MoreIcon,
  NAV_ITEMS,
  NEW_EPISODE_HREF,
  type NavItem,
  PlusIcon,
  isCurrent,
} from "./nav-items";

const COLLAPSED_KEY = "vfs.sidebar.collapsed";

/**
 * Side navigation for tablet and up (design doc section 11.5).
 *
 * - 640 to 1023 px: a 64 px icon rail with tooltips.
 * - 1024 px and up: a 232 px sidebar that the owner can collapse to the 64 px rail.
 *
 * The layout is decided in CSS, so the right navigation is in the first paint at any width.
 */
export function SideNav() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(COLLAPSED_KEY) === "true");
  }, []);

  function toggle() {
    setCollapsed((current) => {
      window.localStorage.setItem(COLLAPSED_KEY, String(!current));
      return !current;
    });
  }

  // Labels are visible only in the expanded desktop sidebar.
  const label = cn("hidden", !collapsed && "lg:inline");
  const rowLayout = cn("justify-center", !collapsed && "lg:justify-start lg:px-3");

  return (
    <nav
      aria-label="Main"
      data-testid="side-nav"
      data-collapsed={collapsed}
      className={cn(
        "sticky top-13 hidden h-[calc(100dvh-3.25rem)] w-16 shrink-0 flex-col gap-1.5 border-r bg-background px-2 py-5 sm:flex",
        !collapsed && "lg:w-58 lg:px-4",
      )}
    >
      <RailTooltip label="New episode" collapsed={collapsed}>
        <Link
          href={NEW_EPISODE_HREF}
          className={cn(
            "mb-3.5 flex h-11 items-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground hover:bg-primary/90",
            "justify-center",
          )}
        >
          <span className={cn(!collapsed && "lg:hidden")}>
            <PlusIcon />
          </span>
          <span className={cn("sr-only", !collapsed && "lg:not-sr-only")}>New episode</span>
        </Link>
      </RailTooltip>

      {NAV_ITEMS.map((item) => (
        <RailTooltip key={item.href} label={item.label} collapsed={collapsed}>
          <NavLink item={item} current={isCurrent(pathname, item.href)} className={rowLayout}>
            <span className={cn("sr-only", !collapsed && "lg:not-sr-only")}>{item.label}</span>
          </NavLink>
        </RailTooltip>
      ))}

      <button
        type="button"
        onClick={toggle}
        aria-expanded={!collapsed}
        aria-label={collapsed ? "Expand the sidebar" : "Collapse the sidebar"}
        className={cn(
          "mt-auto hidden h-11 items-center gap-3 rounded-lg text-sm font-medium text-muted-foreground hover:bg-raised hover:text-foreground lg:flex",
          rowLayout,
        )}
      >
        <span className={cn("transition-transform", collapsed && "rotate-180")}>
          <CollapseIcon />
        </span>
        <span className={label}>Collapse</span>
      </button>
    </nav>
  );
}

function NavLink({
  item,
  current,
  className,
  onNavigate,
  children,
  ...props
}: {
  item: NavItem;
  current: boolean;
  className?: string;
  onNavigate?: () => void;
  children: React.ReactNode;
} & Omit<React.ComponentProps<typeof Link>, "href" | "onClick" | "className">) {
  const ItemIcon = item.icon;
  return (
    // The remaining props come from the tooltip trigger that wraps this link in the rail.
    <Link
      {...props}
      href={item.href}
      onClick={onNavigate}
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex h-11 items-center gap-3 rounded-lg text-sm font-medium text-muted-foreground hover:bg-raised hover:text-foreground",
        current && "bg-raised font-semibold text-foreground",
        className,
      )}
    >
      <ItemIcon />
      {children}
    </Link>
  );
}

/** Shows the label as a tooltip whenever the navigation is an icon rail. */
function RailTooltip({
  label,
  collapsed,
  children,
}: {
  label: string;
  collapsed: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="right" className={cn(!collapsed && "lg:hidden")}>
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Phone navigation (under 640 px): a bottom bar with Board, Videos, Jobs and More.
 * Library and Settings are inside More. A floating New episode button sits above the bar
 * on Board and Videos.
 */
export function BottomNav() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const barItems = NAV_ITEMS.filter((item) => BOTTOM_BAR_HREFS.includes(item.href));
  const moreItems = NAV_ITEMS.filter((item) => MORE_HREFS.includes(item.href));
  const moreIsCurrent = moreItems.some((item) => isCurrent(pathname, item.href));
  const cell =
    "flex min-h-11 flex-col items-center justify-center gap-1 text-[0.6875rem] font-medium text-muted-foreground";

  return (
    <div className="sm:hidden">
      {FLOATING_BUTTON_PATHS.includes(pathname) && (
        <Link
          href={NEW_EPISODE_HREF}
          data-testid="floating-new-episode"
          className="fixed right-4 bottom-21 z-20 flex h-13 items-center rounded-full bg-primary px-5 text-[0.9375rem] font-semibold text-primary-foreground shadow-[0_6px_18px_rgb(0_0_0/0.5)]"
        >
          New episode
        </Link>
      )}

      <nav
        aria-label="Main"
        data-testid="bottom-nav"
        className="fixed inset-x-0 bottom-0 z-10 grid h-17 grid-cols-4 border-t bg-surface"
      >
        {barItems.map((item) => {
          const current = isCurrent(pathname, item.href);
          const ItemIcon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={current ? "page" : undefined}
              className={cn(cell, current && "font-semibold text-primary")}
            >
              <ItemIcon />
              {item.label}
            </Link>
          );
        })}

        <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
          <SheetTrigger className={cn(cell, moreIsCurrent && "font-semibold text-primary")}>
            <MoreIcon />
            More
          </SheetTrigger>
          <SheetContent side="bottom" className="gap-0 rounded-t-xl border-t bg-surface pb-4">
            <SheetHeader>
              <SheetTitle className="font-heading text-lg">More</SheetTitle>
              <SheetDescription>Library and settings.</SheetDescription>
            </SheetHeader>
            <ul className="flex flex-col gap-1.5 px-4">
              {moreItems.map((item) => (
                <li key={item.href}>
                  <NavLink
                    item={item}
                    current={isCurrent(pathname, item.href)}
                    className="px-3"
                    onNavigate={() => setMoreOpen(false)}
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </SheetContent>
        </Sheet>
      </nav>
    </div>
  );
}
