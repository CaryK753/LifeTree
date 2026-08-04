import {
  cpSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frontend = resolve(desktop, "../frontend");
const output = resolve(desktop, "dist");
const exportedFrontend = resolve(frontend, ".next-desktop");

// Windows 上 Node.js 的 spawnSync 调用 .cmd/.bat 文件必须启用 shell，
// 否则报 EINVAL（Node 22+ 更严格）。统一用 shell:true 在所有平台上都安全。
// `env` 参数允许为子进程注入环境变量（跨平台替代 Unix 的 VAR=value cmd 语法）。
function run(args, cwd, env) {
  const result = spawnSync("npm", args, {
    cwd,
    stdio: "inherit",
    shell: true,
    env: { ...process.env, ...env },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function htmlFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return htmlFiles(path);
    return entry.isFile() && entry.name.endsWith(".html") ? [path] : [];
  });
}

function externalizeInlineScripts(directory) {
  const scriptsDirectory = resolve(directory, "_desktop-inline");
  mkdirSync(scriptsDirectory, { recursive: true });
  for (const htmlPath of htmlFiles(directory)) {
    const html = readFileSync(htmlPath, "utf8");
    const rewritten = html.replace(
      /<script([^>]*)>([\s\S]*?)<\/script>/g,
      (tag, attributes, source) => {
        if (/\bsrc\s*=/.test(attributes) || !source.trim()) return tag;
        const digest = createHash("sha256").update(source).digest("hex").slice(0, 20);
        writeFileSync(resolve(scriptsDirectory, `${digest}.js`), source);
        return `<script${attributes} src="/_desktop-inline/${digest}.js"></script>`;
      }
    );
    writeFileSync(htmlPath, rewritten);
  }
}

// 通过环境变量注入桌面端构建标志（跨平台，替代 Unix 的 VAR=value cmd 语法）
run(["run", "build:desktop"], frontend, {
  LIFETREE_DESKTOP_EXPORT: "1",
  NEXT_DIST_DIR: ".next-desktop",
});
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
cpSync(exportedFrontend, output, { recursive: true });
externalizeInlineScripts(output);
run(["run", "build:launcher"], desktop);
