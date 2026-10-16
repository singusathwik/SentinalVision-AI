import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './e2e', timeout: 60000, use: { baseURL: 'http://127.0.0.1:3000', channel: process.env.CI ? undefined : 'msedge', viewport: { width: 1440, height: 1000 } }, workers: 1 });
