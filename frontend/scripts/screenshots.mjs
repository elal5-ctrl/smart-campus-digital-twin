import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const baseUrl = process.env.SCREENSHOT_URL ?? 'http://127.0.0.1:5555';
const outputDir = 'screenshots';

const viewports = {
  desktop: { viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 2 },
  mobile: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true },
};

async function setLanguage(page, lang) {
  await page.getByRole('button', { name: lang, exact: true }).click();
}

async function setDarkMode(page) {
  const themeToggle = page.getByRole('button', { name: /Design|Theme|テーマ/ });
  const isPressed = await themeToggle.getAttribute('aria-pressed');
  if (isPressed !== 'true') {
    await themeToggle.click();
  }
}

async function settle(page) {
  await page.waitForLoadState('networkidle');
  await page.locator('.sensor-card').first().waitFor({ state: 'visible' });
  await page.waitForTimeout(350);
}

async function capturePage(context, filename, options = {}) {
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await settle(page);

  if (options.lang) {
    await setLanguage(page, options.lang);
    await settle(page);
  }

  if (options.dark) {
    await setDarkMode(page);
    await settle(page);
  }

  await page.screenshot({
    path: `${outputDir}/${filename}.png`,
    fullPage: options.fullPage ?? true,
  });

  await page.close();
}

async function captureMapDetail(context) {
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await settle(page);

  const mapShell = page.locator('.map-shell');
  await mapShell.screenshot({
    path: `${outputDir}/map-detail-de.png`,
  });

  await page.close();
}

await mkdir(outputDir, { recursive: true });

const browser = await chromium.launch();
try {
  const desktop = await browser.newContext(viewports.desktop);
  await capturePage(desktop, 'desktop-de', { lang: 'DE' });
  await capturePage(desktop, 'desktop-en', { lang: 'EN' });
  await capturePage(desktop, 'desktop-jp', { lang: 'JP' });
  await capturePage(desktop, 'dark-mode-de', { lang: 'DE', dark: true });
  await captureMapDetail(desktop);
  await desktop.close();

  const mobile = await browser.newContext(viewports.mobile);
  await capturePage(mobile, 'mobile-de', { lang: 'DE' });
  await capturePage(mobile, 'mobile-jp', { lang: 'JP' });
  await mobile.close();
} finally {
  await browser.close();
}

console.log(`Screenshots saved in ${outputDir}/`);
