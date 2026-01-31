#!/usr/bin/env node
// Simple HTTP proxy to expose localhost gateway on all interfaces
// Copy this to gateway-proxy.local.js and customize for your setup
const http = require('http');

const GATEWAY_HOST = process.env.GATEWAY_HOST || '127.0.0.1';
const GATEWAY_PORT = parseInt(process.env.GATEWAY_PORT || '18789', 10);
const PROXY_PORT = parseInt(process.env.PROXY_PORT || '18790', 10);

const server = http.createServer((req, res) => {
  const options = {
    hostname: GATEWAY_HOST,
    port: GATEWAY_PORT,
    path: req.url,
    method: req.method,
    headers: req.headers
  };

  const proxy = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  req.pipe(proxy, { end: true });

  proxy.on('error', (e) => {
    console.error(`Proxy error: ${e.message}`);
    res.writeHead(502);
    res.end('Bad Gateway');
  });
});

server.listen(PROXY_PORT, '0.0.0.0', () => {
  console.log(`Gateway proxy listening on 0.0.0.0:${PROXY_PORT}`);
  console.log(`Forwarding to ${GATEWAY_HOST}:${GATEWAY_PORT}`);
});
