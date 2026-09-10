from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import polars as pl

from app.wyckoff.config import FunnelConfig
from app.wyckoff.layer3_resonance import layer3_sector_resonance


def _history(multiplier: float) -> pd.DataFrame:
    close = np.linspace(10.0, 10.0 * multiplier, 30)
    return pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=30), "close": close})


def test_layer3_prefers_multi_symbol_strong_concept() -> None:
    symbols = ["000001", "000002", "000003", "000004", "000005"]
    concepts = {
        "000001": ["AI 算力"],
        "000002": ["AI 算力"],
        "000003": ["AI 算力"],
        "000004": ["银行"],
        "000005": ["银行"],
    }
    histories = {
        "000001": _history(1.8),
        "000002": _history(1.7),
        "000003": _history(1.6),
        "000004": _history(1.1),
        "000005": _history(1.05),
    }

    survivors, top = layer3_sector_resonance(
        symbols,
        {},
        FunnelConfig(sector_min_count=2, top_n_sectors=1),
        base_symbols=symbols,
        df_map=histories,
        concept_map=concepts,
    )

    assert top == ["AI 算力"]
    assert {"000001", "000002", "000003"}.issubset(survivors)


def test_layer3_falls_back_to_industry_when_concepts_absent() -> None:
    symbols = ["000001", "000002", "000003"]
    survivors, top = layer3_sector_resonance(
        symbols,
        {"000001": "半导体", "000002": "半导体", "000003": "银行"},
        FunnelConfig(sector_min_count=2),
        base_symbols=symbols,
        df_map={symbol: _history(1.2) for symbol in symbols},
    )

    assert top == ["半导体"]
    assert survivors == symbols


def test_wyckoff_concept_context_uses_same_day_limit_up_mainlines(monkeypatch) -> None:
    from app.services import market_mainline, rps_rotation
    from app.services.screener import _load_wyckoff_concept_context

    mapping = pl.DataFrame({
        "_sym_up": ["000001.SZ", "000001.SZ", "000002.SZ"],
        "concept": ["算力", "机器人", "算力"],
    })
    history = pl.DataFrame({
        "date": [pd.Timestamp("2026-09-08").date()] * 3,
        "member": ["机器人", "算力", "银行"],
        "rank": [1, 2, 6],
    })
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args: (mapping, 2))
    monkeypatch.setattr(market_mainline, "load_mainline_history", lambda *_args: history)
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=Path(".")))

    concept_map, hot_concepts = _load_wyckoff_concept_context(repo, pd.Timestamp("2026-09-08").date(), 5)

    assert concept_map["000001.SZ"] == ["机器人", "算力"]
    assert hot_concepts == ["机器人", "算力"]
