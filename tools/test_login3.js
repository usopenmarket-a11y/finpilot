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

  console.log("Navigating to login...");
  await page.goto("https://finpilot-api.vercel.app/auth/login", { waitUntil: "networkidle2", timeout: 30000 });

  await page.type('#email', 'fady.habib.k@gmail.com');
  await page.type('#password', 'Fadyadel11!!');

  console.log("Clicking Sign In and waiting for navigation...");
  
  // Wait for navigation to dashboard
  const [response] = await Promise.all([
    page.waitForNavigation({ timeout: 30000, waitUntil: 'networkidle0' }),
    page.click('button[type="submit"]'),
  ]);

  const currentUrl = page.url();
  console.log("Current URL after nav:", currentUrl);
  
  // If we're on dashboard, wait for full load
  if (currentUrl.includes('/dashboard')) {
    await new Promise(r => setTimeout(r, 3000));
    console.log("SUCCESS: Reached dashboard");
    await page.screenshot({ path: "/tmp/dashboard_success.png" });
  } else {
    // Maybe we're still being redirected - wait more
    await new Promise(r => setTimeout(r, 5000));
    const finalUrl = page.url();
    console.log("Final URL:", finalUrl);
    await page.screenshot({ path: "/tmp/final_state.png" });
    
    const errorText = await page.$eval('[role="alert"]', el => el.textContent).catch(() => null);
    if (errorText) console.log("Error on page:", errorText);
  }

  if (consoleLogs.filter(l => !l.includes('favicon') && l.includes('[error]')).length) {
    console.log("\nErrors:", consoleLogs.filter(l => l.includes('[error]')).join('\n'));
  }

  await browser.close();
})();
