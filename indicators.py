echo "import numpy as np
import pandas as pd
from typing import Dict, Any

def calculate_ema(prices: pd.Series, period: int) -> float:
    '''EMA (Exponential Moving Average) - TA-Lib siz'''
    return prices.ewm(span=period).mean().iloc[-1]

def calculate_rsi(prices: pd.Series, period: int) -> float:
    '''RSI (Relative Strength Index) - TA-Lib siz'''
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def calculate_macd(prices: pd.Series) -> Dict[str, float]:
    '''MACD - TA-Lib siz'''
    exp1 = prices.ewm(span=12).mean()
    exp2 = prices.ewm(span=26).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9).mean()
    hist = macd - signal
    return {
        'macd': macd.iloc[-1],
        'signal': signal.iloc[-1], 
        'hist': hist.iloc[-1]
    }

def calculate_bollinger_bands(prices: pd.Series, period: int) -> Dict[str, float]:
    '''Bollinger Bands - TA-Lib siz'''
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + (std * 2)
    lower = sma - (std * 2)
    return {
        'upper': upper.iloc[-1],
        'middle': sma.iloc[-1],
        'lower': lower.iloc[-1]
    }

def calculate_obv(prices: pd.Series, volumes: pd.Series) -> float:
    '''OBV (On Balance Volume) - TA-Lib siz'''
    obv = (np.sign(prices.diff()) * volumes).fillna(0).cumsum()
    return obv.iloc[-1]" > indicators.py