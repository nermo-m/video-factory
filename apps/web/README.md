# apps/web

The interface: Next.js with TypeScript, Tailwind CSS and shadcn/ui. It talks only to
`apps/api`, through the generated typed client in `src/api/`. The responsive layout rules
are in design doc section 11.5, and the mockups win where they differ.

- `src/app/globals.css`: the design tokens from section 11.1.
- `src/components/shell/`: status strip and navigation (sidebar, rail, bottom bar).
- `src/components/episodes/`: the episode list every screen shares (read again every few
  seconds) and the New episode dialog, which is open whenever the address is
  `/episodes/new`.
- `src/components/board/`: the Board with its groups, cards and its loading, empty and
  error states.
- `src/components/workspace/`: the episode workspace at `/episodes/{id}`: pipeline, tabs,
  the Plan tab with scene cards, raw JSON, a change asked for in words, the gate bar for
  the plan and the pictures, the Assets tab with the pictures and Make again, the Render
  tab with the draft video and its download, and the reason a step stopped with a way to
  run it again.
- `src/components/providers/`: the providers every screen shares (read again every half
  minute), the model picker, the Usage page at `/settings/usage` and the Settings page.
- `src/lib/providers.ts`: how a provider's state and usage are worded.
- `src/lib/episodes.ts`: how an episode is shown: its group, its step and its status line.
- `src/lib/workspace.ts`: the workspace's wording: pipeline steps, scene facts, changes.
- `e2e/`: Playwright and axe tests with approved screenshots. Run `make e2e`.
  `demo.spec.ts` runs an idea through the real API and worker to a rendered video
  (FR-16) and saves that video to `e2e/.demo`, which CI uploads.
- `*.stories.tsx`: Storybook stories at phone, tablet and desktop size. Run `make storybook`.
