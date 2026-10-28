// Screenshots of the HTML report for the README.
// Usage: node scripts/screenshot.mjs <path to the playwright package> [report/index.html] [docs]
//   SUITE=<suite name>  section to capture (default: the first one)
//   EXPAND=<n>          case row whose details are opened in the second shot (default 0)
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const [pwPath, html = 'report/index.html', outDir = 'docs'] = process.argv.slice(2);
const pw = await import(pathToFileURL(resolve(pwPath, 'index.js')).href);
const { chromium } = pw.default ?? pw;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 2, colorScheme: 'light' });
await page.goto(pathToFileURL(resolve(html)).href);

const sections = page.locator('section.suite');
const section = process.env.SUITE ? sections.filter({ hasText: process.env.SUITE }).first() : sections.first();
const name = process.env.SUITE ? `report-${process.env.SUITE}` : 'report';
await section.evaluate((s) => window.scrollTo(0, s.getBoundingClientRect().top + window.scrollY - 24));
await page.screenshot({ path: resolve(outDir, `${name}.png`) });

// Second shot with one case expanded: checks, tool calls, the judge's reasoning and the answer
const details = section.locator('details').nth(Number(process.env.EXPAND ?? 0));
await details.evaluate((d) => (d.open = true));
await details.evaluate((d) => window.scrollTo(0, d.closest('tr').getBoundingClientRect().top + window.scrollY - 24));
await page.screenshot({ path: resolve(outDir, `${name}-case.png`) });
await browser.close();
console.log(`screenshots written to ${outDir}/${name}*.png`);
