import pandas as pd


# Legacy 보조 지표 모듈.
# 전략 엔진은 core/strategy.py의 SR/OB/FVG/트리거 로직을 사용하며,
# 여기서는 보조 계산(백테스트/분석 용도)만 유지한다.


def rsi(data, period=14, column="trade_price"):
    df = pd.DataFrame(data)
    df = df.reindex(index=df.index[::-1]).reset_index(drop=True)

    delta = df[column].diff(1).dropna()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)

    avg_gain = up.ewm(com=(period - 1), min_periods=period).mean()
    avg_loss = down.ewm(com=(period - 1), min_periods=period).mean()
    rs = avg_gain / avg_loss

    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    return rsi_series.iloc[-1]


def macd(data, n_fast=12, n_slow=26, n_signal=9):
    df = pd.DataFrame(data)
    df = df.reindex(index=df.index[::-1]).reset_index(drop=True)

    df["EMAFast"] = df["trade_price"].ewm(span=n_fast).mean()
    df["EMASlow"] = df["trade_price"].ewm(span=n_slow).mean()
    df["MACD"] = df["EMAFast"] - df["EMASlow"]
    df["MACDSignal"] = df["MACD"].ewm(span=n_signal).mean()
    df["MACDDiff"] = df["MACD"] - df["MACDSignal"]
    return df


def atr(data, period=14):
    df = pd.DataFrame(data)
    df = df.reindex(index=df.index[::-1]).reset_index(drop=True)
    prev_close = df["trade_price"].shift(1)
    tr = pd.concat(
        [
            (df["high_price"] - df["low_price"]).abs(),
            (df["high_price"] - prev_close).abs(),
            (df["low_price"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean().iloc[-1]
