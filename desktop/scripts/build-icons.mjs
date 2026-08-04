// 生成符合 macOS Big Sur+ 规范的桌面端图标。
//
// 输入：desktop/src-tauri/icons/sources/lifetree-iOS-*-1024@1x.png
//   - Default: 浅色模式
//   - Dark: 深色模式
//   - ClearDark: 透明深色变体
//
// 输出：desktop/src-tauri/icons/ 下全套图标
//
// macOS 规范要点：
//  - 画布 1024×1024，squircle 内容约 824×824（80.5%），四周留 ~100px padding
//  - iOS 图标是 full-bleed squircle（占满 1024×1024），直接用作 macOS 图标会偏大
//  - 解决方案：缩放到 82% 居中放在透明画布上
//
// Windows 规范：
//  - 图标填满画布，不需要 padding
//  - 直接使用原始 1024×1024 尺寸
//
// 托盘图标：
//  - 生成 64×64 小尺寸图标（保留 squircle 形状）
//  - Default/Dark/ClearDark 三个变体，供运行时根据系统主题切换
//
// 运行：node scripts/build-icons.mjs

import { writeFileSync, mkdirSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const desktop = resolve(here, "..");
const iconsDir = resolve(desktop, "src-tauri/icons");
const sourcesDir = resolve(iconsDir, "sources");

const pythonScript = `
import os
from PIL import Image

OUT_DIR = ${JSON.stringify(iconsDir)}
SRC_DIR = ${JSON.stringify(sourcesDir)}
os.makedirs(OUT_DIR, exist_ok=True)

SIZE = 1024
# macOS squircle 占画布约 80.5%（824/1024），四周留 ~100px padding
MACOS_SCALE = 0.805

def load_source(name):
    path = os.path.join(SRC_DIR, name)
    return Image.open(path).convert("RGBA")

def add_macos_padding(img):
    """缩放到 82% 并居中放在透明 1024×1024 画布上（macOS 规范）。"""
    inner_size = int(SIZE * MACOS_SCALE)  # ~824
    small = img.resize((inner_size, inner_size), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    offset = ((SIZE - inner_size) // 2, (SIZE - inner_size) // 2)
    canvas.paste(small, offset, small)
    return canvas

def save_resized(img, size, name):
    out = os.path.join(OUT_DIR, name)
    if img.size != (size, size):
        img.resize((size, size), Image.LANCZOS).save(out, "PNG")
    else:
        img.save(out, "PNG")
    print(f"  saved {name} ({size}x{size})")

# ============================================================
# 1. macOS 应用图标（Default 变体，82% 缩放 + padding）
# ============================================================
print("=== macOS app icon (Default, 82% scale) ===")
default_src = load_source("lifetree-iOS-Default-1024@1x.png")
macos_icon = add_macos_padding(default_src)

save_resized(macos_icon, 1024, "icon-1024.png")
save_resized(macos_icon, 512, "icon.png")
save_resized(macos_icon, 512, "icon_512x512.png")
save_resized(macos_icon, 256, "128x128@2x.png")
save_resized(macos_icon, 256, "icon_256x256.png")
save_resized(macos_icon, 128, "128x128.png")
save_resized(macos_icon, 128, "icon_128x128.png")
save_resized(macos_icon, 64, "64x64.png")
save_resized(macos_icon, 32, "32x32.png")
save_resized(macos_icon, 32, "icon_32x32.png")
save_resized(macos_icon, 16, "icon_16x16.png")

# ============================================================
# 2. Windows 应用图标（100% 不缩放）
# ============================================================
print("\\n=== Windows app icon (100%, no padding) ===")
windows_icon = default_src  # 原始 full-bleed squircle

# Windows Store / MSIX Square 图标
win_sizes = [
    (30, "Square30x30Logo.png"),
    (44, "Square44x44Logo.png"),
    (50, "StoreLogo.png"),
    (71, "Square71x71Logo.png"),
    (89, "Square89x89Logo.png"),
    (107, "Square107x107Logo.png"),
    (142, "Square142x142Logo.png"),
    (150, "Square150x150Logo.png"),
    (284, "Square284x284Logo.png"),
    (310, "Square310x310Logo.png"),
]
for px, name in win_sizes:
    save_resized(windows_icon, px, name)

# Windows .ico
ico_path = os.path.join(OUT_DIR, "icon.ico")
ico_sizes = [(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)]
windows_icon.save(ico_path, format="ICO", sizes=ico_sizes)
print(f"  saved icon.ico")

# ============================================================
# 3. 托盘图标（64×64，三个主题变体，保留 squircle 形状）
# ============================================================
print("\\n=== Tray icons (4 variants, 64x64) ===")
tray_variants = [
    ("lifetree-iOS-Default-1024@1x.png", "tray-light-64.png"),
    ("lifetree-iOS-Dark-1024@1x.png", "tray-dark-64.png"),
    ("lifetree-iOS-ClearDark-1024@1x.png", "tray-cleardark-64.png"),
]
for src_name, out_name in tray_variants:
    img = load_source(src_name)
    save_resized(img, 64, out_name)

# macOS 菜单栏专用白色图标：使用 ClearDark 的 alpha 通道作为形状蒙版，
# 所有不透明像素填充为纯白（255,255,255），在深色菜单栏上清晰可见。
print("  generating tray-white-64.png (macOS menu bar)")
cleardark = load_source("lifetree-iOS-ClearDark-1024@1x.png")
white_img = Image.new("RGBA", cleardark.size, (255, 255, 255, 0))
white_img.putalpha(cleardark.split()[3])
save_resized(white_img, 64, "tray-white-64.png")
`;

mkdirSync(iconsDir, { recursive: true });
const tmpPy = resolve(desktop, "scripts/_gen-icons.py");
writeFileSync(tmpPy, pythonScript);

console.log("Step 1: Generate icons via Python/PIL...");
const pyResult = spawnSync("python3", [tmpPy], { stdio: "inherit" });
rmSync(tmpPy, { force: true });
if (pyResult.error) throw pyResult.error;
if (pyResult.status !== 0) process.exit(pyResult.status ?? 1);

// ============================================================
// 4. 生成 .icns（macOS 专用，使用 82% 缩放版本）
// ============================================================
console.log("\nStep 2: Generate .icns via iconutil...");
const iconsetDir = resolve(iconsDir, "icon.iconset");
rmSync(iconsetDir, { recursive: true, force: true });
mkdirSync(iconsetDir, { recursive: true });

const src1024 = resolve(iconsDir, "icon-1024.png");

const iconsetSizes = [
  [16, "icon_16x16.png"],
  [32, "icon_16x16@2x.png"],
  [32, "icon_32x32.png"],
  [64, "icon_32x32@2x.png"],
  [128, "icon_128x128.png"],
  [256, "icon_128x128@2x.png"],
  [256, "icon_256x256.png"],
  [512, "icon_256x256@2x.png"],
  [512, "icon_512x512.png"],
  [1024, "icon_512x512@2x.png"],
];

for (const [px, name] of iconsetSizes) {
  const out = resolve(iconsetDir, name);
  const r = spawnSync("sips", ["-z", String(px), String(px), src1024, "--out", out], {
    stdio: "pipe",
  });
  if (r.status !== 0) {
    console.error(`sips failed for ${name}:`, r.stderr?.toString());
    process.exit(1);
  }
}

const icnsOut = resolve(iconsDir, "icon.icns");
rmSync(icnsOut, { force: true });
const icnsResult = spawnSync("iconutil", ["-c", "icns", iconsetDir, "-o", icnsOut], {
  stdio: "pipe",
});
if (icnsResult.status !== 0) {
  console.error("iconutil failed:", icnsResult.stderr?.toString());
  process.exit(1);
}
rmSync(iconsetDir, { recursive: true, force: true });
rmSync(src1024, { force: true });
console.log(`  saved icon.icns`);

console.log("\nAll icons generated successfully.");
console.log("  - macOS app icon: Default @ 82% scale (correct Dock size)");
console.log("  - Windows app icon: Default @ 100% (fills canvas)");
console.log("  - Tray icons: 3 variants (light/dark/cleardark) @ 64x64");
