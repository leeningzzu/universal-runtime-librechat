import importlib.util
import sys
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / 'packs' / 'simplified_market_reference' / 'scripts' / 'macd_divergence.py'
    spec = importlib.util.spec_from_file_location('macd_divergence', path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_market_fixture_runs():
    module = load_module()
    csv_path = Path(__file__).resolve().parents[1] / 'packs' / 'simplified_market_reference' / 'fixtures' / 'sample_ohlcv.csv'
    closes = module.load_close(csv_path)
    result = module.detect_bottom_divergence(closes)
    assert result.status in {'CONFIRMED', 'NONE'}
    assert result.reason
