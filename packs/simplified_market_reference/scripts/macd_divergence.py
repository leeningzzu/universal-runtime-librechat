from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Signal:
    status: str
    first_index: int | None
    second_index: int | None
    reason: str


def ema(values: list[float], span: int) -> list[float]:
    alpha = 2 / (span + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def load_close(path: Path) -> list[float]:
    with path.open('r', encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    return [float(row['close']) for row in rows]


def local_lows(values: list[float]) -> list[int]:
    return [i for i in range(1, len(values)-1) if values[i] < values[i-1] and values[i] <= values[i+1]]


def detect_bottom_divergence(closes: list[float]) -> Signal:
    if len(closes) < 30:
        return Signal('NONE', None, None, 'Not enough bars')
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    dif = [a-b for a,b in zip(fast, slow)]
    lows = local_lows(closes)
    if len(lows) < 2:
        return Signal('NONE', None, None, 'Fewer than two confirmed price lows')
    first, second = lows[-2], lows[-1]
    if closes[second] < closes[first] and dif[second] > dif[first]:
        return Signal('CONFIRMED', first, second, 'Price lower low with DIF higher low')
    return Signal('NONE', first, second, 'Last two confirmed lows do not satisfy divergence rule')


def main() -> None:
    path = Path(__file__).resolve().parents[1] / 'fixtures' / 'sample_ohlcv.csv'
    signal = detect_bottom_divergence(load_close(path))
    print(signal)


if __name__ == '__main__':
    main()
