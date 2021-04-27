import apis
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
