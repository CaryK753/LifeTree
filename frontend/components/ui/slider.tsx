import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Slider — 包装原生 ``<input type="range">``，提供一致的 PWA 样式与无障碍属性。
 *
 * 设计取舍：
 *  - 移动端 / PWA 下原生 range 控件触屏体验优于自定义实现（系统原生手势、
 *    无障碍语义、键盘可达）。
 *  - 这里仅做样式统一与触控目标尺寸增强（PWA 下 thumb 更大、focus 环更明显）。
 *  - 样式全局规则在 ``globals.css`` 的 ``input[type="range"]`` 区块；本组件
 *    额外补充语义属性（aria-valuenow 等）。
 */
export const Slider = React.forwardRef<
  HTMLInputElement,
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & {
    /** 当前数值（受控）。 */
    value?: number;
    /** 默认数值（非受控）。 */
    defaultValue?: number;
    /** 最小值。 */
    min?: number;
    /** 最大值。 */
    max?: number;
    /** 步长。 */
    step?: number;
    /** 方向标签，用于 ``aria-label``。 */
    label?: string;
  }
>(({ className, value, defaultValue, min, max, step, label, ...props }, ref) => {
  const ariaValue = value ?? defaultValue;
  return (
    <input
      ref={ref}
      type="range"
      role="slider"
      aria-label={label}
      aria-valuemin={typeof min === "number" ? min : undefined}
      aria-valuemax={typeof max === "number" ? max : undefined}
      aria-valuenow={typeof ariaValue === "number" ? ariaValue : undefined}
      aria-valuetext={
        typeof ariaValue === "number" && typeof step === "number"
          ? String(ariaValue.toFixed(step < 1 ? 1 : 0))
          : typeof ariaValue === "number"
            ? String(ariaValue)
            : undefined
      }
      min={min}
      max={max}
      step={step}
      value={value}
      defaultValue={value === undefined ? defaultValue : undefined}
      className={cn("lt-slider", className)}
      {...props}
    />
  );
});
Slider.displayName = "Slider";
