from pandas import DataFrame

from freqtrade.strategy import IStrategy


class HomelabBtcTrend(IStrategy):
    """Conservative starter strategy for BTC/USD dry-run validation."""

    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False
    startup_candle_count = 200
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.04,
        "240": 0.02,
        "720": 0.0,
    }

    stoploss = -0.08
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True
    use_exit_signal = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ema_fast"] = close.ewm(span=20, adjust=False).mean()
        dataframe["ema_slow"] = close.ewm(span=50, adjust=False).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rs = gain / loss.replace(0, 0.00000001)
        dataframe["rsi"] = 100 - (100 / (1 + rs))

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0

        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["close"] > dataframe["ema_fast"])
                & (dataframe["rsi"] > 50)
                & (dataframe["rsi"] < 70)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0

        dataframe.loc[
            (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                | (dataframe["rsi"] > 78)
            )
            & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1

        return dataframe
