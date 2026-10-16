// Read-only browser audit of the running local workspace. No records are created.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '../../..');
const pages = ['Overview', 'Live monitoring', 'Video analysis', 'Safety events', 'Zone editor', 'Analytics', 'Model laboratory', 'System health', 'Settings'];
(async () => {
  const output = path.join(root, 'data/layout-audit', process.argv[2] || 'current');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const login = JSON.parse(fs.readFileSync(path.join(root, 'data/local-login.json'), 'utf8'));
  await page.goto('http://127.0.0.1:3000');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.screenshot({ path: path.join(output, `${width}-login.png`), fullPage: true, caret: 'initial' });
  }
  await page.getByLabel('Email address').fill(login.email);
  await page.getByLabel('Password', { exact: true }).fill(login.password);
  await page.getByRole('button', { name: 'Sign in to workspace' }).click();
  await page.getByText('API connected', { exact: true }).waitFor();
  const results = [];
  for (const width of [1440, 390, 320, 768]) {
    await page.setViewportSize({ width, height: 900 });
    for (const name of pages) {
      await page.getByRole('navigation').getByRole('button', { name, exact: true }).click();
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(() => ({
        width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        elements: [...document.querySelectorAll('main input, main select, main button, main section')]
          .filter(el => { const r = el.getBoundingClientRect(); const area = el.closest('.record-list'); const a = area?.getBoundingClientRect(); if (a && (r.bottom < a.top || r.top > a.bottom)) return false; return r.width && (r.right > innerWidth + 1 || r.left < -1); })
          .map(el => `${el.tagName}: ${(el.textContent || el.getAttribute('aria-label') || '').slice(0, 65)}`),
      }));
      results.push({ name, ...overflow });
      if (width === 1440 || width === 390) await page.screenshot({ path: path.join(output, `${width}-${name.replaceAll(' ', '-')}.png`), fullPage: true, caret: 'initial' });
    }
  }
  // Exercise local UI state without creating or changing saved records.
  await page.getByRole('navigation').getByRole('button', { name: 'Video analysis', exact: true }).click();
  const option = page.locator('.rule-option').first();
  if (await option.count()) {
    await option.getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Clear selection', exact: true }).click();
    if (await option.getByRole('checkbox').isChecked()) throw new Error('Clear selection failed');
  }
  await page.getByRole('navigation').getByRole('button', { name: 'Zone editor', exact: true }).click();
  await page.getByRole('button', { name: 'Use inset rectangle' }).click();
  if (await page.getByRole('button', { name: 'Save zone + intrusion rule' }).isDisabled()) throw new Error('Polygon controls failed');
  await page.getByRole('navigation').getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Toggle color theme' }).click();
  await page.screenshot({ path: path.join(output, 'dark-settings.png'), fullPage: true, caret: 'initial' });
  await page.setViewportSize({ width: 390, height: 900 });
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByRole('button', { name: 'Sign in to workspace' }).waitFor();
  await browser.close();
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ results, errors }, null, 2));
  if (errors.length || results.some(r => r.scrollWidth > r.width || r.elements.length)) process.exitCode = 1;
  console.log(JSON.stringify({ checked: results.length, overflow: results.filter(r => r.scrollWidth > r.width || r.elements.length), errors, output }, null, 2));
})().catch(error => { console.error(error); process.exit(1); });
