/** @type {import('next').NextConfig} */
const nextConfig = {
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
    const target = process.env.API_BASE || 'http://localhost:8010'
    return [
      {
        source: '/api/:path*',
        destination: `${target}/api/:path*`,
      },
    ]
  },
}

export default nextConfig
