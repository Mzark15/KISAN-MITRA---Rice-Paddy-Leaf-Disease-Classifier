// Renders the source images @capacitor/assets needs (assets/*.png) from the brand logo.
// Run via `npm run assets`, which then generates every Android icon density and splash screen.
import { mkdirSync, readFileSync } from "node:fs";
import sharp from "sharp";

const logo = readFileSync(new URL("../frontend/logo.svg", import.meta.url), "utf-8");
const out = new URL("../assets/", import.meta.url);
mkdirSync(out, { recursive: true });

const gradient = `
  <defs><linearGradient id="g" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#40916c"/><stop offset="1" stop-color="#1b4332"/>
  </linearGradient></defs>`;
// The rice stalks without the rounded square behind them.
const stalks = logo.replace(/<defs>[\s\S]*<\/defs>/, "").replace(/<rect[^>]*\/>/, "").replace(/<\/?svg[^>]*>/g, "");

const svg = (body, size = 64) =>
  Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${size}" height="${size}">${body}</svg>`);

async function png(name, buffer) {
  await sharp(buffer).png().toFile(new URL(name, out).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
  console.log("wrote assets/" + name);
}

// Legacy (pre-Android 8) icon: the full logo.
await png("icon-only.png", svg(logo.replace(/<\/?svg[^>]*>/g, ""), 1024));

// Adaptive icon: Android masks it to a circle/squircle and shows only the middle ~66%,
// so the stalks are scaled into that safe zone.
await png("icon-foreground.png", svg(`<g transform="translate(32 32) scale(0.95) translate(-32 -30)">${stalks}</g>`, 1024));
await png("icon-background.png", svg(`${gradient}<rect width="64" height="64" fill="url(#g)"/>`, 1024));

// Splash: logo centred on brand green (light and dark variants).
for (const [name, bg] of [["splash.png", "#1b4332"], ["splash-dark.png", "#0f2a1f"]]) {
  const mark = await sharp(svg(logo.replace(/<\/?svg[^>]*>/g, ""), 640)).png().toBuffer();
  await png(name, await sharp({ create: { width: 2732, height: 2732, channels: 4, background: bg } })
    .composite([{ input: mark, gravity: "center" }]).png().toBuffer());
}
