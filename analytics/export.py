"""CSV export of trade history and an informational tax summary; not tax advice."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Any

from analytics.trades import closed_trades, number, parse_time, profit_abs

TRADE_COLUMNS = (
    "trade_id",
    "pair",
    "is_open",
    "enter_tag",
    "exit_reason",
    "open_date",
    "close_date",
    "open_rate",
    "close_rate",
    "amount",
    "stake_amount",
    "fee_open",
    "fee_close",
    "profit_abs",
    "profit_pct",
)
TEXT_COLUMNS = {"pair", "enter_tag", "exit_reason"}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

TAX_BASIS = {
    "regulation": "PMK 50/2025 (berlaku 1 Agustus 2025)",
    "applies_to": "penjualan aset kripto lewat PPMSE yang merupakan PAKD dalam negeri: PPh Pasal 22 final atas nilai transaksi",
    "rate_note": "0,21% untuk PAKD dalam negeri, 1% bila bukan PAKD dalam negeri; angka di bawah memakai pph22_final_pct dari konfigurasi",
    "verified_against": "artikel Direktorat Jenderal Pajak, pajak.go.id, 31 Juli 2025 (disunting 8 September 2025)",
    "not_verified": [
        "status Indodax sebagai PAKD",
        "teks resmi pasal PMK 50/2025 (hanya dibaca lewat artikel DJP)",
        "PPN atas jasa platform dan biaya platform tidak dihitung",
    ],
    "disclaimer": "Informasi dari data dry-run, bukan nasihat pajak dan bukan laporan pajak. Dry-run tidak memotong pajak sungguhan.",
}


def safe_text(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def trade_row(trade: dict[str, Any]) -> dict[str, Any]:
    row = {column: trade.get(column) for column in TRADE_COLUMNS}
    row["profit_abs"] = number(trade, "close_profit_abs", "profit_abs")
    row["profit_pct"] = number(trade, "close_profit_pct", "profit_pct")
    return {
        column: safe_text(value) if column in TEXT_COLUMNS else ("" if value is None else value)
        for column, value in row.items()
    }


def trades_csv(trades: list[dict[str, Any]]) -> str:
    """Render trades as CSV, neutralising spreadsheet formulas in text columns."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=TRADE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for trade in trades:
        writer.writerow(trade_row(trade))
    return buffer.getvalue()


def sell_value(trade: dict[str, Any]) -> float | None:
    amount = number(trade, "amount")
    rate = number(trade, "close_rate")
    if amount is None or rate is None:
        return None
    return amount * rate


def tax_summary(trades: list[dict[str, Any]], rate_pct: float, year: int | None = None) -> dict[str, Any]:
    """Sum sell value and the configured final tax rate per month over closed trades."""
    months: dict[str, dict[str, float]] = defaultdict(
        lambda: {"trades": 0, "sell_value_idr": 0.0, "pph22_final_idr": 0.0, "realized_profit_idr": 0.0}
    )
    skipped = 0
    for trade in closed_trades(trades):
        closed_at = parse_time(str(trade["close_date"]))
        if year is not None and closed_at.year != year:
            continue
        value = sell_value(trade)
        if value is None:
            skipped += 1
            continue
        bucket = months[closed_at.strftime("%Y-%m")]
        bucket["trades"] += 1
        bucket["sell_value_idr"] += value
        bucket["pph22_final_idr"] += value * rate_pct / 100
        bucket["realized_profit_idr"] += profit_abs(trade)
    rows = [{"month": month, **values} for month, values in sorted(months.items())]
    totals = {
        key: sum(row[key] for row in rows)
        for key in ("trades", "sell_value_idr", "pph22_final_idr", "realized_profit_idr")
    }
    return {
        "year": year,
        "rate_pct": rate_pct,
        "months": rows,
        "total": totals,
        "skipped_without_rate": skipped,
        "basis": TAX_BASIS,
    }
