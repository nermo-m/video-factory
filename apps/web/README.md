# apps/web

The interface: Next.js with TypeScript, Tailwind CSS and shadcn/ui. It talks only to
`apps/api`, through the generated typed client in `src/api/`. The responsive layout rules
are in design doc section 11.5, and the mockups win where they differ.

- `src/app/globals.css`: the design tokens from section 11.1.
- `src/components/shell/`: status strip and navigation (sidebar, rail, bottom bar).
- `e2e/`: Playwright and axe tests with approved screenshots. Run `make e2e`.
- `*.stories.tsx`: Storybook stories at phone, tablet and desktop size. Run `make storybook`.
