import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

// Drift guard for the generic `call(path, init)` sites that are not yet typed one-by-one (M-06 remainder):
// every literal `/api/v1/...` path passed to a `call(` must still exist in the OpenAPI snapshot
// (`${...}` segments match any `{param}`), so a renamed/removed endpoint fails here instead of at runtime.
const spec = JSON.parse(readFileSync('../../packages/api-client/openapi.json', 'utf8'));
const templates = Object.keys(spec.paths).map((p) => p.split('/'));
// segment-wise: `{param}` in the spec and `X` (an interpolation, e.g. a verb) in the call both match anything
const matches = (path) => {
  const seg = path.split('/');
  return templates.some(
    (t) => t.length === seg.length && t.every((s, i) => s.startsWith('{') || seg[i] === 'X' || s === seg[i]),
  );
};

const walk = (d) =>
  readdirSync(d).flatMap((n) => {
    const p = join(d, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });

describe('call() literal paths exist in the OpenAPI snapshot', () => {
  it('has no stale endpoint', () => {
    const stale = [];
    const re = /\bcall\(\s*([`'])(\/api\/v1\/[^`'?]*)/g;
    for (const f of walk('src').filter((x) => /\.tsx?$/.test(x))) {
      for (const m of readFileSync(f, 'utf8').matchAll(re)) {
        const path = m[2].replace(/\$\{[^}]*\}/g, 'X');
        if (!matches(path)) stale.push(`${f}: ${m[2]}`);
      }
    }
    expect(stale).toEqual([]);
  });
});
