#!/usr/bin/env node
// Usage: node tools/test_login.js
import puppeteer from "puppeteer";

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  const consoleLogs = [];
  const networkErrors = [];

  page.on('console', msg => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => consoleLogs.push(`[PAGEERR] ${err.message}`));
  page.on('response', async resp => {
    if (!resp.ok() && (resp.url().includes('supabase') || resp.url().includes('vercel'))) {
      networkErrors.push(`${resp.status()} ${resp.url()}`);
    }
  });

  console.log("Navigating to login...");
  await page.goto("https://finpilot-api.vercel.app/auth/login", { waitUntil: "networkidle2", timeout: 30000 });

  await page.type('#email', 'fady.habib.k@gmail.com');
  await page.type('#password', 'Fadyadel11!!');
  console.log("Credentials filled");

  // Click and wait
  await page.click('button[type="submit"]');
  await new Promise(r => setTimeout(r, 8000));

  const currentUrl = page.url();
  console.log("Current URL:", currentUrl);

  const errorText = await page.$eval('[role="alert"]', el => el.textContent).catch(() => null);
  if (errorText) console.log("Page error:", errorText);

  if (currentUrl.includes('/dashboard')) {
    console.log("SUCCESS: Reached dashboard");
    await page.screenshot({ path: "/tmp/dashboard_after_login.png" });
  } else {
    console.log("NOT on dashboard");
    await page.screenshot({ path: "/tmp/after_login_attempt.png" });
  }

  if (consoleLogs.length) {
    console.log("\nConsole:", consoleLogs.join('\n'));
  }
  if (networkErrors.length) {
    console.log("\nNetwork errors:", networkErrors.join('\n'));
  }

  await browser.close();
})();
