import path from 'node:path';
import { defineConfig } from 'vitest/config';

const sourceInspectionTests = [
  'src/components/layout/Navbar.test.ts',
  'src/components/link-pack/LinkPackPage.test.ts',
];

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: 'source-inspection',
          environment: 'node',
          include: sourceInspectionTests,
          globals: false,
          restoreMocks: true,
          clearMocks: true,
        },
      },
      {
        extends: true,
        test: {
          name: 'components',
          environment: 'jsdom',
          include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
          exclude: sourceInspectionTests,
          setupFiles: ['./src/test/setup.ts'],
          globals: false,
          restoreMocks: true,
          clearMocks: true,
        },
      },
    ],
  },
});
