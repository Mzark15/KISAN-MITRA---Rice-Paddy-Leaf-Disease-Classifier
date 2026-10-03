// Runs the Android Gradle wrapper on any OS: `node scripts/gradle.mjs assembleDebug`.
// Gradle 8.14 can't run on very new JDKs (e.g. 25), so prefer Android Studio's bundled JDK 21
// when it's installed. Set KM_KEEP_JAVA_HOME=1 to use your own JAVA_HOME instead.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const isWindows = process.platform === "win32";
const studioJdk = {
  win32: "C:/Program Files/Android/Android Studio/jbr",
  darwin: "/Applications/Android Studio.app/Contents/jbr/Contents/Home",
  linux: "/opt/android-studio/jbr",
}[process.platform];

const env = { ...process.env };
if (!process.env.KM_KEEP_JAVA_HOME && studioJdk && existsSync(studioJdk)) env.JAVA_HOME = studioJdk;

// Full path: Windows may be set not to run programs from the current directory.
const androidDir = resolve("android");
const wrapper = resolve(androidDir, isWindows ? "gradlew.bat" : "gradlew");
const result = spawnSync(isWindows ? `"${wrapper}"` : wrapper, process.argv.slice(2), {
  cwd: androidDir,
  stdio: "inherit",
  env,
  shell: isWindows,
});
process.exit(result.status ?? 1);
