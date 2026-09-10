"""Tushare-backed static market metadata used by the Wyckoff funnel.

Only normalized ``symbol -> industry`` data crosses this boundary.  Strategy
code never receives the Tushare token or a provider-specific response.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app import secrets_store

logger = logging.getLogger(__name__)

TUSHARE_PRO_URL = "https://api.tushare.pro"
SECTOR_CACHE_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class SectorMapResult:
    mapping: dict[str, str]
    source: str
    cached_at: float | None = None


def load_tushare_sector_map(data_dir: Path, *, now: float | None = None) -> SectorMapResult:
    """Load the current Tushare ``stock_basic.industry`` mapping.

    A fresh local cache avoids a network request on every strategy execution.
    On a transient Tushare failure an older cache remains usable, but callers
    receive its source explicitly so a missing map cannot be mistaken for a
    successful metadata load.
    """
    timestamp = time.time() if now is None else now
    cache_path = data_dir / "metadata" / "tushare_sector_map.json"
    cached, cached_at = _read_cache(cache_path)
    if cached and cached_at is not None and timestamp - cached_at < SECTOR_CACHE_TTL_SECONDS:
        return SectorMapResult(cached, "tushare_cache_fresh", cached_at)

    token = secrets_store.get_env_backed_secret("tushare_token", "TUSHARE_TOKEN")
    if not token:
        logger.warning("Wyckoff industry metadata unavailable: TUSHARE_TOKEN is not configured")
        return _stale_or_empty(cached, cached_at)

    try:
        response = httpx.post(
            TUSHARE_PRO_URL,
            json={
                "api_name": "stock_basic",
                "token": token,
                "params": {"exchange": "", "list_status": "L"},
                "fields": "ts_code,industry",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        mapping = _parse_sector_map(response.json())
        if not mapping:
            raise ValueError("stock_basic returned no usable ts_code/industry records")
    except (httpx.HTTPError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("Wyckoff industry metadata refresh failed: %s", exc)
        return _stale_or_empty(cached, cached_at)

    _write_cache(cache_path, mapping, timestamp)
    logger.info("Wyckoff industry metadata refreshed from Tushare: %d symbols", len(mapping))
    return SectorMapResult(mapping, "tushare_live", timestamp)


def _parse_sector_map(payload: dict[str, Any]) -> dict[str, str]:
    if int(payload.get("code", -1)) != 0:
        raise ValueError(f"Tushare stock_basic rejected request: {payload.get('msg') or 'unknown error'}")
    data = payload.get("data") or {}
    fields = data.get("fields") or []
    items = data.get("items") or []
    try:
        code_index = list(fields).index("ts_code")
        industry_index = list(fields).index("industry")
    except ValueError as exc:
        raise ValueError("Tushare stock_basic response is missing ts_code or industry") from exc
    return {
        symbol: industry
        for item in items
        if len(item) > max(code_index, industry_index)
        and (symbol := _normalize_symbol(item[code_index]))
        and (industry := str(item[industry_index] or "").strip())
    }


def _normalize_symbol(value: object) -> str:
    text = str(value or "").strip().upper()
    code, separator, exchange = text.partition(".")
    if not code or not separator or exchange not in {"SH", "SZ", "BJ"}:
        return ""
    return f"{code}.{exchange}"


def _read_cache(path: Path) -> tuple[dict[str, str], float | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        mapping = payload.get("mapping")
        cached_at = float(payload.get("cached_at"))
        if isinstance(mapping, dict):
            return {str(symbol): str(industry) for symbol, industry in mapping.items() if industry}, cached_at
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return {}, None


def _write_cache(path: Path, mapping: dict[str, str], cached_at: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"cached_at": cached_at, "mapping": mapping}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _stale_or_empty(cached: dict[str, str], cached_at: float | None) -> SectorMapResult:
    if cached:
        return SectorMapResult(cached, "tushare_cache_stale", cached_at)
    return SectorMapResult({}, "unavailable", None)
