from __future__ import annotations

import json
from types import SimpleNamespace

from app.services import tushare_metadata as metadata


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "code": 0,
            "data": {
                "fields": ["ts_code", "industry"],
                "items": [["000001.SZ", "银行"], ["600000.SH", "银行"], ["bad", "忽略"]],
            },
        }


def test_load_tushare_sector_map_fetches_normalizes_and_caches(tmp_path, monkeypatch):
    called: dict[str, object] = {}

    def _post(url, *args, **kwargs):
        called["url"] = url
        return _Response()

    monkeypatch.setattr(metadata.secrets_store, "get_tushare_token", lambda: "token")
    monkeypatch.setattr(metadata, "settings", SimpleNamespace(tushare_api_url="https://gateway.example/"))
    monkeypatch.setattr(metadata.httpx, "post", _post)

    result = metadata.load_tushare_sector_map(tmp_path, now=100.0)

    assert result.source == "tushare_live"
    assert result.mapping == {"000001.SZ": "银行", "600000.SH": "银行"}
    assert called["url"] == "https://gateway.example"
    cache = json.loads((tmp_path / "metadata" / "tushare_sector_map.json").read_text(encoding="utf-8"))
    assert cache["mapping"] == result.mapping


def test_load_tushare_sector_map_uses_fresh_cache_without_token(tmp_path, monkeypatch):
    path = tmp_path / "metadata"
    path.mkdir()
    (path / "tushare_sector_map.json").write_text(
        json.dumps({"cached_at": 100.0, "mapping": {"000001.SZ": "银行"}}), encoding="utf-8"
    )
    monkeypatch.setattr(metadata.secrets_store, "get_tushare_token", lambda: "")

    result = metadata.load_tushare_sector_map(tmp_path, now=101.0)

    assert result.source == "tushare_cache_fresh"
    assert result.mapping == {"000001.SZ": "银行"}
