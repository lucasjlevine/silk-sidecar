// silk-sidecar rewrite helper for $name
// Proxy browser $proxy_prefix/* → $upstream/*
//
// next.config.js / next.config.mjs example:
//
//   async rewrites() {
//     return [
//       {
//         source: '$proxy_prefix/:path*',
//         destination: '$upstream/:path*',
//       },
//     ];
//   },
//
// Or set env at build time:
//   API_UPSTREAM=$upstream
//   NEXT_PUBLIC_API_URL=$proxy_prefix

module.exports = {
  source: '$proxy_prefix/:path*',
  destination: '$upstream/:path*',
};
