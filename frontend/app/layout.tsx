import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";
import { ToastProvider } from "@/components/ui/toast";
import { RegisterSW } from "@/components/pwa/register-sw";
import { SSEProvider } from "@/components/sse/sse-provider";
import { ThemeProvider } from "@/components/theme/theme-provider";
import { AuthGate } from "@/components/auth/auth-gate";
import { I18nProvider } from "@/lib/i18n/provider";
import {
  DEFAULT_LOCALE,
  MESSAGES,
  isLocale,
  type Locale,
} from "@/lib/i18n/messages";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });

async function resolveLocaleFromCookie(): Promise<Locale> {
  const cookieStore = await cookies();
  const stored = cookieStore.get("lifetree.locale")?.value;
  if (isLocale(stored)) return stored;
  return DEFAULT_LOCALE;
}

export async function generateMetadata(): Promise<Metadata> {
  const locale = await resolveLocaleFromCookie();
  const dict = MESSAGES[locale] ?? MESSAGES[DEFAULT_LOCALE];
  return {
    title: dict["app.name"] ?? "LifeTree",
    description: dict["app.tagline"] ?? "",
    applicationName: "LifeTree",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/media/favicon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/media/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/media/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [
      { url: "/media/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
    shortcut: ["/media/favicon-32.png"],
  },
  appleWebApp: {
    capable: true,
    title: "LifeTree",
    statusBarStyle: "black-translucent",
  },
  formatDetection: {
    telephone: false,
    email: false,
    address: false,
  },
  other: {
    "apple-mobile-web-app-capable": "yes",
    "mobile-web-app-capable": "yes",
    "apple-mobile-web-app-status-bar-style": "black-translucent",
  },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f6f2" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0d12" },
  ],
  // colorScheme stays "dark light" so the browser UI (form controls,
  // scrollbars) matches whichever theme the user picks.
  colorScheme: "dark light",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await resolveLocaleFromCookie();
  return (
    // suppressHydrationWarning: next-themes injects the `dark`/`light`
    // class on <html> before React hydrates, so the server-rendered HTML
    // won't match. This is the documented next-themes setup.
    <html lang={locale} suppressHydrationWarning>
      <head>
        {/* Inline PWA-detection script — runs synchronously BEFORE first
            paint so the ``html.pwa`` class is set before any CSS applies.
            This prevents a flash of the persistent sidebar rail on PWA
            launch: ``html.pwa .sidebar-rail { display: none !important }``
            kicks in immediately, hiding the rail that the SSR-rendered
            ``<Sidebar>`` would otherwise show. Without this, the rail
            would be visible until React hydrates and ``useIsPwa`` flips
            to the drawer branch. Covers both ``display-mode`` (Android/
            desktop PWA) and ``navigator.standalone`` (iOS PWA). */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var d=false;try{d=new URL(window.location.href).searchParams.get('pwa')==='1';}catch(e){}if(!d){var modes=['standalone','minimal-ui','window-controls-overlay','fullscreen'];for(var i=0;i<modes.length;i++){try{if(window.matchMedia('(display-mode: '+modes[i]+')').matches){d=true;break;}}catch(e){}}}if(!d&&window.navigator&&window.navigator.standalone===true){d=true;}if(d){document.documentElement.classList.add('pwa');}if(window.innerWidth<1024){document.documentElement.classList.add('drawer-mode');}}catch(e){}})();`,
          }}
        />
      </head>
      <body className={`${inter.variable} font-sans antialiased`}>
        <ThemeProvider>
          <I18nProvider>
            <ToastProvider>
              <SSEProvider>
                <AuthGate>
                  <div className="flex h-screen overflow-hidden">
                    <Sidebar />
                    <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden safe-top main-shell">
                      {children}
                    </main>
                  </div>
                </AuthGate>
                <RegisterSW />
              </SSEProvider>
            </ToastProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
