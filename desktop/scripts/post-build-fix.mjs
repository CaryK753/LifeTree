// macOS post-build fixup for the LifeTree .app bundle.
//
// Fixes two issues that occur after `tauri build`:
//  1. The sidecar binary gets `com.apple.provenance` xattr (macOS Sequoia+),
//     which causes SIGKILL when the parent app tries to spawn it.
//  2. The .app bundle may be missing Resources/ or have an incomplete Info.plist.
//
// This script:
//  - Ensures Resources/ exists with icon.icns
//  - Ensures Info.plist has CFBundleIconFile
//  - Clears all quarantine/provenance xattrs from every file in the bundle
//  - Re-signs the sidecar and the entire app bundle (deep, adhoc)
//
// Usage:  node scripts/post-build-fix.mjs
// (called automatically by `npm run build` via the afterBuildCommand hook)

import { existsSync, mkdirSync, copyFileSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const desktop = resolve(here, "..");
const iconsDir = resolve(desktop, "src-tauri/icons");

// 解析命令行参数 --target <triple>
const args = process.argv.slice(2);
let targetTriple = "";
const targetIdx = args.indexOf("--target");
if (targetIdx !== -1 && args[targetIdx + 1]) {
  targetTriple = args[targetIdx + 1];
}

// Locate the built .app bundle.
// `tauri build --target <triple>` 放在 target/<triple>/release/bundle/
// 不带 --target 时放在 target/release/bundle/
function findAppBundle() {
  const candidates = [];
  if (targetTriple) {
    candidates.push(resolve(desktop, `src-tauri/target/${targetTriple}/release/bundle/macos/LifeTree.app`));
  }
  candidates.push(resolve(desktop, "src-tauri/target/release/bundle/macos/LifeTree.app"));
  // 自动扫描 target/*/release/bundle/macos/
  const targetDir = resolve(desktop, "src-tauri/target");
  if (existsSync(targetDir)) {
    for (const entry of readdirSync(targetDir, { withFileTypes: true })) {
      if (entry.isDirectory() && entry.name.includes("-")) {
        candidates.push(resolve(targetDir, entry.name, "release/bundle/macos/LifeTree.app"));
      }
    }
  }
  return candidates.find(existsSync) || candidates[0];
}

const appBundle = findAppBundle();

// Only relevant on macOS
if (process.platform !== "darwin") {
  console.log("post-build-fix: not macOS, skipping.");
  process.exit(0);
}

if (!existsSync(appBundle)) {
  console.error(`post-build-fix: .app bundle not found at ${appBundle}`);
  console.error("Run `npm run build` first.");
  process.exit(1);
}

const contentsDir = resolve(appBundle, "Contents");
const resourcesDir = resolve(contentsDir, "Resources");
const infoPlistPath = resolve(contentsDir, "Info.plist");
const sidecarPath = resolve(contentsDir, "MacOS/lifetree-sidecar");

// ── 1. Ensure Resources/ has the icon ──────────────────────────
console.log("post-build-fix: ensuring Resources/ has icon files...");
mkdirSync(resourcesDir, { recursive: true });

const iconFiles = [
  ["icon.icns", "icon.icns"],
  ["128x128.png", "128x128.png"],
  ["128x128@2x.png", "128x128@2x.png"],
  ["32x32.png", "32x32.png"],
];

for (const [src, dest] of iconFiles) {
  const srcPath = resolve(iconsDir, src);
  const destPath = resolve(resourcesDir, dest);
  if (existsSync(srcPath)) {
    copyFileSync(srcPath, destPath);
    console.log(`  copied ${src} → Resources/${dest}`);
  }
}

// ── 2. Ensure Info.plist has CFBundleIconFile ──────────────────
console.log("post-build-fix: checking Info.plist for CFBundleIconFile...");
let plist = readFileSync(infoPlistPath, "utf-8");
if (!plist.includes("CFBundleIconFile")) {
  // Insert CFBundleIconFile before CSResourcesFileMapped
  plist = plist.replace(
    /(<key>CSResourcesFileMapped<\/key>)/,
    "<key>CFBundleIconFile</key>\n\t<string>icon.icns</string>\n\t$1",
  );
  writeFileSync(infoPlistPath, plist);
  console.log("  added CFBundleIconFile → icon.icns");
} else {
  console.log("  CFBundleIconFile already present");
}

// ── 3. Clear all xattrs from every file in the bundle ──────────
console.log("post-build-fix: clearing xattrs from all bundle files...");
const xattrResult = spawnSync("find", [appBundle, "-exec", "xattr", "-c", "{}", ";"], {
  stdio: "pipe",
});
if (xattrResult.status !== 0) {
  console.warn("  warning: some xattrs could not be cleared");
}

// ── 4. Re-sign sidecar first, then the entire bundle (deep) ────
console.log("post-build-fix: re-signing sidecar binary...");
if (existsSync(sidecarPath)) {
  const signSidecar = spawnSync(
    "codesign",
    ["--force", "--sign", "-", sidecarPath],
    { stdio: "pipe" },
  );
  if (signSidecar.status !== 0) {
    console.error("  failed to sign sidecar:", signSidecar.stderr?.toString());
    process.exit(1);
  }
  console.log("  sidecar signed (adhoc)");
}

console.log("post-build-fix: re-signing entire .app bundle (deep, adhoc)...");
const signApp = spawnSync(
  "codesign",
  ["--force", "--deep", "--sign", "-", appBundle],
  { stdio: "pipe" },
);
if (signApp.status !== 0) {
  console.error("  failed to sign bundle:", signApp.stderr?.toString());
  process.exit(1);
}

// ── 5. Verify ──────────────────────────────────────────────────
console.log("post-build-fix: verifying signature...");
const verify = spawnSync("codesign", ["--verify", "--verbose", appBundle], {
  stdio: "pipe",
});
if (verify.status !== 0) {
  console.error("  verification failed:", verify.stderr?.toString());
  process.exit(1);
}
console.log(verify.stderr?.toString().trim());
console.log("post-build-fix: done ✓");
