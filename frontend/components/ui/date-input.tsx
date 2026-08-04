import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * DateInput — 包装原生 ``<input type="date">``，处理 PWA 下的样式一致性。
 *
 * 设计取舍：
 *  - 移动端 / PWA 下原生日期 picker 是最佳方案：触发系统原生 UI、无障碍
 *    语义完整、跨时区处理一致。自定义日历反而会破坏移动端体验。
 *  - PWA 下的真正问题是样式不一致：
 *      1. iOS standalone 下 ``::-webkit-calendar-picker-indicator`` 颜色不可控
 *         （默认黑色，dark mode 下看不清）。
 *      2. 某些浏览器下 placeholder 颜色与主题冲突。
 *      3. ``appearance`` 默认值会导致 iOS 下显示系统外观。
 *  - 本组件统一 ``appearance: none``，并通过 CSS 控制 picker 图标颜色。
 */
export const DateInput = React.forwardRef<
  HTMLInputElement,
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & {
    label?: string;
  }
>(({ className, label, ...props }, ref) => (
  <input
    ref={ref}
    type="date"
    aria-label={label}
    className={cn("lt-date-input", className)}
    {...props}
  />
));
DateInput.displayName = "DateInput";

/**
 * TimeInput — 包装原生 ``<input type="time">``，同 DateInput 的设计取舍。
 */
export const TimeInput = React.forwardRef<
  HTMLInputElement,
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & {
    label?: string;
  }
>(({ className, label, ...props }, ref) => (
  <input
    ref={ref}
    type="time"
    aria-label={label}
    className={cn("lt-time-input", className)}
    {...props}
  />
));
TimeInput.displayName = "TimeInput";
