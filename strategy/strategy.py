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


def bollinger_bands(data, day=20):
    df = pd.DataFrame(data)

    df = df['trade_price'].iloc[::-1]

    unit = 2
    band1 = unit * np.std(df[len(df) - day:len(df)])
    bb_center = np.mean(df[len(df) - day:len(df)])
    band_high = bb_center + band1
    band_low = bb_center - band1
    return {'high': round(band_high, 2), 'low': round(band_low, 2), }
