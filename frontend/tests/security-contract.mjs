import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const root = new URL("../", import.meta.url);
const html = fs.readFileSync(new URL("index.html", root), "utf8");
const app = fs.readFileSync(new URL("app.js", root), "utf8");
const styles = fs.readFileSync(new URL("styles.css", root), "utf8");

test("document carries a restrictive client CSP and browser policies", () => {
  const csp = html.match(/<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"\s*>/)?.[1];
  assert.ok(csp, "CSP metadata is required");
  for (const directive of [
    "default-src 'none'", "base-uri 'none'", "object-src 'none'",
     "frame-src 'none'", "form-action 'self'",
    "script-src 'self'", "script-src-attr 'none'", "style-src 'self'",
    "style-src-attr 'none'", "connect-src 'self'", "upgrade-insecure-requests",
  ]) assert.match(csp, new RegExp(`(?:^|;\\s*)${directive.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}(?:;|$)`));
  assert.match(html, /http-equiv="Referrer-Policy"\s+content="strict-origin-when-cross-origin"/);
  assert.match(html, /http-equiv="Permissions-Policy"/);
});

test("the static client has no inline script/style blocks or HTML event handlers", () => {
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/i);
  assert.doesNotMatch(html, /<style\b/i);
  assert.doesNotMatch(html, /\son[a-z]+\s*=/i);
  assert.doesNotMatch(app, /\.(?:innerHTML|outerHTML)\s*=/);
  assert.doesNotMatch(styles, /@import\s+url\s*\(/i);
});
