/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the project root: this app lives inside a larger git repo
  // (E:\GIT REPO MAIN\qpg) with no lockfile of its own at that level,
  // which was causing Next.js to mis-infer the workspace root as the
  // parent repo dir instead of this frontend/ folder, breaking module
  // resolution (e.g. "Can't resolve 'tailwindcss' in .../qpg").
  outputFileTracingRoot: import.meta.dirname,
  turbopack: {
    root: import.meta.dirname,
  },
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
