"use client";

import { useEffect, useRef } from "react";

/**
 * ASCII 动态树林背景 + 流星划过夜空。
 *
 * 视觉分两层：
 *   1. **树林层**：多株高低、大小、位置都随机的树同时生长。每株树
 *      从地面发芽，分叉递归生长，深度越深枝条越细。整片树林长完
 *      后会保留一段时间供观赏。
 *   2. **流星层**：树林全部长完后，几颗流星从夜空斜划而过，留下一
 *      串渐淡的字符尾迹。流星结束一段时间后整片场景重置重新生长。
 *
 * 主题：
 *   - 深色模式：夜空底色（深蓝黑），树为暗绿/灰绿，流星为亮白/淡蓝
 *   - 浅色模式：白昼底色（米白），树为深绿，流星为深灰/蓝灰
 *   - 通过监听 ``html.dark`` class 的变化动态切换调色板
 *
 * 性能：requestAnimationFrame + 帧节流（约 12fps），单 Canvas。
 */
export function AsciiTreeBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // 字符集：从细到粗表示枝条的生长程度
    const CHARS = [
      " ", ".", ",", "'", ":", ";", "+", "*", "=", "o", "O", "#", "%", "&", "@",
    ];

    // 流星字符集：从尾到头渐亮
    const METEOR_CHARS = [".", "·", ":", "-", "=", "+", "*", "o", "O", "★"];

    type Theme = {
      bg: string; // canvas 背景填充色
      tree: string; // 树枝字符颜色
      meteor: string; // 流星字符颜色
      ground: string; // 地面线颜色
    };

    const THEMES: Record<"dark" | "light", Theme> = {
      dark: {
        bg: "#0b0d12",
        tree: "rgba(120, 190, 140, 0.32)",
        meteor: "rgba(220, 230, 255, 0.85)",
        ground: "rgba(90, 110, 130, 0.25)",
      },
      light: {
        bg: "#f7f6f2",
        tree: "rgba(60, 110, 70, 0.34)",
        meteor: "rgba(60, 80, 130, 0.7)",
        ground: "rgba(120, 110, 90, 0.3)",
      },
    };

    function currentTheme(): Theme {
      const isDark = document.documentElement.classList.contains("dark");
      return isDark ? THEMES.dark : THEMES.light;
    }

    let W = 0;
    let H = 0;
    let cols = 0;
    let rows = 0;
    const CELL = 9; // 字符格大小（px）
    let grid: string[] = [];
    // 颜色标签：每格一个标签，决定渲染时用什么颜色
    let colorTag: Uint8Array = new Uint8Array(0);
    const TAG_TREE = 1;
    const TAG_GROUND = 2;
    const TAG_METEOR = 3;

    interface Branch {
      x: number;
      y: number;
      angle: number; // 弧度，-π/2 = 正上方
      depth: number;
      growing: boolean;
      growChars: number;
      maxChars: number;
    }

    interface Tree {
      branches: Branch[];
      done: boolean;
    }

    let trees: Tree[] = [];
    let meteors: Meteor[] = [];

    interface Meteor {
      x: number;
      y: number;
      vx: number; // 每帧位移（格）
      vy: number;
      life: number; // 剩余帧数
      maxLife: number;
      trail: Array<{ x: number; y: number; age: number }>;
    }

    let rafId = 0;
    let lastTick = 0;
    const TICK_MS = 80; // 约 12fps
    let phase: "growing" | "meteor" | "pause" = "growing";
    let phaseEndAt = 0;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas!.clientWidth;
      H = canvas!.clientHeight;
      canvas!.width = W * dpr;
      canvas!.height = H * dpr;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = Math.floor(W / CELL);
      rows = Math.floor(H / CELL);
      grid = new Array(cols * rows).fill(" ");
      colorTag = new Uint8Array(cols * rows);
    }

    function setCell(x: number, y: number, depth: number, tag: number, ch?: string) {
      const ix = Math.round(x);
      const iy = Math.round(y);
      if (ix < 0 || ix >= cols || iy < 0 || iy >= rows) return;
      const idx = iy * cols + ix;
      // 树枝允许覆盖地面，流星允许覆盖任何东西
      if (tag === TAG_METEOR) {
        grid[idx] = ch ?? ".";
        colorTag[idx] = tag;
        return;
      }
      // 已有树枝的格子不被地面覆盖
      if (tag === TAG_GROUND && colorTag[idx] === TAG_TREE) return;
      // 树枝覆盖地面 / 空格
      if (tag === TAG_TREE) {
        const chIdx = Math.min(
          CHARS.length - 1,
          Math.max(1, CHARS.length - 1 - depth)
        );
        grid[idx] = CHARS[chIdx];
        colorTag[idx] = tag;
      } else if (tag === TAG_GROUND) {
        grid[idx] = ch ?? "_";
        colorTag[idx] = tag;
      }
    }

    function plantForest() {
      grid.fill(" ");
      colorTag.fill(0);
      trees = [];
      meteors = [];

      // 地面线：随机高度起伏的草地线
      const groundY = rows - 1 - Math.max(1, Math.floor(rows * 0.08));
      for (let x = 0; x < cols; x++) {
        // 起伏：用正弦+随机扰动
        const wave =
          Math.sin(x * 0.18) * 1.2 + (Math.random() * 1.4 - 0.7);
        const gy = Math.round(groundY + wave);
        setCell(x, gy, 0, TAG_GROUND, "·");
        // 地面下面一行偶尔补一个 "."
        if (Math.random() < 0.4) setCell(x, gy + 1, 0, TAG_GROUND, ".");
      }

      // 树林：5 ~ 10 株，随机位置/高度/角度
      const treeCount = 6 + Math.floor(Math.random() * 5);
      const usedX = new Set<number>();
      for (let i = 0; i < treeCount; i++) {
        let rootX: number;
        let tries = 0;
        do {
          rootX = 2 + Math.floor(Math.random() * Math.max(1, cols - 4));
          tries++;
        } while (usedX.has(rootX) && tries < 20);
        // 允许相邻但不重合
        usedX.add(rootX);
        for (let d = -1; d <= 1; d++) usedX.add(rootX + d);

        const rootY = groundY + (Math.random() < 0.3 ? 1 : 0);
        // 树干长度：决定树高
        const trunkLen = 7 + Math.floor(Math.random() * 9);
        // 起始角度：略向左/右倾斜
        const tilt = (Math.random() * 0.2 - 0.1);
        const startAngle = -Math.PI / 2 + tilt;
        // 深度上限：决定分叉几次（影响树的"蓬松度"）
        const depthCap = 4 + Math.floor(Math.random() * 2); // 4 ~ 5

        const tree: Tree = {
          branches: [
            {
              x: rootX,
              y: rootY,
              angle: startAngle,
              depth: 0,
              growing: true,
              growChars: 0,
              maxChars: trunkLen,
            },
          ],
          done: false,
        };
        // 把深度上限挂到 tree 上以便 grow 时读取
        (tree as Tree & { depthCap?: number }).depthCap = depthCap;
        trees.push(tree);
      }
    }

    function growTree(tree: Tree) {
      const depthCap = (tree as Tree & { depthCap?: number }).depthCap ?? 5;
      const next: Branch[] = [];
      for (const b of tree.branches) {
        if (!b.growing) {
          next.push(b);
          continue;
        }
        if (b.growChars < b.maxChars) {
          b.x += Math.cos(b.angle);
          b.y += Math.sin(b.angle);
          setCell(b.x, b.y, b.depth, TAG_TREE);
          b.growChars++;
          next.push(b);
        } else {
          b.growing = false;
          next.push(b);
          if (b.depth < depthCap) {
            const branchCount = 2 + (Math.random() < 0.25 ? 1 : 0);
            for (let i = 0; i < branchCount; i++) {
              const spread = 0.35 + Math.random() * 0.55;
              const newAngle =
                b.angle +
                (i - (branchCount - 1) / 2) * spread +
                (Math.random() * 0.2 - 0.1);
              const len = Math.max(
                3,
                b.maxChars - 1 - Math.floor(Math.random() * 3)
              );
              next.push({
                x: b.x,
                y: b.y,
                angle: newAngle,
                depth: b.depth + 1,
                growing: true,
                growChars: 0,
                maxChars: len,
              });
            }
          }
        }
      }
      tree.branches = next;
      tree.done = !tree.branches.some((b) => b.growing);
    }

    function allTreesDone() {
      return trees.length > 0 && trees.every((t) => t.done);
    }

    function spawnMeteor() {
      // 从屏幕左上或右上角附近出发，斜向下
      const fromLeft = Math.random() < 0.5;
      const startX = fromLeft
        ? -2
        : cols + 2;
      const startY = 1 + Math.floor(Math.random() * Math.max(1, Math.floor(rows * 0.35)));
      const speed = 0.8 + Math.random() * 0.6;
      const angle = fromLeft
        ? Math.PI * 0.18 + Math.random() * 0.1 // 右下方向
        : Math.PI - Math.PI * 0.18 - Math.random() * 0.1; // 左下方向
      const life = 40 + Math.floor(Math.random() * 30);
      meteors.push({
        x: startX,
        y: startY,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life,
        maxLife: life,
        trail: [],
      });
    }

    function updateMeteors() {
      const next: Meteor[] = [];
      for (const m of meteors) {
        // 推进
        m.x += m.vx;
        m.y += m.vy;
        m.life--;
        // 记录尾迹
        m.trail.push({ x: m.x, y: m.y, age: 0 });
        // 老化所有尾迹
        for (const t of m.trail) t.age++;
        // 截断过老的尾迹（长度 ~ 14）
        if (m.trail.length > 16) m.trail.shift();
        // 渲染到 grid
        const trailLen = m.trail.length;
        for (let i = 0; i < trailLen; i++) {
          const t = m.trail[i];
          // 尾部字符淡、头部字符亮
          const ratio = i / Math.max(1, trailLen - 1);
          const chIdx = Math.min(
            METEOR_CHARS.length - 1,
            Math.floor(ratio * METEOR_CHARS.length)
          );
          setCell(t.x, t.y, 0, TAG_METEOR, METEOR_CHARS[chIdx]);
        }
        // 还活着 + 没飞出屏幕 → 保留
        if (m.life > 0 && m.x > -5 && m.x < cols + 5 && m.y < rows + 5) {
          next.push(m);
        }
      }
      meteors = next;
    }

    function render() {
      const theme = currentTheme();
      // 背景
      ctx!.fillStyle = theme.bg;
      ctx!.fillRect(0, 0, W, H);
      ctx!.font = `${CELL}px ui-monospace, "SF Mono", Menlo, monospace`;
      ctx!.textBaseline = "top";

      // 分两遍渲染：先树和地面，再流星（让流星盖在树之上）
      // 收集每行的字符串 + 颜色段
      // 简化做法：逐格渲染（cols*rows 通常 < 10k，可接受）
      // 为减少 fillStyle 切换，按颜色批处理
      type Run = { x: number; y: number; ch: string };
      const treeRuns: Run[] = [];
      const groundRuns: Run[] = [];
      const meteorRuns: Run[] = [];
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const idx = r * cols + c;
          const ch = grid[idx];
          if (ch === " ") continue;
          const tag = colorTag[idx];
          const run: Run = { x: c * CELL, y: r * CELL, ch };
          if (tag === TAG_METEOR) meteorRuns.push(run);
          else if (tag === TAG_GROUND) groundRuns.push(run);
          else treeRuns.push(run);
        }
      }
      ctx!.fillStyle = theme.ground;
      for (const run of groundRuns) ctx!.fillText(run.ch, run.x, run.y);
      ctx!.fillStyle = theme.tree;
      for (const run of treeRuns) ctx!.fillText(run.ch, run.x, run.y);
      ctx!.fillStyle = theme.meteor;
      for (const run of meteorRuns) ctx!.fillText(run.ch, run.x, run.y);
    }

    function tick(now: number) {
      rafId = requestAnimationFrame(tick);
      const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)"
      ).matches;
      if (reduceMotion) {
        render();
        return;
      }
      if (now - lastTick < TICK_MS) return;
      lastTick = now;

      if (phase === "growing") {
        for (const t of trees) growTree(t);
        if (allTreesDone()) {
          // 树林长完 → 进入流星阶段
          phase = "meteor";
          phaseEndAt = now + 8000; // 流星阶段持续 8 秒
          // 立刻放第一颗流星
          spawnMeteor();
        }
      } else if (phase === "meteor") {
        // 间歇性放流星
        if (meteors.length < 2 && Math.random() < 0.08) {
          spawnMeteor();
        }
        updateMeteors();
        if (now > phaseEndAt && meteors.length === 0) {
          phase = "pause";
          phaseEndAt = now + 3000; // 暂停 3 秒后重新生长
        }
      } else if (phase === "pause") {
        if (now > phaseEndAt) {
          phase = "growing";
          plantForest();
        }
      }
      render();
    }

    function start() {
      resize();
      plantForest();
      phase = "growing";
      phaseEndAt = 0;
      cancelAnimationFrame(rafId);
      lastTick = 0;
      rafId = requestAnimationFrame(tick);
    }

    function onResize() {
      start();
    }

    // 监听主题切换：主题变化时立即重渲染（下一帧）
    const themeObserver = new MutationObserver(() => {
      // 不需要重新生长，render() 会自动读取新主题
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });

    // prefers-reduced-motion：一次性长完整片树林，之后只静态渲染
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      resize();
      plantForest();
      let safety = 5000;
      while (trees.some((t) => !t.done) && safety-- > 0) {
        for (const t of trees) growTree(t);
      }
      // 静态渲染循环
      rafId = requestAnimationFrame(function staticTick() {
        render();
        rafId = requestAnimationFrame(staticTick);
      });
    } else {
      start();
    }

    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", onResize);
      themeObserver.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden="true"
    />
  );
}
