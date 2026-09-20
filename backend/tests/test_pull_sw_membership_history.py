from __future__ import annotations

import json
from datetime import date

import polars as pl

import scripts.pull_sw_membership_history as puller
from app.services import rps_rotation
from app.services.sector_membership import replace_sw_membership_history


class _Response:
    def __init__(self, items: list[list[object]]) -> None:
        self._items = items

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"code": 0, "data": {"fields": puller._FIELDS.split(","), "items": self._items}}


class _Client:
    def __init__(self, pages: dict[str, list[list[list[object]]]]) -> None:
        self.pages = pages

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, _url: str, *, json: dict[str, object]) -> _Response:
        status = str(json["params"]["is_new"])
        offset = int(json["params"]["offset"])
        page = self.pages[status][offset // puller._PAGE_SIZE]
        return _Response(page)


def _row(symbol: str, sector: str, in_date: str, out_date: str | None, is_new: str) -> list[object]:
    return [
        "801010.SI",
        sector,
        "801016.SI",
        sector,
        "850111.SI",
        sector,
        symbol,
        symbol,
        in_date,
        out_date,
        is_new,
    ]


def test_to_intervals_keeps_rows_overlapping_requested_window() -> None:
    rows = [
        _row("000001.SZ", "银行", "20200101", "20230911", "N"),
        _row("000002.SZ", "房地产", "20200101", "20240101", "N"),
        _row("000003.SZ", "医药", "20260101", None, "Y"),
    ]

    intervals = puller._to_intervals(rows, start=date(2023, 9, 12), end=date(2026, 9, 12))

    assert [row["symbol"] for row in intervals] == ["000002.SZ", "000003.SZ"]
    assert all(row["kind"] == "industry" for row in intervals)
    assert all(row["membership_as_of"] == date(2023, 9, 12) for row in intervals)
    assert intervals[0]["sector"] == "房地产-房地产-房地产"
    assert intervals[0]["sw1_code"] == "801010.SI"
    assert intervals[0]["sw2_code"] == "801016.SI"
    assert intervals[0]["sw3_code"] == "850111.SI"


def test_to_intervals_keeps_each_row_hierarchy() -> None:
    first = _row("000001.SZ", "银行", "20230101", None, "Y")
    second = _row("000002.SZ", "半导体", "20230101", None, "Y")
    second[:6] = ["801080.SI", "电子", "801081.SI", "半导体", "850810.SI", "半导体设备"]

    intervals = puller._to_intervals([first, second], start=date(2023, 9, 12), end=date(2026, 9, 12))
    by_symbol = {row["symbol"]: row for row in intervals}

    assert by_symbol["000001.SZ"]["sw2_name"] == "银行"
    assert by_symbol["000002.SZ"]["sw1_name"] == "电子"
    assert by_symbol["000002.SZ"]["sw2_name"] == "半导体"
    assert by_symbol["000002.SZ"]["sw3_name"] == "半导体设备"


def test_pull_paginates_and_writes_dedicated_store(tmp_path, monkeypatch) -> None:
    pages = {"Y": [[_row("000001.SZ", "银行", "20200101", None, "Y")]], "N": [[]]}
    monkeypatch.setattr(puller.httpx, "Client", lambda **_kwargs: _Client(pages))

    result = puller.pull(
        start=date(2023, 9, 12),
        end=date(2026, 9, 12),
        token="token",
        api_url="https://gateway.example",
        data_dir=tmp_path,
    )

    stored = pl.read_parquet(tmp_path / "sector_membership_history" / "sw_memberships.parquet")
    metadata = json.loads(
        (tmp_path / "sector_membership_history" / "sw_memberships_metadata.json").read_text(encoding="utf-8")
    )
    assert result["selected_interval_rows"] == 1
    assert stored.select("symbol").to_series().to_list() == ["000001.SZ"]
    assert set(("sw1_code", "sw1_name", "sw2_code", "sw2_name", "sw3_code", "sw3_name")).issubset(stored.columns)
    assert metadata["api_url"] == "https://gateway.example"


def test_industry_loader_prefers_sw_for_current_requests_and_preserves_levels(tmp_path) -> None:
    rows = pl.DataFrame([
        {
            "symbol": "000001.SZ",
            "kind": "industry",
            "sector": "金融-银行-股份制银行",
            "effective_from": date(2023, 1, 1),
            "effective_to": None,
            "membership_as_of": date(2023, 9, 12),
            "source": "tushare_sw_index_member_all",
            "taxonomy_version": "SW2021",
        }
    ], schema={
        "symbol": pl.Utf8,
        "kind": pl.Utf8,
        "sector": pl.Utf8,
        "effective_from": pl.Date,
        "effective_to": pl.Date,
        "membership_as_of": pl.Date,
        "source": pl.Utf8,
        "taxonomy_version": pl.Utf8,
    })
    replace_sw_membership_history(tmp_path, rows)

    class _Store:
        data_dir = tmp_path

    class _Repo:
        _enriched_history_cache = pl.DataFrame({"date": [date(2026, 9, 11)]})
        store = _Store()

    rps_rotation._map_cache.clear()
    rps_rotation._map_ts.clear()
    rps_rotation._map_source.clear()
    frame, count = rps_rotation._load_concept_map_df(_Repo(), "industry")

    assert count == 1
    assert rps_rotation.membership_source_for_kind("industry") == "tushare_sw_index_member_all"
    assert frame.to_dicts() == [{
        "_sym_up": "000001.SZ",
        "industry": "金融-银行-股份制银行",
        "sw1_code": None,
        "sw1_name": "金融",
        "sw2_code": None,
        "sw2_name": "银行",
        "sw3_code": None,
        "sw3_name": "股份制银行",
    }]
    assert rps_rotation._normalized_map(frame, "industry", 2).get_column("industry").to_list() == ["银行"]


def test_strict_industry_level_never_promotes_sw1_only_records() -> None:
    frame = pl.DataFrame({"_sym_up": ["000001.SZ"], "industry": ["金融"]})

    assert rps_rotation._normalized_map(
        frame, "industry", 2, strict_industry_level=True
    ).is_empty()
    assert rps_rotation._normalized_map(
        frame, "industry", 3, strict_industry_level=True
    ).is_empty()


def test_industry_codes_are_stable_keys_and_names_remain_display_fields() -> None:
    frame = pl.DataFrame({
        "_sym_up": ["000001.SZ", "000002.SZ"],
        "industry": ["电子-旧名称-设备", "电子-新名称-设备"],
        "sw2_code": ["801081.SI", "801081.SI"],
        "sw2_name": ["旧名称", "新名称"],
    })

    normalized = rps_rotation._normalized_map(frame, "industry", 2, strict_industry_level=True)

    assert normalized.get_column("industry").unique().to_list() == ["801081.SI"]
    assert set(normalized.get_column("_sector_display_name").to_list()) == {"旧名称", "新名称"}
