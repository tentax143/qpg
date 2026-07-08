/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false,
  allowedDevOrigins: [
    "qgen.ramcoad.com",
    "172.16.71.183",
  ],
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "qgen.ramcoad.com",
      },
    ],
  },
};

export default nextConfig;
