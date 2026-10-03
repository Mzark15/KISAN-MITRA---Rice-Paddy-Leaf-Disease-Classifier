// Guard for `npm run android:release`: a Play build must talk to the HTTPS backend.
import { existsSync, readFileSync } from "node:fs";

// Release builds read web/.env.production (Vite production mode), so .env.local must not leak in.
const read = f => (existsSync(f) ? readFileSync(f, "utf-8").match(/^VITE_API_BASE_URL=(.*)$/m)?.[1]?.trim() : undefined);
const api = process.env.VITE_API_BASE_URL ?? read("web/.env.production") ?? "";

if (!api.startsWith("https://")) {
  console.error(`Release builds need an https API URL; got "${api}". Set VITE_API_BASE_URL in web/.env.production (e.g. https://api.kisanmitra.in).`);
  process.exit(1);
}
if (existsSync("web/.env.local")) {
  console.warn("Note: web/.env.local is ignored for production builds.");
}
if (!existsSync("android/keystore.properties")) {
  console.error("android/keystore.properties is missing: the release bundle can't be signed.");
  process.exit(1);
}
console.log(`Release backend: ${api}`);
