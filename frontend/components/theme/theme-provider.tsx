"use client";

/**
 * Theme provider for LifeTree.
 *
 * Wraps next-themes' ThemeProvider with the project's defaults:
 *   - attribute="class"  → toggles the `dark` class on <html>
 *   - defaultTheme="dark" → first-time visitors get dark mode (matches
 *                          the original LifeTree look)
 *   - enableSystem        → "follow system" option respects OS preference
 *   - disableTransitionOnChange → avoids the slow color-fade flash when
 *                          switching themes
 *
 * The chosen theme is persisted by next-themes in localStorage under the
 * `theme` key. The Provider is a client component; layout.tsx wraps the
 * whole app with it.
 */

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}
