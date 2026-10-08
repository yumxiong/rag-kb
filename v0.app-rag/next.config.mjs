/** @type {import('next').NextConfig} */
const nextConfig = {
  images: { unoptimized: true },
  async rewrites() {
    const backend = process.env.RAG_BACKEND_ORIGIN || 'http://127.0.0.1:18000'
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }]
  },
}
export default nextConfig
