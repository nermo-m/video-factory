import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/node_modules/**",
      "**/.next/**",
      "**/out/**",
      "**/dist/**",
      "**/storybook-static/**",
      "apps/web/e2e/.results/**",
      "**/next-env.d.ts",
      // Generated from apps/api/openapi.json. It is checked for drift, not for style.
      "apps/web/src/api/generated/**",
      ".venv/**",
    ],
  },
  js.configs.recommended,
  {
    files: ["**/*.{js,mjs,cjs}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.node },
    },
  },
  {
    files: ["apps/web/**/*.{ts,tsx}"],
    extends: [...tseslint.configs.strict, ...tseslint.configs.stylistic],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
);
