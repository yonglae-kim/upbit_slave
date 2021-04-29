import numpy as np
import pandas as pd


# data : candles data
# result = apis.get_candles_day(list_krw_market[0], 200)
# rsi = strategy.strategy.rsi(result)
def rsi(data, period=14, column='trade_price'):
    df = pd.DataFrame(data)
    df = df.reindex(index=df.index[::-1]).reset_index()

    delta = df[column].diff(1)
    delta = delta.dropna()

    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0

    AVG_Gain = up.ewm(com=(period - 1), min_periods=period).mean()
    AVG_Loss = down.abs().ewm(com=(period - 1), min_periods=period).mean()
    RS = AVG_Gain / AVG_Loss

    rsi = 100.0 - (100.0 / (1.0 + RS))

    return rsi.iloc[-1]


def stoch_rsi(data, p1=14, k1=3, d1=3):
    df = pd.DataFrame(data)

    series = pd.Series(df['trade_price'].values)

    period = p1
    smoothK = k1
    smoothD = d1

    delta = series.diff().dropna()
    ups = delta * 0
    downs = ups.copy()
    ups[delta > 0] = delta[delta > 0]
    downs[delta < 0] = -delta[delta < 0]
    ups[ups.index[period - 1]] = np.mean(ups[:period])
    ups = ups.drop(ups.index[:(period - 1)])
    downs[downs.index[period - 1]] = np.mean(downs[:period])
    downs = downs.drop(downs.index[:(period - 1)])
    rs = ups.ewm(com=period - 1, min_periods=0, adjust=False, ignore_na=False).mean() / \
         downs.ewm(com=period - 1, min_periods=0, adjust=False, ignore_na=False).mean()
    rsi = 100 - 100 / (1 + rs)

    stochrsi = (rsi - rsi.rolling(period).min()) / (rsi.rolling(period).max() - rsi.rolling(period).min())
    stochrsi_k = stochrsi.rolling(smoothK).mean()
    stochrsi_d = stochrsi_k.rolling(smoothD).mean()
    return {'stochrsi': stochrsi.iloc[-1] * 100, 'stochrsi_k': stochrsi_k.iloc[-1] * 100,
            'stochrsi_d': stochrsi_d.iloc[-1] * 100, }


# 볼린저밴드
def bollinger_bands(data, day=20):
    df = pd.DataFrame(data)

    df = df['trade_price'].iloc[::-1]

    unit = 2
    band1 = unit * np.std(df[len(df) - day:len(df)])
    bb_center = np.mean(df[len(df) - day:len(df)])
    band_high = bb_center + band1
    band_low = bb_center - band1
    return {'high': round(band_high, 2), 'low': round(band_low, 2), }


# 일목균형표
def ichimoku_cloud(data):
    df = pd.DataFrame(data)
    df = df.iloc[::-1]

    high_prices = df['high_price']
    close_prices = df['trade_price']
    low_prices = df['low_price']

    nine_period_high = df['high_price'].rolling(window=9).max()
    nine_period_low = df['low_price'].rolling(window=9).min()
    df['tenkan_sen'] = (nine_period_high + nine_period_low) / 2

    period26_high = high_prices.rolling(window=26).max()
    period26_low = low_prices.rolling(window=26).min()
    df['kijun_sen'] = (period26_high + period26_low) / 2

    df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)

    period52_high = high_prices.rolling(window=52).max()
    period52_low = low_prices.rolling(window=52).min()
    df['senkou_span_b'] = ((period52_high + period52_low) / 2).shift(26)

    df['chikou_span'] = close_prices.shift(-26)

    return {
        'tenkan_sen': df['tenkan_sen'].iloc[-1],  # 전환선
        'kijun_sen': df['kijun_sen'].iloc[-1],  # 기준선
        'chikou_span': df['chikou_span'].iloc[-27],  # 후행스팬
        'senkou_span_a': df['senkou_span_a'].iloc[-1],  # 선행스팬1
        'senkou_span_b': df['senkou_span_b'].iloc[-1],  # 선행스팬2
    }


def macd(data, n_fast=12, n_slow=26, n_signal=9):
    df = pd.DataFrame(data)
    df = df.reindex(index=df.index[::-1]).reset_index()

    df["EMAFast"] = df["trade_price"].ewm(span=n_fast).mean()
    df["EMASlow"] = df["trade_price"].ewm(span=n_slow).mean()
    df["MACD"] = df["EMAFast"] - df["EMASlow"]
    df["MACDSignal"] = df["MACD"].ewm(span=n_signal).mean()
    df["MACDDiff"] = df["MACD"] - df["MACDSignal"]
    return df
