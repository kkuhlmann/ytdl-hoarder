/**
 * Bundle sw/sw.ts to out/sw.js and inject its precache manifest.
 *
 * Runs as npm's `postbuild`, so `next build` -- including Dockerfile.prod's
 * frontend-builder stage -- picks it up with no separate step. Emitting into out/
 * rather than public/ keeps a generated file out of the source tree and keeps the
 * worker away from `next dev`, where it would break HMR.
 */

import { createHash } from "node:crypto"
import { readdir, readFile, stat, writeFile } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"
import * as esbuild from "esbuild"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const outDir = path.join(root, "out")

/** Static assets outside /_next that the shell needs before it can render. */
const EXTRA_PRECACHE = ["/manifest.webmanifest", "/icon-192.png", "/icon-512.png"]

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const files = await Promise.all(
    entries.map((entry) => {
      const full = path.join(dir, entry.name)
      return entry.isDirectory() ? walk(full) : [full]
    })
  )
  return files.flat()
}

async function collectPrecache() {
  const staticDir = path.join(outDir, "_next", "static")
  const files = await walk(staticDir)
  return files
    // Source maps are debug payload the shell never needs, and they dominate the
    // precache size when a build emits them.
    .filter((file) => !file.endsWith(".map"))
    .map((file) => `/${path.relative(outDir, file).split(path.sep).join("/")}`)
    .sort()
}

async function totalBytes(urls) {
  const sizes = await Promise.all(
    urls.map(async (url) => {
      try {
        return (await stat(path.join(outDir, url))).size
      } catch {
        return 0
      }
    })
  )
  return sizes.reduce((a, b) => a + b, 0)
}

async function main() {
  try {
    await stat(path.join(outDir, "index.html"))
  } catch {
    throw new Error(`no static export at ${outDir} — run \`next build\` first`)
  }

  const precache = [...(await collectPrecache()), ...EXTRA_PRECACHE]

  // The shell's own HTML is not content-hashed, so hashing it alongside the asset
  // list is what makes the cache name change on a rebuild that only edits markup.
  const indexHtml = await readFile(path.join(outDir, "index.html"))
  const buildId = createHash("sha256")
    .update(indexHtml)
    .update(precache.join("\n"))
    .digest("hex")
    .slice(0, 16)

  await esbuild.build({
    entryPoints: [path.join(root, "sw", "sw.ts")],
    outfile: path.join(outDir, "sw.js"),
    bundle: true,
    minify: true,
    format: "iife",
    target: "es2022",
    // Mirrors tsconfig's "@/*": ["./*"], the app's only alias.
    alias: { "@": root },
    define: {
      __BUILD_ID__: JSON.stringify(buildId),
      __PRECACHE__: JSON.stringify(precache),
    },
    logLevel: "warning",
  })

  const bytes = await totalBytes(precache)
  const mib = (bytes / 1024 / 1024).toFixed(2)
  console.log(`service worker: build ${buildId}, ${precache.length} precached files (${mib} MiB)`)
}

await main()
