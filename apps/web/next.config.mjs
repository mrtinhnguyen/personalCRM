const nextConfig = {
  output: "standalone",
  devIndicators: false,
  distDir: process.env.NEXT_PUBLIC_DEMO_MODE === "1" ? ".next-demo" : ".next",
  typedRoutes: false,
  async rewrites() {
    const apiOrigin = process.env.API_INTERNAL_URL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  }
};

export default nextConfig;
