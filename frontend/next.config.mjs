/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow large client request bodies to pass through middleware/rewrites (proxy)
  // Default is 10MB; set to 1GB for bulk image uploads. This is a real Next 16 key
  // (`middlewareClientMaxBodySize` in next/dist/server/config-schema), not a leftover.
  middlewareClientMaxBodySize: 1024 * 1024 * 1024,
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
