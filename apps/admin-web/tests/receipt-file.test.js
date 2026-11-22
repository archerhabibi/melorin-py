import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BLOB_TAB_TTL_MS, openBlobInTab } from '../src/features/payments/receiptFile.ts';

// jsdom has no object URLs; put the originals back after each test so other suites are unaffected
const original = { c: URL.createObjectURL, r: URL.revokeObjectURL };

describe('openBlobInTab', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    URL.createObjectURL = vi.fn(() => 'blob:receipt');
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    URL.createObjectURL = original.c;
    URL.revokeObjectURL = original.r;
  });

  it('opens the blob with noopener and releases the object URL only after the TTL', () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    openBlobInTab(new Blob(['x']));
    expect(open).toHaveBeenCalledWith('blob:receipt', '_blank', 'noopener');
    vi.advanceTimersByTime(BLOB_TAB_TTL_MS - 1);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:receipt');
  });
});
