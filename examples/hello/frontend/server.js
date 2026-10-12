#!/usr/bin/env node
/**
 * Minimal Node server for Silk Unit:
 *   - serves a tiny HTML UI at /
 *   - proxies /api/* → API_UPSTREAM (default http://127.0.0.1:8765)
 */
"use strict";

const http = require("http");
const { URL } = require("url");

const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOSTNAME || "127.0.0.1";
const API_UPSTREAM = (process.env.API_UPSTREAM || "http://127.0.0.1:8765").replace(/\/$/, "");

const PAGE = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>silk-sidecar hello</title>
  <style>
    :root { color-scheme: light dark; font-family: ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
           background: radial-gradient(circle at top, #dceeea, #f6f7f8 55%); }
    main { width: min(32rem, calc(100vw - 2rem)); padding: 1.5rem 1.75rem;
           border: 1px solid color-mix(in oklab, CanvasText 12%, transparent);
           border-radius: 1rem; background: color-mix(in oklab, Canvas 88%, transparent);
           backdrop-filter: blur(8px); }
    h1 { margin: 0 0 0.35rem; font-size: 1.5rem; }
    p { margin: 0 0 1rem; color: color-mix(in oklab, CanvasText 70%, transparent); }
    button { appearance: none; border: 0; border-radius: 0.6rem; padding: 0.65rem 1rem;
             background: #0f6b5c; color: white; font: inherit; cursor: pointer; }
    button:hover { filter: brightness(1.08); }
    pre { margin: 1rem 0 0; padding: 0.85rem 1rem; border-radius: 0.6rem;
          background: color-mix(in oklab, CanvasText 6%, transparent);
          overflow: auto; font-size: 0.9rem; }
  </style>
</head>
<body>
  <main>
    <h1>silk-sidecar hello</h1>
    <p>Node front-end → localhost FastAPI via <code>/api</code>.</p>
    <button id="go" type="button">Call /api/hello</button>
    <pre id="out">Click the button…</pre>
  </main>
  <script>
    const out = document.getElementById("out");
    document.getElementById("go").onclick = async () => {
      out.textContent = "Loading…";
      try {
        const res = await fetch("/api/hello?name=Silk");
        const text = await res.text();
        out.textContent = res.status + "\\n" + text;
      } catch (err) {
        out.textContent = String(err);
      }
    };
  </script>
</body>
</html>
`;

function proxyApi(req, res) {
  const upstream = new URL(req.url, API_UPSTREAM);
  const headers = { ...req.headers, host: upstream.host };
  delete headers["accept-encoding"];

  const proxyReq = http.request(
    {
      protocol: upstream.protocol,
      hostname: upstream.hostname,
      port: upstream.port,
      path: upstream.pathname + upstream.search,
      method: req.method,
      headers,
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
      proxyRes.pipe(res);
    },
  );
  proxyReq.on("error", (err) => {
    res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "upstream_unreachable", detail: String(err) }));
  });
  req.pipe(proxyReq);
}

const server = http.createServer((req, res) => {
  const path = (req.url || "/").split("?")[0];
  if (path === "/api" || path.startsWith("/api/")) {
    proxyApi(req, res);
    return;
  }
  if (path === "/" || path === "/index.html") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(PAGE);
    return;
  }
  res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
  res.end("Not found");
});

server.listen(PORT, HOST, () => {
  console.log(`hello-web listening on http://${HOST}:${PORT}`);
  console.log(`proxy /api → ${API_UPSTREAM}`);
});
