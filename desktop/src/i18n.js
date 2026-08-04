// 桌面启动器轻量级 i18n 模块。
// 与前端 frontend/lib/i18n/messages.ts 保持 locale 一致，但只包含启动器需要的 key。
// 探测顺序：Tauri 持久化 → navigator.language → 兜底 zh-CN

export const LOCALES = ["zh-CN", "zh-TW", "en", "es", "de", "fr"];
export const DEFAULT_LOCALE = "zh-CN";

export const LOCALE_LABELS = {
  "zh-CN": "简体中文",
  "zh-TW": "繁體中文",
  en: "English",
  es: "Español",
  de: "Deutsch",
  fr: "Français",
};

const MESSAGES = {
  "zh-CN": {
    "launcher.subtitle": "选择本次使用的数据服务",
    "launcher.mode.title": "运行模式",
    "launcher.mode.local": "本地服务",
    "launcher.mode.local.desc": "数据仅保存在此设备",
    "launcher.mode.selfHosted": "自托管服务",
    "launcher.mode.selfHosted.desc": "连接你的 LifeTree 部署",
    "launcher.mode.cloud": "官方云服务（推荐）",
    "launcher.mode.cloud.desc": "连接 LifeTree 云端租户，开箱即用",
    "launcher.field.serviceUrl": "服务地址",
    "launcher.field.modelRuntime": "模型配置",
    "launcher.modelRuntime.serverManaged": "由所连接的服务管理",
    "launcher.modelRuntime.configureAfterLaunch": "启动后在设置中配置",
    "launcher.button.connect": "连接",
    "launcher.button.launch": "启动",
    "launcher.busy.connecting": "正在连接...",
    "launcher.busy.startingLocal": "正在启动本地服务...",
    "launcher.status.detecting": "检测中",
    "launcher.status.available": "可用",
    "launcher.status.unavailable": "不可用",
    "launcher.localRuntime.detecting": "正在检测本地运行时",
    "launcher.localRuntime.running": "本地服务正在运行",
    "launcher.localRuntime.dataOnly": "数据仅保存在此设备",
    "launcher.localRuntime.notBundled": "尚未打包本地 Sidecar",
    "launcher.localRuntime.detectFailed": "无法检测本地运行时",
    "launcher.localRuntime.requiresTauri": "需要 Tauri 桌面宿主",
    "launcher.error.requireTauri": "请在 Tauri 桌面窗口中完成连接",
    "launcher.footer.version": "桌面基础版本 {version}",
    "launcher.language": "语言",
  },
  "zh-TW": {
    "launcher.subtitle": "選擇本次使用的資料服務",
    "launcher.mode.title": "執行模式",
    "launcher.mode.local": "本地服務",
    "launcher.mode.local.desc": "資料僅儲存於此裝置",
    "launcher.mode.selfHosted": "自架服務",
    "launcher.mode.selfHosted.desc": "連接你的 LifeTree 部署",
    "launcher.mode.cloud": "官方雲端服務（推薦）",
    "launcher.mode.cloud.desc": "連接 LifeTree 雲端租戶，開箱即用",
    "launcher.field.serviceUrl": "服務位址",
    "launcher.field.modelRuntime": "模型設定",
    "launcher.modelRuntime.serverManaged": "由所連接的服務管理",
    "launcher.modelRuntime.configureAfterLaunch": "啟動後在設定中配置",
    "launcher.button.connect": "連接",
    "launcher.button.launch": "啟動",
    "launcher.busy.connecting": "正在連接...",
    "launcher.busy.startingLocal": "正在啟動本地服務...",
    "launcher.status.detecting": "檢測中",
    "launcher.status.available": "可用",
    "launcher.status.unavailable": "不可用",
    "launcher.localRuntime.detecting": "正在檢測本地執行時",
    "launcher.localRuntime.running": "本地服務正在執行",
    "launcher.localRuntime.dataOnly": "資料僅儲存於此裝置",
    "launcher.localRuntime.notBundled": "尚未封裝本地 Sidecar",
    "launcher.localRuntime.detectFailed": "無法檢測本地執行時",
    "launcher.localRuntime.requiresTauri": "需要 Tauri 桌面宿主",
    "launcher.error.requireTauri": "請在 Tauri 桌面視窗中完成連接",
    "launcher.footer.version": "桌面基礎版本 {version}",
    "launcher.language": "語言",
  },
  en: {
    "launcher.subtitle": "Choose data service for this session",
    "launcher.mode.title": "Runtime mode",
    "launcher.mode.local": "Local service",
    "launcher.mode.local.desc": "Data stays on this device only",
    "launcher.mode.selfHosted": "Self-hosted",
    "launcher.mode.selfHosted.desc": "Connect to your LifeTree deployment",
    "launcher.mode.cloud": "Official cloud (recommended)",
    "launcher.mode.cloud.desc": "Connect to LifeTree cloud tenant, ready to use",
    "launcher.field.serviceUrl": "Service URL",
    "launcher.field.modelRuntime": "Model runtime",
    "launcher.modelRuntime.serverManaged": "Managed by the connected service",
    "launcher.modelRuntime.configureAfterLaunch": "Configure in settings after launch",
    "launcher.button.connect": "Connect",
    "launcher.button.launch": "Launch",
    "launcher.busy.connecting": "Connecting...",
    "launcher.busy.startingLocal": "Starting local service...",
    "launcher.status.detecting": "Detecting",
    "launcher.status.available": "Available",
    "launcher.status.unavailable": "Unavailable",
    "launcher.localRuntime.detecting": "Detecting local runtime",
    "launcher.localRuntime.running": "Local service is running",
    "launcher.localRuntime.dataOnly": "Data stays on this device only",
    "launcher.localRuntime.notBundled": "Local sidecar not bundled",
    "launcher.localRuntime.detectFailed": "Cannot detect local runtime",
    "launcher.localRuntime.requiresTauri": "Requires Tauri desktop host",
    "launcher.error.requireTauri": "Please connect from a Tauri desktop window",
    "launcher.footer.version": "Desktop version {version}",
    "launcher.language": "Language",
  },
  es: {
    "launcher.subtitle": "Elija el servicio de datos para esta sesión",
    "launcher.mode.title": "Modo de ejecución",
    "launcher.mode.local": "Servicio local",
    "launcher.mode.local.desc": "Los datos se guardan solo en este dispositivo",
    "launcher.mode.selfHosted": "Autohospedado",
    "launcher.mode.selfHosted.desc": "Conéctese a su despliegue de LifeTree",
    "launcher.mode.cloud": "Nube oficial (recomendado)",
    "launcher.mode.cloud.desc": "Conéctese al inquilino en la nube de LifeTree, listo para usar",
    "launcher.field.serviceUrl": "URL del servicio",
    "launcher.field.modelRuntime": "Motor de modelo",
    "launcher.modelRuntime.serverManaged": "Gestionado por el servicio conectado",
    "launcher.modelRuntime.configureAfterLaunch": "Configurar en ajustes después del inicio",
    "launcher.button.connect": "Conectar",
    "launcher.button.launch": "Iniciar",
    "launcher.busy.connecting": "Conectando...",
    "launcher.busy.startingLocal": "Iniciando servicio local...",
    "launcher.status.detecting": "Detectando",
    "launcher.status.available": "Disponible",
    "launcher.status.unavailable": "No disponible",
    "launcher.localRuntime.detecting": "Detectando entorno local",
    "launcher.localRuntime.running": "El servicio local se está ejecutando",
    "launcher.localRuntime.dataOnly": "Los datos se guardan solo en este dispositivo",
    "launcher.localRuntime.notBundled": "Sidecar local no incluido",
    "launcher.localRuntime.detectFailed": "No se puede detectar el entorno local",
    "launcher.localRuntime.requiresTauri": "Requiere host de escritorio Tauri",
    "launcher.error.requireTauri": "Conéctese desde una ventana de escritorio Tauri",
    "launcher.footer.version": "Versión de escritorio {version}",
    "launcher.language": "Idioma",
  },
  de: {
    "launcher.subtitle": "Wählen Sie den Datendienst für diese Sitzung",
    "launcher.mode.title": "Ausführungsmodus",
    "launcher.mode.local": "Lokaler Dienst",
    "launcher.mode.local.desc": "Daten bleiben nur auf diesem Gerät",
    "launcher.mode.selfHosted": "Selbst gehostet",
    "launcher.mode.selfHosted.desc": "Verbinden Sie sich mit Ihrem LifeTree-Deployment",
    "launcher.mode.cloud": "Offizielle Cloud (empfohlen)",
    "launcher.mode.cloud.desc": "Verbinden Sie sich mit dem LifeTree-Cloud-Mandanten, einsatzbereit",
    "launcher.field.serviceUrl": "Dienst-URL",
    "launcher.field.modelRuntime": "Modell-Laufzeit",
    "launcher.modelRuntime.serverManaged": "Vom verbundenen Dienst verwaltet",
    "launcher.modelRuntime.configureAfterLaunch": "Nach dem Start in den Einstellungen konfigurieren",
    "launcher.button.connect": "Verbinden",
    "launcher.button.launch": "Starten",
    "launcher.busy.connecting": "Verbinden...",
    "launcher.busy.startingLocal": "Lokaler Dienst wird gestartet...",
    "launcher.status.detecting": "Wird erkannt",
    "launcher.status.available": "Verfügbar",
    "launcher.status.unavailable": "Nicht verfügbar",
    "launcher.localRuntime.detecting": "Lokale Laufzeit wird erkannt",
    "launcher.localRuntime.running": "Lokaler Dienst läuft",
    "launcher.localRuntime.dataOnly": "Daten bleiben nur auf diesem Gerät",
    "launcher.localRuntime.notBundled": "Lokaler Sidecar nicht gebündelt",
    "launcher.localRuntime.detectFailed": "Lokale Laufzeit kann nicht erkannt werden",
    "launcher.localRuntime.requiresTauri": "Erfordert Tauri-Desktop-Host",
    "launcher.error.requireTauri": "Bitte verbinden Sie sich aus einem Tauri-Desktop-Fenster",
    "launcher.footer.version": "Desktop-Version {version}",
    "launcher.language": "Sprache",
  },
  fr: {
    "launcher.subtitle": "Choisissez le service de données pour cette session",
    "launcher.mode.title": "Mode d'exécution",
    "launcher.mode.local": "Service local",
    "launcher.mode.local.desc": "Les données restent uniquement sur cet appareil",
    "launcher.mode.selfHosted": "Auto-hébergé",
    "launcher.mode.selfHosted.desc": "Connectez-vous à votre déploiement LifeTree",
    "launcher.mode.cloud": "Cloud officiel (recommandé)",
    "launcher.mode.cloud.desc": "Connectez-vous au locataire cloud LifeTree, prêt à l'emploi",
    "launcher.field.serviceUrl": "URL du service",
    "launcher.field.modelRuntime": "Runtime du modèle",
    "launcher.modelRuntime.serverManaged": "Géré par le service connecté",
    "launcher.modelRuntime.configureAfterLaunch": "Configurer dans les paramètres après le lancement",
    "launcher.button.connect": "Connecter",
    "launcher.button.launch": "Démarrer",
    "launcher.busy.connecting": "Connexion...",
    "launcher.busy.startingLocal": "Démarrage du service local...",
    "launcher.status.detecting": "Détection",
    "launcher.status.available": "Disponible",
    "launcher.status.unavailable": "Indisponible",
    "launcher.localRuntime.detecting": "Détection du runtime local",
    "launcher.localRuntime.running": "Le service local est en cours d'exécution",
    "launcher.localRuntime.dataOnly": "Les données restent uniquement sur cet appareil",
    "launcher.localRuntime.notBundled": "Sidecar local non inclus",
    "launcher.localRuntime.detectFailed": "Impossible de détecter le runtime local",
    "launcher.localRuntime.requiresTauri": "Nécessite un hôte de bureau Tauri",
    "launcher.error.requireTauri": "Veuillez vous connecter depuis une fenêtre de bureau Tauri",
    "launcher.footer.version": "Version de bureau {version}",
    "launcher.language": "Langue",
  },
};

let currentLocale = DEFAULT_LOCALE;
const hasTauriHost = typeof window.__TAURI_INTERNALS__ !== "undefined";

/** 探测初始 locale：Tauri 持久化 → navigator.language → 兜底 */
async function resolveLocale() {
  // 1. 尝试从 Tauri 读取持久化设置
  if (hasTauriHost) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const saved = await invoke("load_locale");
      if (saved && LOCALES.includes(saved)) return saved;
    } catch {
      // 忽略，继续回退
    }
  }

  // 2. navigator.language 前缀匹配
  const nav = navigator.language || "";
  if (nav.startsWith("zh")) {
    return nav.includes("TW") || nav.includes("Hant") ? "zh-TW" : "zh-CN";
  }
  if (nav.startsWith("en")) return "en";
  if (nav.startsWith("es")) return "es";
  if (nav.startsWith("de")) return "de";
  if (nav.startsWith("fr")) return "fr";

  // 3. 兜底
  return DEFAULT_LOCALE;
}

/** 变量插值：{name} → vars.name */
function interpolate(str, vars) {
  if (!vars) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? `{${k}}`);
}

/** 翻译函数 */
export function t(key, vars) {
  const dict = MESSAGES[currentLocale] || MESSAGES[DEFAULT_LOCALE];
  const str = dict[key] || MESSAGES[DEFAULT_LOCALE][key] || key;
  return interpolate(str, vars);
}

/** 获取当前 locale */
export function getLocale() {
  return currentLocale;
}

/** 初始化 i18n：探测 locale 并应用到 DOM */
export async function initI18n() {
  currentLocale = await resolveLocale();
  applyToDom();
  document.documentElement.lang = currentLocale;
}

/** 将所有 data-i18n 属性的元素翻译为当前语言 */
function applyToDom() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const varsAttr = el.getAttribute("data-i18n-vars");
    const vars = varsAttr ? JSON.parse(varsAttr) : undefined;
    el.textContent = t(key, vars);
  });
  // placeholder
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });
}

/** 切换语言并持久化 */
export async function setLocale(locale) {
  if (!LOCALES.includes(locale)) return;
  currentLocale = locale;
  document.documentElement.lang = locale;
  applyToDom();
  if (hasTauriHost) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("save_locale", { locale });
    } catch {
      // 忽略持久化失败
    }
  }
  // 通知 main.js 重新渲染动态文本
  window.dispatchEvent(new CustomEvent("locale-changed", { detail: locale }));
}
