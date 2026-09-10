from __future__ import annotations

from types import SimpleNamespace

from app.api import strategy as strategy_api


def _request(tmp_path):
    repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(repo=repo)))


def test_wyckoff_chart_reads_strategy_level_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(strategy_api.strategy_cache, "read_cache", lambda *_args: {
        "as_of": "2026-09-06",
        "results": {
            "wyckoff_funnel": {
                "as_of": "2026-09-06",
                "rows": [{
                    "symbol": "000001.SZ",
                    "wyckoff_channel": "trend",
                    "wyckoff_stage": "Markup",
                    "wyckoff_trigger": "sos",
                }],
                "evidence": {
                    "wyckoff_snapshot": {
                        "layer1_symbols": ["000001.SZ"],
                        "layer2_symbols": ["000001.SZ"],
                        "layer3_symbols": ["000001.SZ"],
                        "top_sectors": ["测试行业"],
                        "trading_ranges": {"000001.SZ": {"low": 10.0}},
                        "triggers": {"sos": [{"symbol": "000001.SZ", "score": 1.0}]},
                    },
                },
            },
        },
    })

    payload = strategy_api.get_wyckoff_chart_data("000001.SZ", _request(tmp_path))

    assert payload["status"] == "ok"
    assert payload["layers"] == {"l1": True, "l2": True, "l3": True}
    assert payload["trading_range"] == {"low": 10.0}
    assert payload["triggers"]["sos"] == {"symbol": "000001.SZ", "score": 1.0}
