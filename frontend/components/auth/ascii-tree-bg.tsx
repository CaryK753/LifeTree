"use client";

import { useEffect, useRef } from "react";
import {
  BENCH_ART,
  BIRD_ART,
  CLOUD_ART,
  LAMP_ART,
  MOON_ART,
  PERSON_ART,
  SUN_ART,
} from "./ascii-scene-art";

/**
 * ASCII 动态场景背景：银河星空 / 白昼天空 + 树林 + 公园长凳·路灯·人。
 *
 * 视觉分三层：
 *   1. **天空层**：
 *      - 深色模式 = 银河星空：闪烁的星点、圆月、从右往左倾斜划过天空并淡出的流星。
 *      - 浅色模式 = 白昼天空：太阳、随机飞过的鸟。
 *   2. **树林层**：多株高低、粗细、位置都随机的树同时生长。每株树
 *      从地面发芽，分叉递归生长。长成后枝叶随风轻微晃动。
 *   3. **地面层**：草地线 + 泥土 + 公园长凳 + 路灯 + 人（紧密排列）。
 *      - 深色模式：路灯亮起（带光晕），人坐在长凳上仰望星空。
 *      - 浅色模式：路灯熄灭，人坐在长凳上思考。
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

    // ---------- 字符集 ----------
    const CHARS = [
      " ", ".", ",", "'", ":", ";", "+", "*", "=", "o", "O", "#", "%", "&", "@",
    ];
    const LEAF_CHARS = ["*", "+", "o", "·", "✦"];
    // 流星尾迹字符：从尾到头越来越粗
    const METEOR_TAIL = [".", "·", ":", "-", "=", "+", "*"];
    // 流星头部字符：大而明显
    const METEOR_HEAD = "◉";
    const STAR_CHARS = [".", "·", "✦", "⋆", "∙"];
    const SPARK_CHARS = ["✦", "✧", "*", "·", ".", "+", "★"];

    type ThemeName = "dark" | "light";
    interface Theme {
      bg: string;
      tree: string;
      leaf: string;
      ground: string;
      soil: string;
      meteor: string;
      meteorHead: string;
      star: string;
      moon: string;
      sun: string;
      bird: string;
      cloud: string;
      bench: string;
      lamp: string;
      lampGlow: string;
      person: string;
    }

    const THEMES: Record<ThemeName, Theme> = {
      dark: {
        bg: "#0b0d12",
        tree: "rgba(100, 220, 130, 0.55)",
        leaf: "rgba(120, 200, 110, 0.45)",
        ground: "rgba(90, 110, 130, 0.3)",
        soil: "rgba(100, 80, 60, 0.4)",
        meteor: "rgba(220, 230, 255, 0.85)",
        meteorHead: "rgba(255, 255, 255, 1)",
        star: "rgba(220, 230, 255, 0.7)",
        moon: "rgba(240, 245, 220, 0.9)",
        sun: "transparent",
        bird: "transparent",
        cloud: "transparent",
        bench: "rgba(150, 130, 100, 0.55)",
        lamp: "rgba(255, 220, 140, 0.85)",
        lampGlow: "rgba(255, 200, 120, 0.18)",
        person: "rgba(180, 190, 210, 0.7)",
      },
      light: {
        bg: "#f7f6f2",
        tree: "rgba(60, 110, 70, 0.34)",
        leaf: "rgba(70, 130, 80, 0.4)",
        ground: "rgba(120, 110, 90, 0.35)",
        soil: "rgba(140, 110, 80, 0.4)",
        meteor: "transparent",
        meteorHead: "transparent",
        star: "transparent",
        moon: "transparent",
        sun: "rgba(245, 180, 80, 0.85)",
        bird: "rgba(80, 80, 80, 0.55)",
        cloud: "rgba(100, 125, 145, 0.28)",
        bench: "rgba(120, 90, 60, 0.5)",
        lamp: "rgba(120, 110, 90, 0.4)",
        lampGlow: "transparent",
        person: "rgba(80, 80, 80, 0.6)",
      },
    };

    function currentTheme(): Theme {
      const isDark = document.documentElement.classList.contains("dark");
      return isDark ? THEMES.dark : THEMES.light;
    }
    function currentThemeName(): ThemeName {
      return document.documentElement.classList.contains("dark") ? "dark" : "light";
    }

    // ---------- 网格 ----------
    let W = 0;
    let H = 0;
    let cols = 0;
    let rows = 0;
    const CELL = 9;
    let grid: string[] = [];
    let colorTag: Uint8Array = new Uint8Array(0);

    const TAG_TREE = 1;
    const TAG_LEAF = 2;
    const TAG_GROUND = 3;
    const TAG_SOIL = 4;
    const TAG_METEOR = 5;
    const TAG_METEOR_HEAD = 6;
    const TAG_SPARK = 7;
    const TAG_STAR = 8;
    const TAG_MOON = 9;
    const TAG_SUN = 10;
    const TAG_BENCH = 11;
    const TAG_LAMP = 12;
    const TAG_LAMP_GLOW = 13;
    const TAG_PERSON = 14;
    const TAG_BIRD = 15;
    const TAG_CLOUD = 16;

    // ---------- 数据结构 ----------
    interface Branch {
      x: number;
      y: number;
      angle: number;
      depth: number;
      growing: boolean;
      growChars: number;
      maxChars: number;
    }

    interface TreeCell {
      x: number;
      y: number;
      ch: string;
      tag: number;
      heightFromGround: number;
      treeIndex: number;
    }

    interface Tree {
      rootX: number;
      trunkThickness: 1 | 2 | 3;
      swayPhase: number;
      swayFreq: number;
      branches: Branch[];
      done: boolean;
      depthCap: number;
      cells: TreeCell[];
      topY: number; // 树顶 y 坐标，流星必须高于此值
    }

    interface Meteor {
      x: number;
      y: number;
      vx: number;
      vy: number;
      trail: Array<{ x: number; y: number }>;
      life: number;
      maxLife: number;
    }

    interface Star {
      x: number;
      y: number;
      brightness: number;
      twinklePhase: number;
      twinkleFreq: number;
    }

    interface Bird {
      x: number;
      y: number;
      vx: number;
      wingPhase: number;
    }

    interface Cloud {
      x: number;
      y: number;
      vx: number;
      artIndex: number;
    }

    interface Spark {
      x: number;
      y: number;
      vx: number;
      vy: number;
      life: number;
      ch: string;
    }

    // 萤火虫（夜晚在路灯周围飞舞）
    interface Firefly {
      x: number;
      y: number;
      vx: number;
      vy: number;
      life: number;
      flickerPhase: number;
      baseX: number;
      baseY: number;
    }

    let trees: Tree[] = [];
    let treeCells: TreeCell[] = [];
    let meteors: Meteor[] = [];
    let stars: Star[] = [];
    let birds: Bird[] = [];
    let clouds: Cloud[] = [];
    let sparks: Spark[] = [];
    let fireflies: Firefly[] = [];

    let groundLineY = 0;
    let treeMaxTopY = 0; // 所有树中最高的 y 值，流星必须高于此

    let rafId = 0;
    let lastTick = 0;
    const TICK_MS = 80;
    let phase: "growing" | "alive" = "growing";
    let nextMeteorAt = 0;
    let nextBirdAt = 0;
    let nextFireflyAt = 0;
    let tickCount = 0;
    // 底部场景（路灯/长凳/人）生长进度 0..1，alive 阶段从 0 增长到 1
    let bottomSceneProgress = 0;
    // 路灯灯笼中心坐标，供萤火虫生成使用
    let lampCenterX = 0;
    let lampCenterY = 0;

    // ---------- 尺寸 ----------
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

    function setCell(x: number, y: number, tag: number, ch: string) {
      const ix = Math.round(x);
      const iy = Math.round(y);
      if (ix < 0 || ix >= cols || iy < 0 || iy >= rows) return;
      const idx = iy * cols + ix;
      // 动态元素可以覆盖任何东西
      if (
        tag === TAG_METEOR ||
        tag === TAG_METEOR_HEAD ||
        tag === TAG_SPARK ||
        tag === TAG_BIRD ||
        tag === TAG_CLOUD ||
        tag === TAG_STAR ||
        tag === TAG_LAMP_GLOW
      ) {
        grid[idx] = ch;
        colorTag[idx] = tag;
        return;
      }
      // 已有树枝/叶子的格子不被地面覆盖
      if (
        tag === TAG_GROUND &&
        (colorTag[idx] === TAG_TREE ||
          colorTag[idx] === TAG_LEAF ||
          colorTag[idx] === TAG_BENCH ||
          colorTag[idx] === TAG_LAMP ||
          colorTag[idx] === TAG_PERSON ||
          colorTag[idx] === TAG_SOIL)
      )
        return;
      // 已有底部场景（路灯/长凳/人）的格子不被树枝/叶子覆盖
      // —— 路灯/长凳/人是前景物体，应在树之前面
      if (
        (tag === TAG_TREE || tag === TAG_LEAF) &&
        (colorTag[idx] === TAG_BENCH ||
          colorTag[idx] === TAG_LAMP ||
          colorTag[idx] === TAG_PERSON)
      )
        return;
      grid[idx] = ch;
      colorTag[idx] = tag;
    }

    function clearDynamicCells() {
      for (let i = 0; i < grid.length; i++) {
        const tag = colorTag[i];
        if (
          tag === TAG_METEOR ||
          tag === TAG_METEOR_HEAD ||
          tag === TAG_SPARK ||
          tag === TAG_BIRD ||
          tag === TAG_CLOUD ||
          tag === TAG_STAR ||
          tag === TAG_LAMP_GLOW
        ) {
          grid[i] = " ";
          colorTag[i] = 0;
        }
      }
    }

    function clearTreeCells() {
      for (let i = 0; i < grid.length; i++) {
        const tag = colorTag[i];
        if (tag === TAG_TREE || tag === TAG_LEAF) {
          grid[i] = " ";
          colorTag[i] = 0;
        }
      }
    }

    // 清除底部场景（路灯/长凳/人）格子，便于每帧重画实现生长与闪烁动画
    function clearBottomSceneCells() {
      for (let i = 0; i < grid.length; i++) {
        const tag = colorTag[i];
        if (
          tag === TAG_BENCH ||
          tag === TAG_LAMP ||
          tag === TAG_PERSON ||
          tag === TAG_LAMP_GLOW
        ) {
          grid[i] = " ";
          colorTag[i] = 0;
        }
      }
    }

    // 按 progress 比例从底部向上"生长"绘制 ASCII art
    function drawArtWithGrowth(
      art: readonly string[],
      x: number,
      y: number,
      tag: number,
      progress: number
    ) {
      const p = Math.max(0, Math.min(1, progress));
      if (p <= 0) return;
      const visibleRows = Math.max(
        1,
        Math.min(art.length, Math.ceil(art.length * p))
      );
      const startRow = art.length - visibleRows;
      for (let row = startRow; row < art.length; row++) {
        for (let column = 0; column < art[row].length; column++) {
          const ch = art[row][column];
          if (ch !== " ") setCell(x + column, y + row, tag, ch);
        }
      }
    }

    // ---------- 地面 ----------
    function drawGround() {
      groundLineY = rows - 1 - Math.max(1, Math.floor(rows * 0.08));
      // 草地线
      for (let x = 0; x < cols; x++) {
        const wave = Math.sin(x * 0.18) * 1.2 + (Math.random() * 1.4 - 0.7);
        const gy = Math.round(groundLineY + wave);
        setCell(x, gy, TAG_GROUND, '"');
        if (Math.random() < 0.5) setCell(x, gy - 1, TAG_GROUND, "'");
      }
      // 泥土层：草地下方 2-3 行用密集 ASCII 字符表示土地
      for (let x = 0; x < cols; x++) {
        for (let dy = 1; dy <= 3; dy++) {
          const soilY = groundLineY + dy;
          // 越深字符越密集
          const chars = dy === 1 ? ["#", "%", "&", "="] : dy === 2 ? ["%", "&", "@", "#"] : ["@", "#", "%", "&"];
          const ch = chars[Math.floor(Math.random() * chars.length)];
          if (Math.random() < 0.85) setCell(x, soilY, TAG_SOIL, ch);
        }
      }
    }

    // ---------- 树林 ----------
    function plantForest() {
      trees = [];
      treeCells = [];

      const treeCount = 6 + Math.floor(Math.random() * 5);
      const usedX = new Set<number>();
      for (let i = 0; i < treeCount; i++) {
        let rootX: number;
        let tries = 0;
        do {
          rootX = 2 + Math.floor(Math.random() * Math.max(1, cols - 4));
          tries++;
        } while (usedX.has(rootX) && tries < 20);
        usedX.add(rootX);
        for (let d = -1; d <= 1; d++) usedX.add(rootX + d);

        const rootY = groundLineY + (Math.random() < 0.3 ? 1 : 0);
        const trunkLen = 7 + Math.floor(Math.random() * 9);
        const tilt = Math.random() * 0.2 - 0.1;
        const startAngle = -Math.PI / 2 + tilt;
        const depthCap = 4 + Math.floor(Math.random() * 2);
        const trunkThickness = (Math.random() < 0.5
          ? 1
          : Math.random() < 0.7
            ? 2
            : 3) as 1 | 2 | 3;
        const swayPhase = Math.random() * Math.PI * 2;
        const swayFreq = 0.04 + Math.random() * 0.04;

        const tree: Tree = {
          rootX,
          trunkThickness,
          swayPhase,
          swayFreq,
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
          depthCap,
          cells: [],
          topY: rootY,
        };
        trees.push(tree);
      }
    }

    function growTree(tree: Tree, treeIndex: number) {
      const next: Branch[] = [];
      for (const b of tree.branches) {
        if (!b.growing) {
          next.push(b);
          continue;
        }
        if (b.growChars < b.maxChars) {
          b.x += Math.cos(b.angle);
          b.y += Math.sin(b.angle);
          if (b.y < tree.topY) tree.topY = b.y;
          if (b.depth === 0 && tree.trunkThickness > 1) {
            const perpX = -Math.sin(b.angle);
            const perpY = Math.cos(b.angle);
            const half = Math.floor(tree.trunkThickness / 2);
            for (let t = -half; t <= half; t++) {
              if (t === 0) continue;
              const px = b.x + perpX * t;
              const py = b.y + perpY * t;
              const chIdx = Math.min(CHARS.length - 1, Math.max(1, CHARS.length - 1 - b.depth));
              setCell(px, py, TAG_TREE, CHARS[chIdx]);
              tree.cells.push({ x: px, y: py, ch: CHARS[chIdx], tag: TAG_TREE, heightFromGround: groundLineY - py, treeIndex });
            }
          }
          const chIdx = Math.min(CHARS.length - 1, Math.max(1, CHARS.length - 1 - b.depth));
          setCell(b.x, b.y, TAG_TREE, CHARS[chIdx]);
          tree.cells.push({ x: b.x, y: b.y, ch: CHARS[chIdx], tag: TAG_TREE, heightFromGround: groundLineY - b.y, treeIndex });
          b.growChars++;
          next.push(b);
        } else {
          b.growing = false;
          next.push(b);
          if (b.depth >= tree.depthCap - 1) {
            const leafCount = 2 + Math.floor(Math.random() * 3);
            for (let k = 0; k < leafCount; k++) {
              const lx = b.x + (Math.random() * 2 - 1);
              const ly = b.y + (Math.random() * 2 - 1);
              const ch = LEAF_CHARS[Math.floor(Math.random() * LEAF_CHARS.length)];
              setCell(lx, ly, TAG_LEAF, ch);
              tree.cells.push({ x: lx, y: ly, ch, tag: TAG_LEAF, heightFromGround: groundLineY - ly, treeIndex });
            }
          }
          if (b.depth < tree.depthCap) {
            const branchCount = 2 + (Math.random() < 0.25 ? 1 : 0);
            for (let i = 0; i < branchCount; i++) {
              const spread = 0.35 + Math.random() * 0.55;
              const newAngle = b.angle + (i - (branchCount - 1) / 2) * spread + (Math.random() * 0.2 - 0.1);
              const len = Math.max(3, b.maxChars - 1 - Math.floor(Math.random() * 3));
              next.push({ x: b.x, y: b.y, angle: newAngle, depth: b.depth + 1, growing: true, growChars: 0, maxChars: len });
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

    function finalizeTreeCells() {
      treeCells = [];
      treeMaxTopY = rows; // 默认底部
      for (let i = 0; i < trees.length; i++) {
        const t = trees[i];
        for (const c of t.cells) treeCells.push(c);
        if (t.topY < treeMaxTopY) treeMaxTopY = t.topY;
      }
      // 流星飞行区域：树顶上方 2 格以上
      treeMaxTopY = Math.max(1, treeMaxTopY - 2);
    }

    function drawTreesWithSway(time: number) {
      clearTreeCells();
      for (const c of treeCells) {
        const heightFactor = Math.max(0, c.heightFromGround) / Math.max(1, rows * 0.3);
        const amp = Math.min(1.5, heightFactor * 1.5);
        const tree = trees[c.treeIndex];
        const phase = tree ? tree.swayPhase : 0;
        const freq = tree ? tree.swayFreq : 0.04;
        const offset = Math.sin(time * freq + phase) * amp;
        setCell(c.x + offset, c.y, c.tag, c.ch);
      }
    }

    // ---------- 星空（深色） ----------
    function spawnStars() {
      stars = [];
      const count = Math.floor(cols * rows * 0.012);
      for (let i = 0; i < count; i++) {
        const x = Math.floor(Math.random() * cols);
        const y = Math.floor(Math.random() * Math.floor(rows * 0.6));
        stars.push({ x, y, brightness: 0.3 + Math.random() * 0.7, twinklePhase: Math.random() * Math.PI * 2, twinkleFreq: 0.02 + Math.random() * 0.05 });
      }
    }

    function drawStars(time: number) {
      for (const s of stars) {
        const tw = 0.5 + 0.5 * Math.sin(time * s.twinkleFreq + s.twinklePhase);
        if (tw * s.brightness < 0.3) continue;
        const ch = STAR_CHARS[Math.floor(tw * (STAR_CHARS.length - 1))];
        setCell(s.x, s.y, TAG_STAR, ch);
      }
    }

    function drawMoon() {
      // 留出右上主题按钮区域，并让圆月成为独立视觉焦点。
      const mx = Math.max(3, Math.min(cols - 14, Math.floor(cols * 0.62)));
      const my = 3;
      for (let i = 0; i < MOON_ART.length; i++) {
        for (let j = 0; j < MOON_ART[i].length; j++) {
          const ch = MOON_ART[i][j];
          if (ch !== " ") setCell(mx + j, my + i, TAG_MOON, ch);
        }
      }
    }

    function drawSun() {
      const sx = Math.max(3, Math.min(cols - 14, Math.floor(cols * 0.72)));
      const sy = 3;
      for (let i = 0; i < SUN_ART.length; i++) {
        for (let j = 0; j < SUN_ART[i].length; j++) {
          const ch = SUN_ART[i][j];
          if (ch !== " ") setCell(sx + j, sy + i, TAG_SUN, ch);
        }
      }
    }

    // ---------- 流星（深色，统一从右向左） ----------
    function spawnMeteor() {
      const startX = cols + 2;
      // y 必须高于所有树（y 值更小）
      const maxY = Math.max(1, treeMaxTopY - 3);
      const y = 1 + Math.floor(Math.random() * Math.max(1, maxY));
      const speed = 1.0 + Math.random() * 0.5;
      const vx = -speed;
      const vy = 0.3 + Math.random() * 0.2; // 轻微向下倾斜
      const life = 30 + Math.floor(Math.random() * 25);
      meteors.push({ x: startX, y, vx, vy, trail: [], life, maxLife: life });
    }

    function updateMeteors() {
      const next: Meteor[] = [];
      for (const m of meteors) {
        m.x += m.vx;
        m.y += m.vy;
        m.life--;

        // 记录尾迹
        m.trail.push({ x: m.x, y: m.y });
        if (m.trail.length > 14) m.trail.shift();

        // 透明度随生命值递减（飞行时逐渐消失）
        const fadeRatio = m.life / m.maxLife;

        // 渲染尾迹：从尾到头字符逐渐变大
        const trailLen = m.trail.length;
        for (let i = 0; i < trailLen; i++) {
          const t = m.trail[i];
          const headRatio = i / Math.max(1, trailLen - 1); // 0=尾, 1=头
          const chIdx = Math.min(METEOR_TAIL.length - 1, Math.floor(headRatio * METEOR_TAIL.length));
          // 接近寿命终点时整体淡出（随机跳过一些格子）
          if (Math.random() > fadeRatio * 0.85 + 0.15) continue;
          setCell(t.x, t.y, TAG_METEOR, METEOR_TAIL[chIdx]);
        }

        // 流星头部：大而明显的字符
        if (m.life > 0 && fadeRatio > 0.1) {
          setCell(m.x, m.y, TAG_METEOR_HEAD, METEOR_HEAD);
          // 头部周围加一点光晕
          if (fadeRatio > 0.5) {
            setCell(m.x + 1, m.y, TAG_METEOR, "*");
            setCell(m.x, m.y - 1, TAG_METEOR, ".");
          }
        }

        // 飞出屏幕或寿命耗尽则消失
        if (m.life > 0 && m.x > -5 && m.x < cols + 5) {
          next.push(m);
        }
      }
      meteors = next;
    }

    // ---------- 鸟（浅色） ----------
    function spawnBird() {
      const fromLeft = Math.random() < 0.5;
      const startX = fromLeft ? -3 : cols + 3;
      const y = 2 + Math.floor(Math.random() * Math.floor(rows * 0.4));
      const speed = 0.4 + Math.random() * 0.3;
      const vx = fromLeft ? speed : -speed;
      birds.push({ x: startX, y, vx, wingPhase: 0 });
    }

    function updateBirds() {
      const next: Bird[] = [];
      for (const b of birds) {
        b.x += b.vx;
        b.wingPhase += 0.3;
        const frameIndex = Math.sin(b.wingPhase) > 0 ? 0 : 1;
        const direction = b.vx > 0 ? "right" : "left";
        drawArt(BIRD_ART[direction][frameIndex], b.x - 2, b.y, TAG_BIRD);
        if (b.x > -5 && b.x < cols + 5) next.push(b);
      }
      birds = next;
    }

    // ---------- 云（浅色） ----------
    function seedClouds() {
      clouds = [];
      const count = Math.max(2, Math.min(4, Math.floor(cols / 45)));
      for (let i = 0; i < count; i++) {
        clouds.push({
          x: Math.floor((cols / count) * i + Math.random() * 12),
          y: 5 + Math.floor(Math.random() * Math.max(2, rows * 0.18)),
          vx: 0.04 + Math.random() * 0.04,
          artIndex: Math.floor(Math.random() * CLOUD_ART.length),
        });
      }
    }

    function updateClouds() {
      for (const cloud of clouds) {
        cloud.x += cloud.vx;
        const art = CLOUD_ART[cloud.artIndex];
        if (cloud.x > cols + 4) {
          cloud.x = -art[art.length - 1].length - 4;
          cloud.y = 5 + Math.floor(Math.random() * Math.max(2, rows * 0.18));
        }
        drawArt(art, cloud.x, cloud.y, TAG_CLOUD);
      }
    }

    // ---------- 火花 ----------
    function updateSparks() {
      const next: Spark[] = [];
      for (const s of sparks) {
        s.x += s.vx;
        s.y += s.vy;
        s.vy += 0.05;
        s.life--;
        if (s.life > 0) {
          setCell(s.x, s.y, TAG_SPARK, s.ch);
          next.push(s);
        }
      }
      sparks = next;
    }

    // ---------- 底部场景：路灯 | 长凳 | 人（紧密排列，置于画面左侧，避开中心登录弹窗） ----------
    // progress: 0..1 生长进度，从地面向上"长出"
    // time: tickCount，用于灯光闪烁动画
    function drawBottomScene(themeName: ThemeName, progress: number, time: number) {
      const lampW = 7;
      const benchW = BENCH_ART[0].length;
      const personW = PERSON_ART.seated[0].length;
      const totalW = lampW + benchW + personW;
      // 放在画面左侧 ~8% 位置，远离居中的登录弹窗
      const startX = Math.max(
        1,
        Math.min(cols - totalW - 2, Math.floor(cols * 0.08))
      );

      const lampX = startX;
      const benchX = lampX + lampW;
      const personX = benchX + benchW - 2;
      // 路灯很高，保护顶部不超出画面
      const lampY = Math.max(1, groundLineY - LAMP_ART.length + 1);

      // 记录路灯灯笼中心，供萤火虫生成使用
      lampCenterX = lampX + 3;
      lampCenterY = lampY + 2;

      drawLamp(lampX, lampY, themeName, progress, time);
      drawBench(benchX, progress);
      drawPerson(personX, progress);
    }

    function drawBench(x: number, progress: number) {
      drawArtWithGrowth(BENCH_ART, x, groundLineY - BENCH_ART.length + 1, TAG_BENCH, progress);
    }

    function drawLamp(x: number, top: number, themeName: ThemeName, progress: number, time: number) {
      // 白天不开灯（light 主题 lampGlow 为 transparent，render 时跳过）
      // 夜晚（dark）：灯柱生长完成后，灯笼点亮并带闪烁光晕
      if (themeName === "dark") {
        // 灯笼位于 art 顶部（第 0-3 行），当 progress 使灯笼可见时才点亮
        const lampHeadVisible = progress >= (LAMP_ART.length - 4) / LAMP_ART.length;
        if (lampHeadVisible) {
          // 闪烁：基础亮度 0.7 + 0.3 的正弦波动
          const flicker = 0.7 + 0.3 * Math.sin(time * 0.18);
          const glowRadius = Math.max(2, Math.floor(6 * flicker));
          const centerX = x + 3;
          const centerY = top + 2;
          for (let dy = -glowRadius; dy <= glowRadius; dy++) {
            for (let dx = -glowRadius; dx <= glowRadius; dx++) {
              const distance = Math.sqrt(dx * dx + dy * dy);
              if (distance > glowRadius || distance < 1) continue;
              // 闪烁时偶尔跳过外圈格子，模拟火光摇曳
              if (distance > 3 && Math.random() > flicker) continue;
              setCell(
                centerX + dx,
                centerY + dy,
                TAG_LAMP_GLOW,
                distance < 2 ? "·" : "."
              );
            }
          }
        }
      }
      drawArtWithGrowth(LAMP_ART, x, top, TAG_LAMP, progress);
    }

    function drawPerson(x: number, progress: number) {
      const art = PERSON_ART.seated;
      drawArtWithGrowth(art, x, groundLineY - art.length + 1, TAG_PERSON, progress);
    }

    function drawArt(
      art: readonly string[],
      x: number,
      y: number,
      tag: number
    ) {
      for (let row = 0; row < art.length; row++) {
        for (let column = 0; column < art[row].length; column++) {
          const ch = art[row][column];
          if (ch !== " ") setCell(x + column, y + row, tag, ch);
        }
      }
    }

    // ---------- 萤火虫（夜晚，围绕路灯飞舞） ----------
    function spawnFirefly(centerX: number, centerY: number) {
      const angle = Math.random() * Math.PI * 2;
      const r = 2 + Math.random() * 6;
      fireflies.push({
        x: centerX + Math.cos(angle) * r,
        y: centerY + Math.sin(angle) * r,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.3,
        life: 80 + Math.floor(Math.random() * 100),
        flickerPhase: Math.random() * Math.PI * 2,
        baseX: centerX,
        baseY: centerY,
      });
    }

    function updateFireflies() {
      const next: Firefly[] = [];
      for (const f of fireflies) {
        // 之字形随机飞行：偶尔改变方向
        if (Math.random() < 0.12) {
          f.vx += (Math.random() - 0.5) * 0.4;
          f.vy += (Math.random() - 0.5) * 0.3;
        }
        // 限速
        f.vx = Math.max(-0.7, Math.min(0.7, f.vx));
        f.vy = Math.max(-0.4, Math.min(0.4, f.vy));
        f.x += f.vx;
        f.y += f.vy;
        f.life--;
        f.flickerPhase += 0.35;
        // 离路灯太远时拉回
        const dx = f.x - f.baseX;
        const dy = f.y - f.baseY;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist > 10) {
          f.vx -= (dx / dist) * 0.08;
          f.vy -= (dy / dist) * 0.08;
        }
        if (f.life > 0 && f.x > -2 && f.x < cols + 2 && f.y > 0 && f.y < rows) {
          const flicker = 0.5 + 0.5 * Math.sin(f.flickerPhase);
          if (flicker > 0.45) {
            const ch = flicker > 0.8 ? "✦" : flicker > 0.6 ? "·" : ".";
            setCell(f.x, f.y, TAG_SPARK, ch);
          }
          next.push(f);
        }
      }
      fireflies = next;
    }

    // ---------- 渲染 ----------
    function render() {
      const theme = currentTheme();
      ctx!.fillStyle = theme.bg;
      ctx!.fillRect(0, 0, W, H);
      ctx!.font = `${CELL}px ui-monospace, "SF Mono", Menlo, monospace`;
      ctx!.textBaseline = "top";

      type Run = { x: number; y: number; ch: string };
      const runsByTag: Record<number, Run[]> = {};
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const idx = r * cols + c;
          const ch = grid[idx];
          if (ch === " ") continue;
          const tag = colorTag[idx];
          if (!runsByTag[tag]) runsByTag[tag] = [];
          runsByTag[tag].push({ x: c * CELL, y: r * CELL, ch });
        }
      }
      const tagColorMap: Record<number, string> = {
        [TAG_TREE]: theme.tree,
        [TAG_LEAF]: theme.leaf,
        [TAG_GROUND]: theme.ground,
        [TAG_SOIL]: theme.soil,
        [TAG_METEOR]: theme.meteor,
        [TAG_METEOR_HEAD]: theme.meteorHead,
        [TAG_SPARK]: theme.meteor,
        [TAG_STAR]: theme.star,
        [TAG_MOON]: theme.moon,
        [TAG_SUN]: theme.sun,
        [TAG_BIRD]: theme.bird,
        [TAG_CLOUD]: theme.cloud,
        [TAG_BENCH]: theme.bench,
        [TAG_LAMP]: theme.lamp,
        [TAG_LAMP_GLOW]: theme.lampGlow,
        [TAG_PERSON]: theme.person,
      };
      for (const tagStr of Object.keys(runsByTag)) {
        const tag = parseInt(tagStr, 10);
        const color = tagColorMap[tag] || theme.tree;
        if (color === "transparent") continue;
        ctx!.fillStyle = color;
        for (const run of runsByTag[tag]) {
          ctx!.fillText(run.ch, run.x, run.y);
        }
      }
    }

    // ---------- 主循环 ----------
    function tick(now: number) {
      rafId = requestAnimationFrame(tick);
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduceMotion) {
        render();
        return;
      }
      if (now - lastTick < TICK_MS) return;
      lastTick = now;
      tickCount++;
      const themeName = currentThemeName();

      clearDynamicCells();

      if (phase === "growing") {
        for (let i = 0; i < trees.length; i++) growTree(trees[i], i);
        // 底部场景（路灯/长凳/人）与树木同步从地面生长
        if (bottomSceneProgress < 1) {
          bottomSceneProgress = Math.min(1, bottomSceneProgress + 0.04);
        }
        clearBottomSceneCells();
        drawBottomScene(themeName, bottomSceneProgress, tickCount);
        if (allTreesDone()) {
          finalizeTreeCells();
          phase = "alive";
          bottomSceneProgress = 1;
          nextMeteorAt = now + 500;
          nextBirdAt = now + 1000;
          nextFireflyAt = now + 1500;
        }
      } else if (phase === "alive") {
        // 先画树（背景），再画底部场景（前景覆盖在树之上）
        drawTreesWithSway(tickCount);
        clearBottomSceneCells();
        drawBottomScene(themeName, 1, tickCount);

        if (themeName === "dark") {
          drawStars(tickCount);
          drawMoon();
          if (meteors.length < 2 && now >= nextMeteorAt) {
            spawnMeteor();
            nextMeteorAt = now + 2500 + Math.random() * 3500;
          }
          updateMeteors();
          // 萤火虫：路灯长成后在路灯周围生成
          if (fireflies.length < 6 && now >= nextFireflyAt) {
            spawnFirefly(lampCenterX, lampCenterY);
            nextFireflyAt = now + 1200 + Math.random() * 2000;
          }
          updateFireflies();
        } else {
          updateClouds();
          drawSun();
          if (birds.length < 2 && now >= nextBirdAt) {
            spawnBird();
            nextBirdAt = now + 3000 + Math.random() * 4000;
          }
          updateBirds();
        }
        updateSparks();
      }
      render();
    }

    function start() {
      resize();
      grid.fill(" ");
      colorTag.fill(0);
      drawGround();
      // 底部场景不再一次性绘制，改为 alive 阶段生长动画
      bottomSceneProgress = 0;
      plantForest();
      if (currentThemeName() === "dark") spawnStars();
      else seedClouds();
      phase = "growing";
      nextMeteorAt = 0;
      nextBirdAt = 0;
      nextFireflyAt = 0;
      tickCount = 0;
      cancelAnimationFrame(rafId);
      lastTick = 0;
      rafId = requestAnimationFrame(tick);
    }

    function onResize() {
      start();
    }

    let lastThemeName: ThemeName = currentThemeName();
    const themeObserver = new MutationObserver(() => {
      const newTheme = currentThemeName();
      if (newTheme !== lastThemeName) {
        lastThemeName = newTheme;
        start();
      }
    });
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      resize();
      drawGround();
      plantForest();
      if (currentThemeName() === "dark") {
        spawnStars();
        drawStars(0);
        drawMoon();
      } else {
        seedClouds();
        updateClouds();
        drawSun();
      }
      let safety = 5000;
      while (trees.some((t) => !t.done) && safety-- > 0) {
        for (let i = 0; i < trees.length; i++) growTree(trees[i], i);
      }
      // 静态模式：直接绘制完整底部场景
      drawBottomScene(currentThemeName(), 1, 0);
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
