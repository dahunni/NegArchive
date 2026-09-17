/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow large client request bodies to pass through middleware/rewrites (proxy)
  // Default is 10MB; set to 1GB for bulk image uploads.
  middlewareClientMaxBodySize: 1024 * 1024 * 1024,
  typescript: {
    ignoreBuildErrors: true,
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
