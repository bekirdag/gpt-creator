import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.{js,ts}'],
    // Use vmThreads to avoid worker crash in restricted sandboxes.
    pool: 'vmThreads',
    minWorkers: 1,
  },
});
