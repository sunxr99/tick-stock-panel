"""Persistent background research runs for the standalone Wyckoff V2 engine."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl

from app.parquet import scan_enriched_parquet
from app.wyckoff.v2 import WyckoffV2Config, run_event_backtest_frames
from app.wyckoff.v2.backtest import EXPERIMENT_VARIANTS

ENGINE_VERSION = "v2-p0-range-taxonomy-2"
SUCCESS = "SUCCESS"
ACTIVE = frozenset({"QUEUED", "RUNNING"})
_CSV_COLUMNS = ("symbol", "date", "range_id", "event_id", "entry", "state", "parent_event_id", "support", "creek", "invalid_price")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class WyckoffV2ResearchService:
    """Small file-backed job manager, deliberately isolated from production screening."""

    def __init__(self, data_dir: Path | str) -> None:
        self._data_dir = Path(data_dir).resolve()
        self._root = self._data_dir / "research" / "wyckoff_v2" / "runs"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self.recover_interrupted()

    def recover_interrupted(self) -> int:
        recovered = 0
        for path in self._root.glob("*/manifest.json"):
            manifest = self.get(path.parent.name)
            if manifest and manifest.get("status") in ACTIVE:
                self._update(path.parent.name, status="FAILED", finished_at=_now(), error="backend restarted before research run completed")
                recovered += 1
        return recovered

    def shutdown(self) -> None:
        return None

    def start(self, request: Mapping[str, Any], *, force_recompute: bool = False) -> dict[str, Any]:
        normalized = self._canonical_request(request)
        config_hash = self._config_hash(normalized)
        with self._lock:
            if not force_recompute:
                cached = self._find(config_hash, {SUCCESS}) or self._find(config_hash, ACTIVE)
                if cached is not None:
                    return {**cached, "reused": True}
            run_id = uuid.uuid4().hex
            manifest = {"run_id": run_id, "status": "QUEUED", "request": normalized, "engine_version": ENGINE_VERSION, "config_hash": config_hash, "created_at": _now(), "started_at": None, "finished_at": None, "error": None, "progress": {"processed_symbols": 0, "total_symbols": 0, "percent": 0}}
            run_dir = self._run_dir(run_id)
            run_dir.mkdir()
            _write_json(run_dir / "manifest.json", manifest)
            _write_json(run_dir / "summary.json", {})
            thread = threading.Thread(target=self._run, args=(run_id,), daemon=True, name=f"wyckoff-v2-{run_id[:8]}")
            self._threads[run_id] = thread
            thread.start()
            return {**manifest, "reused": False}

    def get(self, run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(run_id) / "manifest.json"
        if not path.exists():
            return None
        manifest = json.loads(path.read_text(encoding="utf-8"))
        started = manifest.get("started_at")
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds() if started else 0.0
        return {**manifest, "elapsed_seconds": round(elapsed, 3)}

    def summary(self, run_id: str) -> dict[str, Any] | None:
        manifest = self.get(run_id)
        if manifest is None or manifest["status"] != SUCCESS:
            return None
        return json.loads((self._run_dir(run_id) / "summary.json").read_text(encoding="utf-8"))

    def events(self, run_id: str, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        path = self._run_dir(run_id) / "events.json"
        items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return items[offset : offset + limit], len(items)

    def export_path(self, run_id: str) -> Path | None:
        path = self._run_dir(run_id) / "events.csv"
        return path if path.exists() else None

    def report_path(self, run_id: str) -> Path | None:
        path = self._run_dir(run_id) / "report.md"
        return path if path.exists() else None

    def _run(self, run_id: str) -> None:
        try:
            manifest = self.get(run_id)
            if manifest is None:
                return
            self._update(run_id, status="RUNNING", started_at=_now())
            request = manifest["request"]
            start, end = date.fromisoformat(request["start_date"]), date.fromisoformat(request["end_date"])
            source = (scan_enriched_parquet(str(self._data_dir / "kline_daily_enriched" / "**" / "*.parquet")).filter(pl.col("date").is_between(start - timedelta(days=220), end + timedelta(days=max(request["horizons"]) + 14))).select(["symbol", "date", "open", "high", "low", "close", "volume"]))
            symbols = source.filter(pl.col("date").is_between(start, end)).select(pl.col("symbol").unique().sort()).collect().get_column("symbol").to_list()
            self._update(run_id, progress={"processed_symbols": 0, "total_symbols": len(symbols), "percent": 0})
            records: list[dict[str, object]] = []
            cfg = WyckoffV2Config()
            report = run_event_backtest_frames(
                self._frames(run_id, source, symbols, request["batch_size"]),
                cfg,
                horizons=request["horizons"],
                entries=request["entries"],
                experiment_variants=request["experiment_variants"],
                benchmark_return=self._benchmark(request["benchmark"], start, end, request["horizons"]),
                market_regime=self._market_regime(start, end, cfg),
                event_sink=records.append,
                entry_start=start,
                entry_end=end,
            )
            report.update({"run_id": run_id, "engine_version": ENGINE_VERSION, "config_hash": manifest["config_hash"], "benchmark": request["benchmark"]})
            _write_json(self._run_dir(run_id) / "summary.json", report)
            _write_json(self._run_dir(run_id) / "events.json", records)
            self._write_csv(run_id, records, request["horizons"])
            self._write_report(run_id, report)
            self._update(run_id, status=SUCCESS, finished_at=_now(), progress={"processed_symbols": len(symbols), "total_symbols": len(symbols), "percent": 100})
        except Exception as exc:
            self._update(run_id, status="FAILED", finished_at=_now(), error=str(exc)[:2000])
        finally:
            with self._lock:
                self._threads.pop(run_id, None)

    def _benchmark(self, name: str, start: date, end: date, horizons: list[int]) -> Callable[[str, int], float | None] | None:
        if name == "none":
            return None
        max_horizon = max(horizons)
        if name == "all_a":
            source = scan_enriched_parquet(str(self._data_dir / "kline_daily_enriched" / "**" / "*.parquet")).filter(pl.col("date").is_between(start, end + timedelta(days=max_horizon + 14))).select(["symbol", "date", "open", "close"])
            values: dict[int, dict[str, float]] = {}
            try:
                for days in horizons:
                    result = (source.sort(["symbol", "date"]).with_columns(pl.col("open").shift(-1).over("symbol").alias("entry_open"), pl.col("close").shift(-days).over("symbol").alias("exit_close")).filter(pl.col("date").is_between(start, end) & (pl.col("entry_open") > 0)).with_columns(((pl.col("exit_close") / pl.col("entry_open") - 1.0) * 100).alias("return_pct")).group_by("date").agg(pl.col("return_pct").mean()).collect().to_dicts())
                    values[days] = {str(row["date"]): float(row["return_pct"]) for row in result if row["return_pct"] is not None}
            except Exception:
                return None

            return lambda signal_date, days: values.get(days, {}).get(signal_date)
        symbol = "000300.SH" if name == "all_a" else name
        try:
            rows = scan_enriched_parquet(str(self._data_dir / "kline_index_enriched" / "**" / "*.parquet")).filter((pl.col("symbol") == symbol) & pl.col("date").is_between(start, end + timedelta(days=max_horizon + 14))).select(["date", "open", "close"]).sort("date").collect().to_dicts()
        except Exception:
            return None
        dates = [str(row["date"]) for row in rows]
        opens, closes = [float(row["open"]) for row in rows], [float(row["close"]) for row in rows]
        indexes = {value: index for index, value in enumerate(dates)}

        def evaluate(signal_date: str, days: int) -> float | None:
            index = indexes.get(signal_date)
            if index is None or index + days >= len(dates):
                return None
            return (closes[index + days] / opens[index + 1] - 1.0) * 100.0 if opens[index + 1] > 0 else None

        return evaluate

    def _market_regime(self, start: date, end: date, cfg: WyckoffV2Config) -> Callable[[str], str]:
        """Classify 000300 using only its closed history on each signal date."""
        try:
            rows = (
                scan_enriched_parquet(str(self._data_dir / "kline_index_enriched" / "**" / "*.parquet"))
                .filter((pl.col("symbol") == "000300.SH") & pl.col("date").is_between(start - timedelta(days=220), end))
                .select(["date", "close"])
                .sort("date")
                .collect()
                .to_dicts()
            )
        except Exception:
            return lambda _signal_date: "UNCLASSIFIED"
        values = [(str(row["date"]), float(row["close"])) for row in rows if row.get("close") and float(row["close"]) > 0]
        window = cfg.market_regime_return_window
        labels: dict[str, str] = {}
        for index, (day, close) in enumerate(values):
            if index < window:
                labels[day] = "UNCLASSIFIED"
                continue
            return_pct = (close / values[index - window][1] - 1.0) * 100.0
            if return_pct >= cfg.market_regime_bull_return_pct:
                labels[day] = "BULL"
            elif return_pct <= cfg.market_regime_bear_return_pct:
                labels[day] = "BEAR"
            else:
                labels[day] = "SIDEWAYS"
        return lambda signal_date: labels.get(signal_date, "UNCLASSIFIED")

    def _frames(self, run_id: str, source: pl.LazyFrame, symbols: list[str], batch_size: int) -> Iterator[tuple[str, pd.DataFrame]]:
        total, processed, iterator = len(symbols), 0, iter(symbols)
        while batch := list(islice(iterator, max(1, batch_size))):
            frame = source.filter(pl.col("symbol").is_in(batch)).sort(["symbol", "date"]).collect()
            for key, partition in frame.partition_by("symbol", as_dict=True, maintain_order=True).items():
                symbol = str(key[0] if isinstance(key, tuple) else key)
                yield symbol, partition.drop("symbol").to_pandas()
                processed += 1
            self._update(run_id, progress={"processed_symbols": processed, "total_symbols": total, "percent": int(processed * 100 / total) if total else 100})

    def _write_csv(self, run_id: str, records: list[dict[str, object]], horizons: list[int]) -> None:
        with (self._run_dir(run_id) / "events.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            columns = [*_CSV_COLUMNS, *[f"t_plus_{value}_return_pct" for value in horizons], *[f"t_plus_{value}_mfe_pct" for value in horizons], *[f"t_plus_{value}_mae_pct" for value in horizons]]
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for record in records:
                row = {name: record.get(name) for name in _CSV_COLUMNS}
                for horizon, outcome in record.get("outcomes", {}).items():
                    for field in ("return_pct", "mfe_pct", "mae_pct"):
                        row[f"t_plus_{horizon}_{field}"] = outcome.get(field)
                writer.writerow(row)

    def _write_report(self, run_id: str, report: Mapping[str, Any]) -> None:
        """Persist a compact, reproducible research report; no result selection."""
        lines = [
            "# Wyckoff V2 P1 Research Report", "", "Research only; does not affect L1-L4 selection or defaults.", "",
            "## Spring funnel", "",
        ]
        for state, value in report.get("spring_outcomes", {}).items():
            if state not in {"rates", "total"}:
                lines.append(f"- {state}: {value}")
        lines.extend(["", "## LPS funnel", "", "| Stage | Count | Conversion |", "| --- | ---: | ---: |"])
        for stage, value in report.get("lps_funnel", {}).items():
            lines.append(f"| {stage} | {value['count']} | {value['conversion_rate']:.2%} |")
        lines.extend(["", "## LPS rejection reasons", ""])
        for reason, value in report.get("lps_rejection_reasons", {}).items():
            lines.append(f"- {reason}: {value['count']} ({value['percentage']:.2f}%)")
        lines.extend(["", "## Experiment entries", "", "| Entry | Samples |", "| --- | ---: |"])
        for name, value in report.get("entries", {}).items():
            lines.append(f"| {name} | {value['events']} |")
        (self._run_dir(run_id) / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _update(self, run_id: str, **changes: Any) -> None:
        with self._lock:
            manifest = self.get(run_id)
            if manifest is not None:
                manifest.update(changes)
                _write_json(self._run_dir(run_id) / "manifest.json", manifest)

    def _find(self, config_hash: str, statuses: set[str] | frozenset[str]) -> dict[str, Any] | None:
        matches = []
        for path in self._root.glob("*/manifest.json"):
            item = self.get(path.parent.name)
            if item and item.get("config_hash") == config_hash and item.get("status") in statuses:
                matches.append(item)
        return max(matches, key=lambda item: str(item.get("created_at")), default=None)

    def _run_dir(self, run_id: str) -> Path:
        if not run_id.isalnum():
            raise ValueError("invalid run id")
        return self._root / run_id

    @staticmethod
    def _canonical_request(request: Mapping[str, Any]) -> dict[str, Any]:
        allowed_entries = {
            "spring_aggressive", "spring_standard", "spring_conservative", "lps_standard",
            "spring_confirm_atr", "spring_confirm_clv", "spring_confirm_volume",
            "spring_confirm_clv_volume", "spring_confirm_swing_high", "lps_classic_standard",
            "lps_classic_swing_high", "lps_classic_sos_held_20", "lps_classic_sos_held_30",
            "lps_classic_sos_held_40", "lps_classic_sos_held_50", "lps_shallow_standard",
        }
        entries = sorted(set(request.get("entries") or allowed_entries))
        if not entries or set(entries) - allowed_entries:
            raise ValueError("entries must contain known V2 entry types")
        experiment_variants = sorted(set(request.get("experiment_variants") or ()))
        if set(experiment_variants) - set(EXPERIMENT_VARIANTS):
            raise ValueError("experiment_variants must contain known P1 experiment variants")
        start, end = str(request["start_date"]), str(request["end_date"])
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("start_date must not be after end_date")
        horizons = sorted({int(value) for value in request.get("horizons", (1, 3, 5, 10, 20)) if int(value) > 0})
        if not horizons:
            raise ValueError("horizons must contain a positive value")
        benchmark = str(request.get("benchmark", "all_a"))
        if benchmark not in {"all_a", "000300.SH", "none"}:
            raise ValueError("benchmark must be all_a, 000300.SH, or none")
        return {"start_date": start, "end_date": end, "entries": entries, "experiment_variants": experiment_variants, "universe": "all", "benchmark": benchmark, "horizons": horizons, "batch_size": 100, "v2_config": asdict(WyckoffV2Config())}

    @staticmethod
    def _config_hash(request: Mapping[str, Any]) -> str:
        payload = json.dumps({"engine_version": ENGINE_VERSION, **request}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
