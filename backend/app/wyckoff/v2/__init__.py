"""Independent, event-driven Wyckoff engine.

This package deliberately does not import the legacy observation-only
``wyckoff_structure`` module.  It can be evaluated beside it, and only uses
closed OHLCV bars supplied by the strategy service.
"""

from app.wyckoff.v2.backtest import (
    run_event_backtest,
    run_event_backtest_frames,
    run_parameter_grid,
)
from app.wyckoff.v2.config import WyckoffV2Config
from app.wyckoff.v2.engine import analyze_wyckoff_v2
from app.wyckoff.v2.models import WyckoffV2Analysis

__all__ = ["WyckoffV2Analysis", "WyckoffV2Config", "analyze_wyckoff_v2", "run_event_backtest", "run_event_backtest_frames", "run_parameter_grid"]
