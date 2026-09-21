// Capture only the local synthetic showcase, never a deployed CRM instance.
import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const port = Number(process.env.DEMO_PORT || 4310);
const origin = `http://127.0.0.1:${port}`;
const output = new URL('../docs/images/', import.meta.url).pathname;
await mkdir(output, { recursive: true });
const browser = await chromium.launch(process.env.SHOWCASE_BROWSER_CHANNEL ? { channel: process.env.SHOWCASE_BROWSER_CHANNEL } : {});
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, deviceScaleFactor: 1, locale: 'en-US', timezoneId: 'UTC', serviceWorkers: 'block' });
const errors = [];
const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
// Public map tiles are unnecessary for these captures; prevent external requests.
await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
async function open(path) {
  await page.goto(origin + path);
  await page.getByRole('note').filter({ hasText: 'SYNTHETIC DEMO' }).waitFor();
}
async function capture(name) {
  if (errors.length) throw new Error(errors.join('\n'));
  await page.screenshot({ path: `${output}${name}.png`, animations: 'disabled', fullPage: name === 'relationships' });
  console.log(`Saved ${name}.png`);
}
try {
  await open('/dashboard');
  await page.locator('.analytics-totals').waitFor();
  await page.getByRole('link', { name: 'People 128', exact: true }).waitFor();
  await capture('dashboard');

  await open('/profiles');
  await page.locator('.profile-list-row').first().waitFor();
  for (const label of await page.locator('.profile-list-main strong').allTextContents()) {
    if (!/^Person \d{2}$/.test(label)) throw new Error('Unexpected contact label; refusing to capture.');
  }
  await capture('contacts');

  await open('/relationships');
  await page.locator('[data-graph-controls]:not([hidden])').waitFor();
  await page.getByRole('button', { name: 'Fit all nodes', exact: true }).click();
  await page.locator('[data-graph-status]').filter({ hasText: '72 / 72' }).waitFor();
  await capture('relationships');

  await open('/dashboard#timeline');
  await page.locator('.photo-story').first().waitFor();
  await page.locator('#timeline').evaluate(element => window.scrollTo(0, element.getBoundingClientRect().top + window.scrollY - 130));
  await capture('timeline');
} finally {
  await browser.close();
}
