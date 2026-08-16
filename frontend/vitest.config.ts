import path from "node:path"
import { defineConfig } from "vitest/config"

export default defineConfig({
  resolve: {
    // Mirrors tsconfig's "@/*": ["./*"] — the app's only alias.
    alias: { "@": path.resolve(__dirname) },
  },
  test: {
    environment: "node",
    include: ["app/**/*.test.{ts,tsx}"],
    // Non-UTC on purpose: the dev container and CI both default to TZ=UTC, under which
    // local-time and UTC parsing of the same string land on the same instant, so the
    // utils.ts trailing-Z coercion tests can't tell a working coercion from a deleted one.
    env: { TZ: "America/New_York" },
  },
})
