/**
 * Regenerate the dev-bugs home-screen / favicon assets in static/dev_bugs_icons/.
 *
 * Build-time only — nothing at runtime depends on Node. Run it when the mark or
 * the "dev" label changes; otherwise the committed PNGs are the artifact.
 *
 *   node scripts/gen_dev_bugs_icons.mjs
 *
 * Needs: node + playwright (chromium). No network access and no webfont — the
 * mark is three vector circles and the label uses the system sans stack.
 *
 * The mark is the Willab three-dot logo (small · large · small), rebuilt as
 * vector circles rather than traced from the raster so it stays crisp at 32px
 * and 512px alike, plus a small "dev" label so an installed dev icon is never
 * mistaken for the real app's. Icon-only by design — the page itself carries no
 * logo (founder call, 2026-07-26).
 *
 * Sizes exist for concrete consumers; see routes/dev_bugs.py::_ICON_FILES and the
 * <link> tags in static/dev_bugs.html. iOS ignores data: URIs for
 * apple-touch-icon, which is why these are real files served over HTTP.
 */
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const OUT = join(ROOT, 'static', 'dev_bugs_icons');
mkdirSync(OUT, { recursive: true });

// Mark geometry on the 512 canvas. Ratios taken from the supplied logo:
// large/small diameter ~= 1.46, edge gap ~= 0.69 x small. The row spans ~72% of
// the canvas, which keeps the outer dots clear of the iOS corner mask.
const S = 76;                          // small dot diameter
const B = Math.round(S * 1.46);        // large (centre) dot
const G = Math.round(S * 0.69);        // gap between dot edges
const INK = '#000000';
const GROUND = '#ffffff';

const dots = (scale = 1) => `
  <div class="dots" style="gap:${Math.round(G * scale)}px">
    <i style="width:${Math.round(S * scale)}px;height:${Math.round(S * scale)}px"></i>
    <i style="width:${Math.round(B * scale)}px;height:${Math.round(B * scale)}px"></i>
    <i style="width:${Math.round(S * scale)}px;height:${Math.round(S * scale)}px"></i>
  </div>`;

const css = `
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{background:transparent}
  /* 512x512 full-bleed — iOS/Android apply their own corner mask */
  .icon{width:512px;height:512px;background:${GROUND};position:relative;display:flex;
        flex-direction:column;align-items:center;justify-content:center;gap:34px;overflow:hidden}
  .dots{display:flex;align-items:center}
  .dots i{border-radius:50%;background:${INK};display:block;flex:none}
  .dev{font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
       font-weight:700;font-size:48px;line-height:1;letter-spacing:.01em;color:${INK}}
  .inner{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:34px}
  .shrink{transform:scale(.7)}          /* Android maskable safe zone */
`;

const html = `<!doctype html><meta charset="utf-8"><style>${css}</style><body>
  <div class="icon" id="icon">${dots()}<div class="dev">dev</div></div>
  <div class="icon" id="maskable">
    <div class="inner shrink">${dots()}<div class="dev">dev</div></div>
  </div>
  <!-- the tab favicon is only 32px, where a "dev" label rasterizes to mush, so it
       carries the bare mark; the tab title already says dev-bugs -->
  <div class="icon" id="favicon">${dots(1.12)}</div>
</body>`;

const browser = await chromium.launch();

/** Render `sel` at exactly `size` px so the art rasterizes crisply (no downscale). */
async function shoot(sel, file, size) {
  const page = await browser.newPage({
    viewport: { width: 512, height: 512 },
    deviceScaleFactor: size / 512,
  });
  await page.setContent(html);
  await page.waitForTimeout(150);
  await page.locator(sel).screenshot({ path: join(OUT, file) });
  await page.close();
  console.log('  wrote', file);
}

await shoot('#icon', 'icon-180.png', 180);              // apple-touch-icon (iOS)
await shoot('#icon', 'icon-192.png', 192);              // manifest / Android
await shoot('#icon', 'icon-512.png', 512);              // manifest / Android
await shoot('#maskable', 'icon-maskable-512.png', 512); // manifest purpose=maskable
await shoot('#favicon', 'favicon-32.png', 32);          // browser tab
await shoot('#favicon', 'favicon-180.png', 180);        // hi-dpi tab / bookmark

await browser.close();
console.log('done →', OUT);
