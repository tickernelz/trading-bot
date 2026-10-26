import "@fontsource-variable/atkinson-hyperlegible-next/wght.css";
import "./app.css";
import { mount } from "svelte";
import App from "./App.svelte";
import { gateway } from "./lib/gateway.svelte";

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  void navigator.serviceWorker.register("/sw.js", { scope: "/" });
}

gateway.start();

export default mount(App, { target: document.getElementById("app")! });
