import puppeteer from "puppeteer";

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  const consoleLogs = [];
  page.on('console', msg => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => consoleLogs.push(`[PAGEERR] ${err.message}`));

  console.log("Navigating to login...");
  await page.goto("https://finpilot-api.vercel.app/auth/login", { waitUntil: "networkidle2", timeout: 30000 });

  await page.type('#email', 'fady.habib.k@gmail.com');
  await page.type('#password', 'Fadyadel11!!');

  console.log("Clicking Sign In...");
  await page.click('button[type="submit"]');
  
  // Wait longer for navigation
  await new Promise(r => setTimeout(r, 10000));

  const currentUrl = page.url();
  console.log("Current URL:", currentUrl);

  const errorText = await page.$eval('[role="alert"]', el => el.textContent).catch(() => null);
  if (errorText) console.log("Page error:", errorText);

  await page.screenshot({ path: "/tmp/after_login2.png" });

  if (currentUrl.includes('/dashboard')) {
    console.log("SUCCESS: Reached dashboard");
    await page.screenshot({ path: "/tmp/dashboard_final.png" });
  } else {
    console.log("URL does not contain /dashboard, checking page content...");
    const title = await page.title();
    const h1 = await page.$eval('h1', el => el.textContent).catch(() => 'no h1');
    console.log("Page title:", title);
    console.log("H1:", h1);
  }

  if (consoleLogs.filter(l => !l.includes('favicon')).length) {
    console.log("\nConsole:", consoleLogs.filter(l => !l.includes('favicon')).join('\n'));
  }

  await browser.close();
})();
