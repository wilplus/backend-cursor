/**
 * Regenerate the dev-bugs home-screen / favicon assets in static/dev_bugs_icons/.
 *
 * Build-time only — nothing at runtime depends on Node. Run it when the brand
 * mark or the "dev" badge changes; otherwise the committed PNGs are the artifact.
 *
 *   node scripts/gen_dev_bugs_icons.mjs
 *
 * Needs: node + playwright (chromium) available, and network access to
 * fonts.gstatic.com for Pacifico (cached to /tmp on first run).
 *
 * The art is the Willab wordmark exactly as services/assignment_email._logo_html
 * renders it — Pacifico, ink #2d3748, orange #f97316 period — plus a small orange
 * "dev" pill so an installed dev icon is never mistaken for the real app's.
 *
 * Sizes exist for concrete consumers; see routes/dev_bugs.py::_ICON_FILES and the
 * <link> tags in static/dev_bugs.html. iOS ignores data: URIs for
 * apple-touch-icon, which is why these are real files served over HTTP.
 */
import { chromium } from 'playwright';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const OUT = join(ROOT, 'static', 'dev_bugs_icons');
const FONT_CACHE = '/tmp/willab-pacifico.ttf';
const FONT_URL = 'https://fonts.gstatic.com/s/pacifico/v23/FwZY7-Qmy14u9lezJ96A.ttf';

const INK = '#2d3748';
const ORANGE = '#f97316';
const GROUND = '#ffffff';

mkdirSync(OUT, { recursive: true });

if (!existsSync(FONT_CACHE)) {
  const res = await fetch(FONT_URL);
  if (!res.ok) throw new Error(`Pacifico download failed: ${res.status}`);
  writeFileSync(FONT_CACHE, Buffer.from(await res.arrayBuffer()));
}
const ttf = readFileSync(FONT_CACHE).toString('base64');

const css = `
  @font-face{font-family:'Pacifico';font-style:normal;font-weight:400;
    src:url(data:font/ttf;base64,${ttf}) format('truetype')}
  *{margin:0;padding:0;box-sizing:border-box}
  html,body{background:transparent}
  /* 512x512 full-bleed — iOS/Android apply their own corner mask */
  .icon{width:512px;height:512px;background:${GROUND};position:relative;
        display:flex;align-items:center;justify-content:center;overflow:hidden}
  .mark{font-family:'Pacifico',cursive;font-size:150px;line-height:1;
        color:${INK};letter-spacing:-.02em;white-space:nowrap}
  .dot{color:${ORANGE}}
  .pill{position:absolute;left:50%;bottom:58px;transform:translateX(-50%);
        background:${ORANGE};color:#fff;border-radius:999px;white-space:nowrap;
        font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
        font-weight:800;font-size:50px;line-height:1;padding:16px 34px 20px}
  .lift{transform:translateY(-38px)}                 /* clear the pill */
  .inner{width:512px;height:512px;display:flex;align-items:center;
         justify-content:center;position:relative}
  .shrink{transform:scale(.7)}                       /* Android maskable safe zone */
  .wordmark{display:inline-block;font-family:'Pacifico',cursive;font-size:48px;
            line-height:1.25;color:${INK};letter-spacing:-.02em;
            white-space:nowrap;padding:0 4px}
`;

const WORDMARK_ART = `<div class="mark lift">Willab<span class="dot">.</span></div>
                      <div class="pill">dev</div>`;

const html = `<!doctype html><meta charset="utf-8"><style>${css}</style><body>
  <div class="icon" id="icon">${WORDMARK_ART}</div>
  <div class="icon" id="maskable"><div class="inner shrink">${WORDMARK_ART}</div></div>
  <!-- the wordmark is illegible at 32px, so the tab icon uses the "W." reduction
       of the same mark, keeping the orange period as the brand cue -->
  <div class="icon" id="favicon">
    <div class="mark" style="font-size:330px;transform:translateY(-8px)">W<span class="dot">.</span></div>
  </div>
  <div class="wordmark" id="wordmark">Willab<span class="dot">.</span></div>
</body>`;

const browser = await chromium.launch();

/** Render `sel` at exactly `size` px so glyphs rasterize crisply (no downscale). */
async function shoot(sel, file, size, { omitBackground = false, scale = null } = {}) {
  const page = await browser.newPage({
    viewport: { width: 512, height: 512 },
    deviceScaleFactor: scale ?? size / 512,
  });
  await page.setContent(html);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(250);
  await page.locator(sel).screenshot({ path: join(OUT, file), omitBackground });
  await page.close();
  console.log('  wrote', file);
}

await shoot('#icon', 'icon-180.png', 180);              // apple-touch-icon (iOS)
await shoot('#icon', 'icon-192.png', 192);              // manifest / Android
await shoot('#icon', 'icon-512.png', 512);              // manifest / Android
await shoot('#maskable', 'icon-maskable-512.png', 512); // manifest purpose=maskable
await shoot('#favicon', 'favicon-32.png', 32);          // browser tab
await shoot('#favicon', 'favicon-180.png', 180);        // hi-dpi tab / bookmark
// transparent wordmark for the page's brand row, 2x for retina
await shoot('#wordmark', 'wordmark.png', 0, { omitBackground: true, scale: 2 });

await browser.close();
console.log('done →', OUT);
