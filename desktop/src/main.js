import { invoke } from "@tauri-apps/api/core";
import logoUrl from "../../frontend/public/media/logo.png";
import { initI18n, t, setLocale, getLocale, LOCALES } from "./i18n.js";
import "./styles.css";

const form = document.querySelector("#runtime-form");
const logo = document.querySelector("#brand-logo");
const serviceUrl = document.querySelector("#service-url");
const errorMessage = document.querySelector("#error");
const connectButton = document.querySelector("#connect");
const localRuntimeStatus = document.querySelector("#local-runtime-status");
const localMode = document.querySelector("#local-mode");
const localModeOption = document.querySelector("#local-mode-option");
const localModeBadge = document.querySelector("#local-mode-badge");
const serviceUrlField = document.querySelector("#service-url-field");
const localeSelect = document.querySelector("#locale-select");
const hasTauriHost = typeof window.__TAURI_INTERNALS__ !== "undefined";

logo.src = logoUrl;

const CLOUD_DEFAULT_URL = "https://lifetree.spark-ai.top";

function selectedMode() {
  return new FormData(form).get("mode");
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = !message;
}

function setBusy(busy) {
  connectButton.disabled = busy;
  if (busy) {
    connectButton.textContent = selectedMode() === "local_private"
      ? t("launcher.busy.startingLocal")
      : t("launcher.busy.connecting");
  } else {
    connectButton.textContent = selectedMode() === "local_private"
      ? t("launcher.button.launch")
      : t("launcher.button.connect");
  }
}

function syncModeFields() {
  const mode = selectedMode();
  const local = mode === "local_private";
  serviceUrl.disabled = local;
  serviceUrl.required = !local;
  serviceUrlField.hidden = local;
  // 官方云服务模式自动填入默认地址（用户未手动修改时）
  if (mode === "cloud_multi_tenant" && !serviceUrl.value) {
    serviceUrl.value = CLOUD_DEFAULT_URL;
  } else if (mode === "self_hosted" && serviceUrl.value === CLOUD_DEFAULT_URL) {
    serviceUrl.value = "";
  }
  connectButton.textContent = local
    ? t("launcher.button.launch")
    : t("launcher.button.connect");
}

async function restoreConfig() {
  if (!hasTauriHost) {
    serviceUrl.value = CLOUD_DEFAULT_URL;
    return;
  }
  try {
    const config = await invoke("load_runtime_config");
    if (!config) return;
    const option = form.querySelector(`[name="mode"][value="${config.mode}"]`);
    if (option && !option.disabled) option.checked = true;
    if (config.mode !== "local_private") serviceUrl.value = config.service_url || "";
    syncModeFields();
  } catch (error) {
    showError(String(error));
  }
}

async function detectLocalRuntime() {
  if (!hasTauriHost) {
    localRuntimeStatus.textContent = t("launcher.localRuntime.requiresTauri");
    return;
  }
  try {
    const status = await invoke("local_runtime_status");
    if (status.sidecarPresent) {
      localRuntimeStatus.textContent = status.running
        ? t("launcher.localRuntime.running")
        : t("launcher.localRuntime.dataOnly");
    } else {
      localRuntimeStatus.textContent = t("launcher.localRuntime.notBundled");
    }
    localMode.disabled = !status.available;
    localModeOption.classList.toggle("unavailable", !status.available);
    localModeBadge.textContent = status.available
      ? t("launcher.status.available")
      : t("launcher.status.unavailable");
  } catch {
    localRuntimeStatus.textContent = t("launcher.localRuntime.detectFailed");
  }
}

form.addEventListener("change", () => {
  showError("");
  syncModeFields();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  setBusy(true);

  if (!hasTauriHost) {
    showError(t("launcher.error.requireTauri"));
    setBusy(false);
    return;
  }

  const config = {
    version: 1,
    mode: selectedMode(),
    service_url: selectedMode() === "local_private" ? "" : serviceUrl.value,
    model_runtime: "server_managed",
  };

  try {
    const saved = await invoke("save_runtime_config", { config });
    await invoke("open_runtime", { config: saved });
  } catch (error) {
    showError(String(error));
    setBusy(false);
  }
});

// 语言切换
localeSelect.addEventListener("change", async (e) => {
  await setLocale(e.target.value);
  syncModeFields();
});

// locale 变化时重新渲染动态文本
window.addEventListener("locale-changed", () => {
  syncModeFields();
  // 重新检测本地运行时状态文本
  if (hasTauriHost) {
    detectLocalRuntime();
  }
});

async function initialize() {
  // 初始化 i18n
  await initI18n();
  // 同步语言选择器
  localeSelect.value = getLocale();

  await detectLocalRuntime();
  await restoreConfig();
  syncModeFields();
}

initialize();
