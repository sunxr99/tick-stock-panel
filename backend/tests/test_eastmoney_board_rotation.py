from __future__ import annotations

from datetime import date

import polars as pl

from app.services import eastmoney_board_rotation
from app.services.eastmoney_concept_taxonomy import classify_concept


def _row(day: str, code: str, pct: float, *, name: str = "测试概念") -> dict[str, object]:
    return {
        "ts_code": code,
        "trade_date": day,
        "name": name,
        "leading": "龙头股",
        "leading_code": "000001.SZ",
        "pct_change": pct,
        "leading_pct": pct + 1.0,
        "total_mv": 100.0,
        "turnover_rate": 2.0,
        "up_num": 8,
        "down_num": 2,
        "idx_type": "概念板块",
        "level": None,
    }


def _write_index(tmp_path, rows: list[dict[str, object]]) -> None:
    path = eastmoney_board_rotation.index_path(tmp_path)
    path.parent.mkdir(parents=True)
    pl.DataFrame(rows).write_parquet(path)


def test_rotation_uses_eastmoney_concepts_and_skips_unchanged_weekend_snapshots(tmp_path) -> None:
    rows: list[dict[str, object]] = []
    for number, day in enumerate(("20260914", "20260915", "20260916", "20260917", "20260918", "20260919"), start=1):
        rows.extend([_row(day, "BK0001.DC", float(number)), _row(day, "BK0002.DC", -float(number), name="另一概念")])
    # The provider's weekend copy is byte-for-byte the preceding session.
    rows.extend([_row("20260920", "BK0001.DC", 6.0), _row("20260920", "BK0002.DC", -6.0, name="另一概念")])
    rows.append({**_row("20260921", "BK0001.DC", 7.0), "idx_type": "行业板块"})
    _write_index(tmp_path, rows)

    frame = eastmoney_board_rotation.load_hot_rotation_history(tmp_path)

    assert frame.get_column("date").max() == date(2026, 9, 19)
    latest = eastmoney_board_rotation.latest_hot_rotation(tmp_path)
    assert latest.get_column("ts_code").to_list() == ["BK0001.DC", "BK0002.DC"]
    first = latest.row(0, named=True)
    assert first["pct_change"] == 6.0
    assert first["return_5d"] is not None
    assert first["return_5d"] > 0
    assert first["return_5d_percentile"] == 100.0
    assert latest.row(1, named=True)["return_5d_percentile"] == 0.0


def test_rotation_history_is_case_insensitive_and_limits_sessions(tmp_path) -> None:
    rows = []
    for number, day in enumerate(("20260914", "20260915", "20260916"), start=1):
        rows.append(_row(day, "BK0001.DC", float(number)))
    _write_index(tmp_path, rows)

    frame = eastmoney_board_rotation.hot_rotation_history(tmp_path, ts_code="bk0001.dc", limit=2)

    assert frame.get_column("date").to_list() == [date(2026, 9, 15), date(2026, 9, 16)]


def test_taxonomy_separates_short_term_events_and_style_filters(tmp_path) -> None:
    rows = []
    for day in ("20260914", "20260915", "20260916", "20260917", "20260918"):
        rows.extend([
            _row(day, "BK0001.DC", 1.0, name="首发经济"),
            _row(day, "BK0002.DC", 2.0, name="昨日连板"),
            _row(day, "BK0003.DC", 3.0, name="低价股"),
        ])
    _write_index(tmp_path, rows)

    latest = eastmoney_board_rotation.latest_hot_rotation(tmp_path)

    assert latest.get_column("name").to_list() == ["首发经济"]
    assert eastmoney_board_rotation.latest_hot_rotation(tmp_path, category="sentiment").get_column("name").to_list() == ["昨日连板"]
    assert eastmoney_board_rotation.latest_hot_rotation(tmp_path, category="style").get_column("name").to_list() == ["低价股"]
    assert classify_concept("昨日首板").reason == "短线事件或价格状态板块"
    assert classify_concept("Kimi概念").category == "theme"


def test_member_lookup_reads_only_exact_date_and_board(tmp_path) -> None:
    path = eastmoney_board_rotation.member_path(tmp_path, trade_date=date(2026, 9, 22))
    path.parent.mkdir(parents=True)
    pl.DataFrame({
        "trade_date": ["20260922", "20260922", "20260921"],
        "ts_code": ["BK0001.DC", "BK0002.DC", "BK0001.DC"],
        "con_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
        "name": ["平安银行", "万科A", "历史成员"],
    }).write_parquet(path)

    frame = eastmoney_board_rotation.load_hot_rotation_members(
        tmp_path, trade_date=date(2026, 9, 22), ts_code="bk0001.dc"
    )

    assert frame.to_dicts() == [{
        "trade_date": "20260922", "ts_code": "BK0001.DC", "con_code": "000001.SZ", "name": "平安银行",
    }]
