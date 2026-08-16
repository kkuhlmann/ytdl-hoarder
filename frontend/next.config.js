/** @type {import('next').NextConfig} */

// Next 16 blocks cross-origin requests to dev resources (/_next/*, HMR) unless
// the origin is listed in allowedDevOrigins. This was advisory in Next 15 and
// is enforced in 16, so anyone reaching the dev server as something other than
// localhost -- a LAN IP, a Tailscale MagicDNS name, a reverse proxy -- loses
// hot reload until their host is allowed.
//
// The hostname is derived from NEXT_PUBLIC_BACKEND_API, since the host you
// reach the backend on is the host you reach the frontend on; setting that one
// variable (which non-localhost access already requires) is therefore enough.
// ALLOWED_DEV_ORIGINS, comma-separated, adds any extras. localhost is always
// permitted and does not need listing. None of this affects the production
// static export, which has no dev server.
function devOrigins() {
  const origins = new Set()

  const api = process.env.NEXT_PUBLIC_BACKEND_API
  if (api) {
    try {
      origins.add(new URL(api).hostname)
    } catch {
      // Not a parseable URL — nothing to derive, fall through to the explicit list.
    }
  }

  for (const entry of (process.env.ALLOWED_DEV_ORIGINS || "").split(",")) {
    const host = entry.trim()
    if (host) origins.add(host)
  }

  return [...origins]
}

const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  allowedDevOrigins: devOrigins(),
}

module.exports = nextConfig
