from __future__ import annotations

from datetime import date
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
        FunnelConfig(sector_min_count=2, top_n_sectors=1, use_concept_map=True),
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
    assert survivors == ["000001", "000002"]


def test_layer3_rejects_when_group_metadata_is_unavailable() -> None:
    symbols = ["000001", "000002", "000003"]

    survivors, top = layer3_sector_resonance(
        symbols,
        {},
        FunnelConfig(),
        base_symbols=symbols,
        df_map={symbol: _history(1.2) for symbol in symbols},
    )

    assert survivors == []
    assert top == []


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


def test_wyckoff_industry_context_uses_sw1_from_rps_membership(monkeypatch) -> None:
    from app.services import rps_rotation
    from app.services.screener import _load_wyckoff_industry_context

    mapping = pl.DataFrame({
        "_sym_up": ["000001.SZ", "000002.SZ"],
        "industry": ["银行-股份制银行", "电子-半导体"],
        "sw1_name": ["银行", "电子"],
    })
    monkeypatch.setattr(rps_rotation, "_load_concept_map_df", lambda *_args, **_kwargs: (mapping, 2))
    monkeypatch.setattr(rps_rotation, "membership_source_for_kind", lambda _kind: "tushare_sw_index_member_all")
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=Path(".")))

    sector_map, source = _load_wyckoff_industry_context(repo, pd.Timestamp("2026-09-08").date())

    assert sector_map == {"000001.SZ": "银行", "000002.SZ": "电子"}
    assert source == "tushare_sw_index_member_all"


def test_wyckoff_tdx_context_uses_881_fine_industry_memberships(monkeypatch) -> None:
    from app.services import tdx_board_rotation
    from app.services.screener import _load_tdx_wyckoff_context

    def members(_data_dir, *, trade_date, category):
        assert trade_date == date(2026, 9, 23)
        if category == "industry":
            return pl.DataFrame({
                "ts_code": ["880001.TDX", "881001.TDX", "881501.TDX"],
                "name": ["Broad", "Fine", "Outside fine scope"],
                "con_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
                "con_name": ["平安银行", "平安银行", "平安银行"],
                "trade_date": ["20260923", "20260923", "20260923"],
            })
        return pl.DataFrame({
            "ts_code": ["885001.TDX"],
            "name": ["AI"],
            "con_code": ["000001.SZ"],
            "con_name": ["平安银行"],
            "trade_date": ["20260923"],
        })

    monkeypatch.setattr(tdx_board_rotation, "load_category_membership", members)
    monkeypatch.setattr(tdx_board_rotation, "top_category_board_names", lambda *_args, **_kwargs: ["AI [885001.TDX]"])
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=Path(".")))

    industries, concepts, hot, source = _load_tdx_wyckoff_context(repo, date(2026, 9, 23), 5)

    assert industries["000001.SZ"] == ["Fine [881001.TDX]"]
    assert concepts["000001.SZ"] == ["AI [885001.TDX]"]
    assert hot == ["AI [885001.TDX]"]
    assert source == "tushare_tdx_member_daily_snapshot"
