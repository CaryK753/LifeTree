"use client";

import { useEffect, useRef } from "react";

/**
 * ASCII 动态生长树背景。
 *
 * 在 Canvas 上以等宽字符画出一棵不断生长、分叉的树，营造"人生树"
 * 的视觉隐喻。生长完成后会暂停一段时间，然后重置重新生长。
 *
 * 性能：requestAnimationFrame + 帧节流（约 12fps），单个 Canvas 元素，
 * 在低性能设备上也保持流畅。
 */
export function AsciiTreeBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // 字符集：从细到粗表示枝条的生长程度
    const CHARS = [" ", ".", ",", "'", ":", ";", "+", "*", "=", "o", "O", "#", "%", "&", "@"];

    let W = 0;
    let H = 0;
    let cols = 0;
    let rows = 0;
    const CELL = 9; // 字符格大小（px）
    let grid: string[] = [];
    let tree: Branch[] = [];
    let rafId = 0;
    let lastTick = 0;
    const TICK_MS = 80; // 约 12fps，足够流畅又不烧 CPU

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
    }

    interface Branch {
      x: number;
      y: number;
      angle: number; // 弧度，-π/2 = 正上方
      length: number;
      depth: number;
      growing: boolean;
      growChars: number; // 已画多少格
      maxChars: number;
    }

    function plant() {
      grid.fill(" ");
      const rootX = Math.floor(cols / 2) + (Math.random() * 4 - 2) | 0;
      const rootY = rows - 1;
      tree = [{
        x: rootX,
        y: rootY,
        angle: -Math.PI / 2 + (Math.random() * 0.2 - 0.1),
        length: 0,
        depth: 0,
        growing: true,
        growChars: 0,
        maxChars: 8 + Math.floor(Math.random() * 6),
      }];
    }

    function setCell(x: number, y: number, depth: number) {
      if (x < 0 || x >= cols || y < 0 || y >= rows) return;
      // 根据深度选字符：树干粗（@），枝梢细（.）
      const idx = Math.min(CHARS.length - 1, Math.max(1, CHARS.length - 1 - depth));
      grid[y * cols + x] = CHARS[idx];
    }

    function grow() {
      const next: Branch[] = [];
      for (const b of tree) {
        if (!b.growing) {
          next.push(b);
          continue;
        }
        if (b.growChars < b.maxChars) {
          // 沿角度前进一格
          const stepX = Math.cos(b.angle);
          const stepY = Math.sin(b.angle);
          b.x += stepX;
          b.y += stepY;
          setCell(Math.round(b.x), Math.round(b.y), b.depth);
          b.growChars++;
          next.push(b);
        } else {
          // 停止生长，决定是否分叉
          b.growing = false;
          next.push(b);
          if (b.depth < 5) {
            const branchCount = 2 + (Math.random() < 0.3 ? 1 : 0);
            for (let i = 0; i < branchCount; i++) {
              const spread = 0.4 + Math.random() * 0.5;
              const newAngle = b.angle + (i - (branchCount - 1) / 2) * spread + (Math.random() * 0.2 - 0.1);
              const len = Math.max(3, b.maxChars - 1 - Math.floor(Math.random() * 2));
              next.push({
                x: b.x,
                y: b.y,
                angle: newAngle,
                length: 0,
                depth: b.depth + 1,
                growing: true,
                growChars: 0,
                maxChars: len,
              });
            }
          }
        }
      }
      tree = next;
    }

    function hasLiving() {
      return tree.some((b) => b.growing);
    }

    function render() {
      ctx!.clearRect(0, 0, W, H);
      ctx!.font = `${CELL}px ui-monospace, "SF Mono", Menlo, monospace`;
      ctx!.textBaseline = "top";
      // 颜色：根据主题选择
      const isDark = document.documentElement.classList.contains("dark");
      ctx!.fillStyle = isDark ? "rgba(110, 180, 130, 0.22)" : "rgba(60, 120, 70, 0.28)";
      for (let r = 0; r < rows; r++) {
        const line = grid.slice(r * cols, (r + 1) * cols).join("");
        if (line.trim()) {
          ctx!.fillText(line, 0, r * CELL);
        }
      }
    }

    let cycles = 0;
    let pauseUntil = 0;
    // 检测 prefers-reduced-motion：只画一棵静态树，不生长
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    function tick(now: number) {
      rafId = requestAnimationFrame(tick);
      if (reduceMotion) {
        render();
        return;
      }
      if (now - lastTick < TICK_MS) return;
      lastTick = now;

      if (pauseUntil > 0 && now < pauseUntil) {
        render();
        return;
      }
      pauseUntil = 0;

      if (hasLiving()) {
        grow();
      } else {
        cycles++;
        if (cycles >= 1) {
          // 一棵树长完，暂停 4 秒再重新开始
          cycles = 0;
          pauseUntil = now + 4000;
        }
      }
      render();
    }

    function start() {
      resize();
      plant();
      // prefers-reduced-motion: 一次性长完整棵树，之后只静态渲染
      if (reduceMotion) {
        let safety = 2000;
        while (hasLiving() && safety-- > 0) grow();
      }
      cancelAnimationFrame(rafId);
      lastTick = 0;
      pauseUntil = 0;
      cycles = 0;
      rafId = requestAnimationFrame(tick);
    }

    function onResize() {
      // 重新种植以适配新尺寸
      start();
    }

    start();
    window.addEventListener("resize", onResize);
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", onResize);
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
