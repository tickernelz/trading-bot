<script lang="ts">
  import {
    CandlestickSeries,
    createChart,
    createSeriesMarkers,
    LineSeries,
    LineStyle,
    LineType,
    type AutoscaleInfo,
    type IChartApi,
    type IPriceLine,
    type ISeriesApi,
    type ISeriesMarkersPluginApi,
    type SeriesMarker,
    type Time,
    type UTCTimestamp,
  } from "lightweight-charts";
  import { onDestroy, onMount } from "svelte";
  import { chartOptions, cssColor, onSchemeChange } from "../lib/chartTheme";
  import { parseTs, signedPercent } from "../lib/format";
  import { t } from "../lib/i18n";
  import { newsByBar, sentimentLine } from "../lib/timeMachine";
  import type { CandleFrame, Decision, NewsItem, SentimentPoint, Trade } from "../lib/types";
  import { verdictText } from "../lib/words";

  let {
    frame,
    trades,
    showFast,
    showSlow,
    showRsi,
    showMarkers,
    news = [],
    showNews = false,
    sentiment = [],
    showSentiment = false,
    focus = null,
  }: {
    frame: CandleFrame;
    trades: Trade[];
    showFast: boolean;
    showSlow: boolean;
    showRsi: boolean;
    showMarkers: boolean;
    news?: NewsItem[];
    showNews?: boolean;
    sentiment?: SentimentPoint[];
    showSentiment?: boolean;
    focus?: Decision | null;
  } = $props();

  let host: HTMLDivElement;
  let chart: IChartApi | null = null;
  let candles: ISeriesApi<"Candlestick"> | null = null;
  let fast: ISeriesApi<"Line"> | null = null;
  let slow: ISeriesApi<"Line"> | null = null;
  let rsi: ISeriesApi<"Line"> | null = null;
  let fng: ISeriesApi<"Line"> | null = null;
  let centered: string | null = null;
  let markers: ISeriesMarkersPluginApi<Time> | null = null;
  let stops: IPriceLine[] = [];
  let stopFloor: number | null = null;
  let fitted = "";
  let detach: (() => void) | null = null;

  const HOUR_S = 3600;
  const toTime = (v: string | number) => Math.floor(parseTs(v) / 1000) as UTCTimestamp;
  const barTime = (ms: number) => (Math.floor(ms / 1000 / HOUR_S) * HOUR_S) as UTCTimestamp;

  function theme() {
    if (!chart || !candles || !fast || !slow || !rsi) return;
    chart.applyOptions(chartOptions());
    const ink = cssColor("--ink");
    const ink2 = cssColor("--ink2");
    candles.applyOptions({
      upColor: cssColor("--panel"),
      downColor: ink2,
      borderUpColor: ink2,
      borderDownColor: ink2,
      wickUpColor: ink2,
      wickDownColor: ink2,
    });
    fast.applyOptions({ color: ink });
    slow.applyOptions({ color: ink2 });
    rsi.applyOptions({ color: ink2 });
    fng?.applyOptions({ color: ink2 });
    draw();
  }

  function draw() {
    if (!chart || !candles || !fast || !slow || !rsi || !fng || !markers) return;
    const col = (name: string) => frame.columns.indexOf(name);
    const [iD, iO, iH, iL, iC, iF, iS, iR] = ["date", "open", "high", "low", "close", "ema_fast", "ema_slow", "rsi"].map(col);
    const rows = frame.data;
    candles.setData(rows.map((r) => ({ time: toTime(r[iD] as string), open: Number(r[iO]), high: Number(r[iH]), low: Number(r[iL]), close: Number(r[iC]) })));
    const line = (i: number) =>
      i < 0 ? [] : rows.filter((r) => r[i] !== null && r[i] !== undefined).map((r) => ({ time: toTime(r[iD] as string), value: Number(r[i]) }));
    fast.setData(showFast ? line(iF) : []);
    slow.setData(showSlow ? line(iS) : []);
    rsi.setData(showRsi ? line(iR) : []);
    const first = rows.length ? toTime(rows[0][iD] as string) : 0;
    const list: SeriesMarker<Time>[] = [];
    if (showMarkers) {
      const ink = cssColor("--ink");
      for (const trade of trades) {
        const open = barTime(trade.open_timestamp);
        if (open >= first) list.push({ time: open, position: "belowBar", shape: "arrowUp", color: ink, text: t("chart.entry_marker", { id: trade.trade_id }) });
        if (!trade.is_open && trade.close_timestamp) {
          const close = barTime(trade.close_timestamp);
          if (close >= first) list.push({ time: close, position: "aboveBar", shape: "arrowDown", color: ink, text: t("chart.exit_marker", { pct: signedPercent(trade.profit_pct ?? 0) }) });
        }
      }
    }
    const last = rows.length ? toTime(rows[rows.length - 1][iD] as string) : 0;
    if (showNews) {
      const ink2 = cssColor("--ink2");
      for (const [bar, items] of newsByBar(news, first)) {
        list.push({ time: bar as UTCTimestamp, position: "aboveBar", shape: "square", color: ink2, size: 0.6, text: t("chart.news_marker", { n: items.length }) });
      }
    }
    if (focus) {
      const bar = barTime(parseTs(focus.candle));
      if (bar >= first) list.push({ time: bar, position: "aboveBar", shape: "arrowDown", color: cssColor("--ink"), text: t("tm.marker", { verdict: verdictText(focus) }) });
    }
    markers.setMarkers(list.sort((a, b) => (a.time as number) - (b.time as number)));
    fng.setData(showSentiment ? sentimentLine(sentiment, first, last).map((p) => ({ time: p.time as UTCTimestamp, value: p.value })) : []);
    for (const s of stops) candles.removePriceLine(s);
    const open = trades.filter((trade) => trade.is_open);
    const stopOf = (trade: Trade) => trade.stop_loss_abs ?? trade.open_rate * (1 + (trade.stop_loss_pct ?? -3) / 100);
    stopFloor = open.length ? Math.min(...open.map(stopOf)) : null;
    stops = open
      .map((trade) =>
        candles!.createPriceLine({
          price: stopOf(trade),
          color: cssColor("--sig"),
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: t("chart.stop_line", { id: trade.trade_id }),
        }),
      );
    chart.panes()[1]?.setHeight(showRsi ? 110 : 0);
    chart.panes()[2]?.setHeight(showSentiment ? 90 : 0);
    const bars = Math.max(24, Math.min(96, Math.round(host.clientWidth / 11)));
    if (fitted !== frame.pair && rows.length) {
      fitted = frame.pair;
      chart.timeScale().setVisibleLogicalRange({ from: rows.length - bars, to: rows.length + 2 });
    }
    const focusId = focus ? focus.decision_id : null;
    if (focusId !== centered && rows.length) {
      centered = focusId;
      const at = focus ? rows.findIndex((r) => toTime(r[iD] as string) >= barTime(parseTs(focus.candle))) : -1;
      if (at >= 0) chart.timeScale().setVisibleLogicalRange({ from: at - bars / 2, to: at + bars / 2 });
      else chart.timeScale().setVisibleLogicalRange({ from: rows.length - bars, to: rows.length + 2 });
    }
  }

  onMount(() => {
    chart = createChart(host, chartOptions());
    candles = chart.addSeries(CandlestickSeries, {
      priceLineVisible: false,
      lastValueVisible: true,
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const info = original();
        if (!info?.priceRange || stopFloor === null) return info;
        return { ...info, priceRange: { ...info.priceRange, minValue: Math.min(info.priceRange.minValue, stopFloor) } };
      },
    });
    fast = chart.addSeries(LineSeries, { lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    slow = chart.addSeries(LineSeries, { lineWidth: 2, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    rsi = chart.addSeries(LineSeries, { lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "RSI" }, 1);
    rsi.createPriceLine({ price: 70, color: cssColor("--rule-strong"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
    rsi.createPriceLine({ price: 30, color: cssColor("--rule-strong"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
    fng = chart.addSeries(
      LineSeries,
      {
        lineWidth: 2,
        lineType: LineType.WithSteps,
        priceLineVisible: false,
        lastValueVisible: true,
        title: t("chart.fear_greed_short"),
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
      },
      2,
    );
    fng.createPriceLine({ price: 25, color: cssColor("--rule-strong"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
    fng.createPriceLine({ price: 75, color: cssColor("--rule-strong"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: "" });
    markers = createSeriesMarkers(candles, []);
    detach = onSchemeChange(theme);
    theme();
  });

  $effect(() => {
    void [frame, trades, showFast, showSlow, showRsi, showMarkers, news, showNews, sentiment, showSentiment, focus];
    draw();
  });

  onDestroy(() => {
    detach?.();
    chart?.remove();
    chart = null;
  });
</script>

<div class="chart" bind:this={host} role="img" aria-label={t("chart.candle_label", { pair: frame.pair })}></div>

<style>
  .chart {
    width: 100%;
    height: clamp(320px, 58vh, 560px);
  }
</style>
