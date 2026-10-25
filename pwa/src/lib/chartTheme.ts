import { ColorType, TickMarkType, type ChartOptions, type DeepPartial, type Time } from "lightweight-charts";
import { price } from "./format";

let probe: CanvasRenderingContext2D | null = null;

export function cssColor(name: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  probe ??= document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  if (!probe) return raw;
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = "#000";
  probe.fillStyle = raw;
  probe.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = probe.getImageData(0, 0, 1, 1).data;
  return "rgba(" + r + "," + g + "," + b + "," + (a / 255).toFixed(3) + ")";
}

const hm = new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const dm = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short" });
const full = new Intl.DateTimeFormat("id-ID", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

const toDate = (time: Time) => new Date((time as number) * 1000);

export function chartOptions(): DeepPartial<ChartOptions> {
  const ink2 = cssColor("--ink2");
  const rule = cssColor("--rule");
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: cssColor("--panel") },
      textColor: ink2,
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 12,
      attributionLogo: false,
      panes: { separatorColor: rule, separatorHoverColor: rule },
    },
    grid: { vertLines: { color: rule }, horzLines: { color: rule } },
    rightPriceScale: { borderColor: rule },
    timeScale: {
      borderColor: rule,
      timeVisible: true,
      secondsVisible: false,
      tickMarkFormatter: (time: Time, type: TickMarkType) => {
        const d = toDate(time);
        return type <= TickMarkType.DayOfMonth ? dm.format(d) : hm.format(d);
      },
    },
    crosshair: {
      vertLine: { color: ink2, labelBackgroundColor: cssColor("--ink") },
      horzLine: { color: ink2, labelBackgroundColor: cssColor("--ink") },
    },
    localization: {
      locale: "id-ID",
      priceFormatter: (p: number) => price(p),
      timeFormatter: (time: Time) => full.format(toDate(time)),
    },
  };
}

export function onSchemeChange(apply: () => void): () => void {
  const query = matchMedia("(prefers-color-scheme: dark)");
  query.addEventListener("change", apply);
  return () => query.removeEventListener("change", apply);
}
