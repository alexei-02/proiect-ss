/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.API_BASE_URL || 'http://localhost:8989'}/api/:path*`,
      },
    ];
  },
};
module.exports = nextConfig;
