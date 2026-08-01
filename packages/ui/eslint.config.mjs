import globals from "globals";
import tseslint from "typescript-eslint";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";

export default tseslint.config(
  // Ignore build output and deps
  {
    ignores: ["dist/**", "node_modules/**"],
  },

  // TypeScript recommended (sets up the TS parser + rules)
  ...tseslint.configs.recommended,

  // React + React Hooks for the component library
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: {
      react,
      "react-hooks": reactHooks,
    },
    languageOptions: {
      globals: {
        ...globals.browser,
      },
    },
    settings: {
      react: { version: "detect" },
    },
    rules: {
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,

      // New JSX transform (React 19): no need to import React in scope.
      "react/react-in-jsx-scope": "off",
      // Prop types are redundant in a TypeScript codebase.
      "react/prop-types": "off",

      // Keep these as warnings so `eslint src/` stays green while still surfacing them.
      "@typescript-eslint/no-explicit-any": "warn",
      "react-hooks/exhaustive-deps": "warn",
    },
  }
);
