#!/usr/bin/env node
// Usage: node tools/screenshot.js <url> [output-path]
// Takes a screenshot of <url> and saves it to output-path (default: /tmp/screenshot.png)

import puppeteer from "puppeteer";
import path from "path";

const url = process.argv[2];
const outputPath = process.argv[3] || "/tmp/screenshot.png";

if (!url) {
  console.error("Error: URL is required.");
  console.error("Usage: node tools/screenshot.js <url> [output-path]");
  process.exit(1);
}

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--ignore-certificate-errors",
    ],
  });

  try {
    const page = await browser.newPage();

    // Set a reasonable viewport
    await page.setViewport({ width: 1280, height: 900 });

    await page.goto(url, { waitUntil: "networkidle2", timeout: 30000 });

    const resolvedPath = path.resolve(outputPath);
    await page.screenshot({ path: resolvedPath, fullPage: true });

    console.log(resolvedPath);
  } finally {
    await browser.close();
  }
})();
