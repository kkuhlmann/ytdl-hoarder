/** @type {import('next').NextConfig} */

// Next 16 blocks cross-origin requests to dev resources (/_next/*, HMR) unless
// the host matches allowedDevOrigins. This was advisory in Next 15 and is
// enforced in 16. A same-origin page load carries no Origin header and is never
// blocked, so what this actually governs is hot reload from another device.
//
// A dev server cannot know which address a developer will browse to, so the list
// is as wide as Next's matcher allows. "**.*" covers every IPv4 literal and every
// dotted name -- a LAN hostname, .local, Tailscale MagicDNS, a domain. A bare "*"
// or "**" matches NOTHING: matchWildcardDomain in
// next/dist/server/app-render/csrf-protection rejects a single-segment wildcard
// outright, so widening this by shortening the pattern would silently block
// everything. Nothing can match a single-label host (http://nas:3000) or an IPv6
// literal, which is what ALLOWED_DEV_ORIGINS is still here for. localhost is
// always permitted by Next itself. The production static export has no dev
// server and is unaffected.
const DEV_ORIGIN_PATTERNS = ["**.*"]

function devOrigins() {
  const extras = (process.env.ALLOWED_DEV_ORIGINS || "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean)

  return [...new Set([...DEV_ORIGIN_PATTERNS, ...extras])]
}

const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  allowedDevOrigins: devOrigins(),
}

module.exports = nextConfig
