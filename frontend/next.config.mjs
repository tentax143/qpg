/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: [
    "qgen.ramcoad.com",
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
