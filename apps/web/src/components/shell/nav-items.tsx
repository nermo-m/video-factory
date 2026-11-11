import type { ReactNode } from "react";

/** Stroke icon in the style of the mockups: 24 px grid, round caps, current colour. */
function Icon({ children, strokeWidth = 2 }: { children: ReactNode; strokeWidth?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className="size-5 shrink-0"
    >
      {children}
    </svg>
  );
}

export const BoardIcon = () => (
  <Icon>
    <path d="M4 5h6v14H4zM14 5h6v8h-6z" />
  </Icon>
);
export const VideosIcon = () => (
  <Icon>
    <rect x="4" y="5" width="16" height="14" rx="2" />
    <path d="M10 9l5 3-5 3z" />
  </Icon>
);
export const LibraryIcon = () => (
  <Icon>
    <path d="M4 6h16M4 12h16M4 18h16" />
  </Icon>
);
export const JobsIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="8" />
    <path d="M12 8v4l3 2" />
  </Icon>
);
export const SettingsIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
  </Icon>
);
export const MoreIcon = () => (
  <Icon strokeWidth={2.5}>
    <path d="M5 12h.01M12 12h.01M19 12h.01" />
  </Icon>
);
export const PlusIcon = () => (
  <Icon strokeWidth={2.5}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);
export const CollapseIcon = () => (
  <Icon>
    <path d="M15 6l-6 6 6 6" />
  </Icon>
);
export const SpinnerIcon = () => (
  <Icon strokeWidth={3}>
    <path d="M12 3a9 9 0 1 0 9 9" />
  </Icon>
);
export const BellIcon = () => (
  <Icon>
    <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4" />
  </Icon>
);

export interface NavItem {
  href: string;
  label: string;
  icon: () => ReactNode;
}

/** Section 11.5: Board, Videos, Library, Jobs, Settings. */
export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Board", icon: BoardIcon },
  { href: "/videos", label: "Videos", icon: VideosIcon },
  { href: "/library", label: "Library", icon: LibraryIcon },
  { href: "/jobs", label: "Jobs", icon: JobsIcon },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
];

/** On a phone the bottom bar shows four items. Library and Settings sit behind More. */
export const BOTTOM_BAR_HREFS = ["/", "/videos", "/jobs"];
export const MORE_HREFS = ["/library", "/settings"];

export const NEW_EPISODE_HREF = "/episodes/new";

/** The floating New episode button appears on Board and Videos only (section 11.5). */
export const FLOATING_BUTTON_PATHS = ["/", "/videos"];

export function isCurrent(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}
