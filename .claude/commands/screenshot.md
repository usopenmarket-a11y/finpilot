---
description: Take a screenshot of a URL using Puppeteer and view it visually.
---

Take a screenshot of the given URL using Puppeteer.

## Steps

1. Run the screenshot script:
   ```bash
   node tools/screenshot.js $ARGUMENTS
   ```
   If no output path is given, the screenshot is saved to `/tmp/screenshot.png`.

2. Read the output file path printed by the script, then use the Read tool on that path to display the screenshot visually.

## Examples

- `/screenshot https://finpilot.vercel.app` — captures the Vercel deployment
- `/screenshot https://example.com /tmp/example.png` — saves to a custom path

## Notes

- Puppeteer is installed as a devDependency in the root `package.json`.
- The script waits for `networkidle2` before capturing, so dynamic content loads fully.
- Full-page screenshots are taken (not just the viewport).
- Uses `--no-sandbox` flag for compatibility with WSL/Linux environments.
