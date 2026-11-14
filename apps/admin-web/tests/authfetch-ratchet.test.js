import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

// Typed-client migration ratchet (architecture audit 8.1): new admin code talks to the API through `typedClient`
// (paths and bodies checked against the generated OpenAPI types). `authFetch` call sites may only shrink.
// Lower BUDGET whenever a view is migrated; never raise it.
const BUDGET = 27;

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe('typed client ratchet', () => {
  it('does not add new authFetch call sites', () => {
    const files = walk('src').filter((f) => /\.(ts|tsx)$/.test(f) && !f.endsWith('api.ts'));
    const n = files.reduce((a, f) => a + (readFileSync(f, 'utf8').match(/\bauthFetch\(/g) || []).length, 0);
    expect(n).toBeLessThanOrEqual(BUDGET);
  });
});
