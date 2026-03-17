import puppeteer from "puppeteer";

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });

  const consoleLogs = [];
  const requests = [];
  
  page.on('console', msg => {
    if (!msg.text().includes('favicon')) consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
  });
  page.on('request', req => {
    const url = req.url();
    if (url.includes('supabase') || url.includes('dashboard') || url.includes('auth')) {
      requests.push(`> ${req.method()} ${url.substring(0, 100)}`);
    }
  });
  page.on('response', async resp => {
    const url = resp.url();
    if (url.includes('supabase') || url.includes('dashboard') || url.includes('auth')) {
      let body = '';
      try { body = (await resp.text()).substring(0, 100); } catch {}
      requests.push(`< ${resp.status()} ${url.substring(0, 100)} | ${body}`);
    }
  });

  await page.goto("https://finpilot-api.vercel.app/auth/login", { waitUntil: "networkidle2", timeout: 30000 });

  await page.type('#email', 'fady.habib.k@gmail.com');
  await page.type('#password', 'Fadyadel11!!');
  
  await page.click('button[type="submit"]');
  await new Promise(r => setTimeout(r, 15000));

  console.log("Final URL:", page.url());
  
  console.log("\nNetwork requests (supabase/auth/dashboard):");
  requests.forEach(r => console.log(r));
  
  if (consoleLogs.length) {
    console.log("\nConsole:", consoleLogs.join('\n'));
  }

  await page.screenshot({ path: "/tmp/login_debug.png" });
  await browser.close();
})();
