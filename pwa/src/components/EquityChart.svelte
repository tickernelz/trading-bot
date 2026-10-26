<script lang="ts">
  import { createChart, LineSeries, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
  import { onDestroy, onMount } from "svelte";
  import { chartOptions, cssColor, onSchemeChange } from "../lib/chartTheme";
  import { parseTs } from "../lib/format";
  import type { Equity } from "../lib/types";

  let { equity, label = "Kurva ekuitas bot A dan bot B, tujuh hari" }: { equity: Equity; label?: string } = $props();

  let host: HTMLDivElement;
  let chart: IChartApi | null = null;
  let lines: ISeriesApi<"Line">[] = [];
  let detach: (() => void) | null = null;

  function draw() {
    if (!chart) return;
    for (const l of lines) chart.removeSeries(l);
    const styles = [
      { color: cssColor("--ink2"), lineStyle: LineStyle.Dashed },
      { color: cssColor("--ink"), lineStyle: LineStyle.Solid },
    ];
    lines = equity.series.map((s, i) => {
      const line = chart!.addSeries(LineSeries, { lineWidth: 2, priceLineVisible: false, title: s.label, ...styles[i % 2] });
      line.setData(s.points.map(([ts, v]) => ({ time: Math.floor(parseTs(ts) / 1000) as UTCTimestamp, value: v })));
      return line;
    });
    lines[0]?.createPriceLine({ price: equity.start_equity, color: cssColor("--rule-strong"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, title: "modal awal" });
    chart.timeScale().fitContent();
  }

  function theme() {
    chart?.applyOptions(chartOptions());
    draw();
  }

  onMount(() => {
    chart = createChart(host, chartOptions());
    detach = onSchemeChange(theme);
    draw();
  });

  $effect(() => {
    void equity;
    draw();
  });

  onDestroy(() => {
    detach?.();
    chart?.remove();
    chart = null;
  });
</script>

<div class="chart" bind:this={host} role="img" aria-label={label}></div>

<style>
  .chart {
    width: 100%;
    height: clamp(260px, 44vh, 420px);
  }
</style>
