import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

// Typing ratchet (T-O03 / T-R11): the loose `Json` / `Rec` aliases may only shrink.
// Lower BUDGET whenever a view gets real types; never raise it.
const BUDGET = 2042;

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe('typing ratchet', () => {
  it('does not add new loose Json/Rec usages', () => {
    const files = walk('src').filter((f) => /\.(ts|tsx)$/.test(f) && !f.endsWith('types.ts'));
    const n = files.reduce((a, f) => a + (readFileSync(f, 'utf8').match(/\b(Json|Rec)\b/g) || []).length, 0);
    expect(n).toBeLessThanOrEqual(BUDGET);
  });
  it('has no @ts-ignore / @ts-nocheck / as any escapes', () => {
    const bad = walk('src')
      .filter((f) => /\.(ts|tsx)$/.test(f))
      .filter((f) =>
        /@ts-(ignore|nocheck)|\bas any\b|: any\b/.test(
          readFileSync(f, 'utf8')
            .replace(/\/\/ eslint-disable-line[^\n]*/g, '')
            .replace(/export type (Rec|Json) = any;/g, ''),
        ),
      );
    expect(bad).toEqual([]);
  });
});
