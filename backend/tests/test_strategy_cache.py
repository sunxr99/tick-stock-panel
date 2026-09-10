from __future__ import annotations

from app.services import strategy_cache


def _result(*symbols: str) -> dict:
    return {
        "total": len(symbols),
        "as_of": "2026-07-20",
        "rows": [{"symbol": symbol, "close": index + 1.0} for index, symbol in enumerate(symbols)],
    }


def test_same_day_partial_writes_merge_strategy_results(tmp_path):
    strategy_cache.write_cache(tmp_path, "2026-07-20", {"strategy_a": _result("000001.SZ")})
    strategy_cache.write_cache(tmp_path, "2026-07-20", {"strategy_b": _result("600000.SH")})

    cached = strategy_cache.read_cache(tmp_path)

    assert set(cached["results"]) == {"strategy_a", "strategy_b"}
    assert cached["results"]["strategy_a"]["rows"][0]["symbol"] == "000001.SZ"
    assert cached["results"]["strategy_b"]["rows"][0]["symbol"] == "600000.SH"


def test_same_day_update_replaces_only_target_strategy_and_keeps_ever_rows(tmp_path):
    strategy_cache.write_cache(tmp_path, "2026-07-20", {
        "strategy_a": _result("000001.SZ"),
        "strategy_b": _result("600000.SH"),
    })
    strategy_cache.write_cache(tmp_path, "2026-07-20", {"strategy_a": _result("000002.SZ")})

    cached = strategy_cache.read_cache(tmp_path)

    assert [row["symbol"] for row in cached["results"]["strategy_a"]["rows"]] == ["000002.SZ"]
    assert [row["symbol"] for row in cached["results"]["strategy_b"]["rows"]] == ["600000.SH"]
    assert set(cached["today_ever_rows"]["strategy_a"]) == {"000001.SZ", "000002.SZ"}


def test_new_date_resets_results_and_ever_rows(tmp_path):
    strategy_cache.write_cache(tmp_path, "2026-07-20", {"strategy_a": _result("000001.SZ")})
    next_day = _result("600000.SH")
    next_day["as_of"] = "2026-07-21"

    strategy_cache.write_cache(tmp_path, "2026-07-21", {"strategy_b": next_day})
    cached = strategy_cache.read_cache(tmp_path)

    assert cached["as_of"] == "2026-07-21"
    assert set(cached["results"]) == {"strategy_b"}
    assert set(cached["today_ever_rows"]) == {"strategy_b"}


def test_cache_compacts_legacy_per_row_wyckoff_snapshot(tmp_path):
    snapshot = {"layer1_symbols": ["000001.SZ"], "trading_ranges": {"000001.SZ": {"low": 1.0}}}
    strategy_cache.write_cache(tmp_path, "2026-07-20", {
        "wyckoff_funnel": {
            "total": 2,
            "as_of": "2026-07-20",
            "rows": [
                {"symbol": "000001.SZ", "wyckoff_snapshot": snapshot},
                {"symbol": "000002.SZ", "wyckoff_snapshot": snapshot},
            ],
        },
    })

    cached = strategy_cache.read_cache(tmp_path)
    result = cached["results"]["wyckoff_funnel"]

    assert all("wyckoff_snapshot" not in row for row in result["rows"])
    assert result["evidence"]["wyckoff_snapshot"] == snapshot
    ever_rows = cached["today_ever_rows"]["wyckoff_funnel"].values()
    assert all("wyckoff_snapshot" not in row for row in ever_rows)


def test_read_cache_skips_file_over_size_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(strategy_cache, "_MAX_CACHE_BYTES", 10)
    path = tmp_path / "user_data" / "strategy_cache.json"
    path.parent.mkdir()
    path.write_text("{" + "x" * 10 + "}", encoding="utf-8")

    assert strategy_cache.read_cache(tmp_path) is None
