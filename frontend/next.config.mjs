/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    // Let a whole roll of TIFFs through the /api proxy. The default is 10 MB,
    // which is one 16-bit scan.
    //
    // M3 found this was doing nothing: the key was set at the top level, where
    // Next ignores it with a warning ("Unrecognized key(s) in object"). It lives
    // under `experimental`, and in Next 16 the spelling
    // `experimental.middlewareClientMaxBodySize` is deprecated in favour of
    // `proxyClientMaxBodySize` (next/dist/server/config.js warns and copies the
    // old name over). So: new name, right place, and the limit now applies.
    proxyClientMaxBodySize: 1024 * 1024 * 1024,
  },
  typescript: {
    // M3/R#30: type errors fail the build. `npx tsc --noEmit` is also a CI step.
    ignoreBuildErrors: false,
  },
  images: {
    unoptimized: true,
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost', port: '8010', pathname: '/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '8010', pathname: '/**' },
      { protocol: 'http', hostname: 'localhost', port: '8000', pathname: '/**' },
      { protocol: 'http', hostname: '127.0.0.1', port: '8000', pathname: '/**' },
    ],
  },
  async redirects() {
    // M1 moved things around. These are real 307s rather than pages that call
    // `redirect()`, because a prerendered page can only redirect after hydration —
    // a bookmark or a QR code should get the new location straight from the server.
    return [
      // Search is the filter bar on the roll list; `?q=` is carried over.
      { source: '/search', destination: '/', permanent: false },
      // The catalog is one Gear section with tabs.
      { source: '/cameras', destination: '/gear?tab=cameras', permanent: false },
      { source: '/lenses', destination: '/gear?tab=lenses', permanent: false },
      { source: '/filmstocks', destination: '/gear?tab=filmstocks', permanent: false },
      // Roll forms are a wizard dialog and a side panel, not pages.
      { source: '/films/new', destination: '/?new=1', permanent: false },
      { source: '/films/:id/edit', destination: '/films/:id?edit=1', permanent: false },
      // The frame viewer replaced the image edit page; uploading is a drop zone.
      { source: '/images/upload', destination: '/images', permanent: false },
      { source: '/images/:id/edit', destination: '/images/:id', permanent: false },
    ]
  },
  async rewrites() {
    // Proxy API requests through the frontend server to the backend service.
    // This allows running API and frontend on the same public port.
    // Prefer Docker service name if available; otherwise fall back to any
    // provided public base (local dev), and finally to the Docker default.
    const target =
      process.env.API_BASE
      || process.env.NEXT_PUBLIC_API_BASE
      || 'http://web:8000'
    return [
      {
        source: '/api/:path*',
        destination: `${target}/api/:path*`,
      },
      {
        // Catalog images and uploads are served by the backend from /static.
        // Without this the browser would have to reach the backend directly,
        // which it cannot do in Docker (the backend publishes no host port).
        source: '/static/:path*',
        destination: `${target}/static/:path*`,
      },
    ]
  },
}

export default nextConfig
