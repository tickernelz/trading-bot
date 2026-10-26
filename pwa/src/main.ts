import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";
import "./app.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { gateway } from "./lib/gateway.svelte";
import { language, t } from "./lib/i18n";

document.documentElement.lang = language.htmlLang;
document.title = t("app.name");

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  void navigator.serviceWorker.register("/sw.js", { scope: "/" });
}

gateway.start();

export default mount(App, { target: document.getElementById("app")! });
