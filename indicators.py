import talib
import numpy as np
import pandas as pd
from typing import Dict, Any

def calculate_ema(prices: pd.Series, period: int) -> float:
    """EMA (Exponential Moving Average) hisoblaydi."""
    ema = talib.EMA(prices, timeperiod=period)
    return ema.iloc[-1] if not ema.empty else None

def calculate_rsi(prices: pd.Series, period: int) -> float:
    """RSI (Relative Strength Index) hisoblaydi."""
    rsi = talib.RSI(prices, timeperiod=period)
    return rsi.iloc[-1] if not rsi.empty else None

def calculate_macd(prices: pd.Series) -> Dict[str, float]:
    """MACD (Moving Average Convergence Divergence) hisoblaydi."""
    macd, macdsignal, macdhist = talib.MACD(prices, fastperiod=12, slowperiod=26, signalperiod=9)
    return {
        "macd": macd.iloc[-1] if not macd.empty else None,
        "signal": macdsignal.iloc[-1] if not macdsignal.empty else None,
        "hist": macdhist.iloc[-1] if not macdhist.empty else None
    }

def calculate_bollinger_bands(prices: pd.Series, period: int) -> Dict[str, float]:
    """Bollinger Bands hisoblaydi."""
    upper, middle, lower = talib.BBANDS(prices, timeperiod=period)
    return {
        "upper": upper.iloc[-1] if not upper.empty else None,
        "middle": middle.iloc[-1] if not middle.empty else None,
        "lower": lower.iloc[-1] if not lower.empty else None
    }

def calculate_obv(prices: pd.Series, volumes: pd.Series) -> float:
    """OBV (On Balance Volume) hisoblaydi."""
    obv = talib.OBV(prices, volumes)
    return obv.iloc[-1] if not obv.empty else None