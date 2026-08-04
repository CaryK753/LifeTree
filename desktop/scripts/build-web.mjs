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
function run(args, cwd) {
  const result = spawnSync("npm", args, { cwd, stdio: "inherit", shell: true });
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

run(["run", "build:desktop"], frontend);
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
cpSync(exportedFrontend, output, { recursive: true });
externalizeInlineScripts(output);
run(["run", "build:launcher"], desktop);
