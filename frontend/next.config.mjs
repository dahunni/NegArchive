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
    ],
  },
}

export default nextConfig
