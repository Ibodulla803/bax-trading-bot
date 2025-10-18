# trading_logic.py
import asyncio
import logging
import datetime
import random
import numpy as np
import pandas as pd
import pytz
import uuid
import re
import talib
import math
import aiohttp
import hashlib
import time
import json
import traceback
import aiohttp
from gemini_ai import get_ai_approval
from typing import Dict, Any, List, Optional, Tuple
from telegram.ext import ContextTypes, CallbackContext
from config import get_asset_name_by_epic
from capital_api import CapitalComAPI
from db import InMemoryDB
from config import (
    ACTIVE_INSTRUMENTS, stop_event, CHAT_ID,
GEMINI_API_KEY
)
from indicators import calculate_ema, calculate_rsi, calculate_macd, calculate_bollinger_bands

from config import TRADING_SETTINGS
# Loggerni sozlash
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # ✅ DEBUG darajasini qo'llash



# Vaqtincha xabarlar orasidagi vaqtni saqlash uchun o'zgaruvchi
last_none_message_time = datetime.datetime.now()

# Global o'zgaruvchilar
MIN_PRICE_CHANGE = 0.5  # % 0.5 dan katta o'zgarishlarni ko'rsatish
stop_event = asyncio.Event()
last_prices = {}
global_db_instance = None
global_api_instance = None
ai_trailing_positions = {}

# trading_logic.py - bosh qismiga (importlardan keyin)

# Yordamchi funksiyalar

def get_macd_status(macd, macd_signal):
    """
    MACD va signal chizig‘ini tahlil qilib trend holatini qaytaradi.
    """
    if macd is None or macd_signal is None:
        return "UNKNOWN"

    if macd > macd_signal:
        return "BULLISH"
    elif macd < macd_signal:
        return "BEARISH"
    else:
        return "NEUTRAL"

def get_trend_status(indicators: dict) -> str:
    """
    EMA va MACD asosida trend holatini aniqlaydi.
    """
    ema = indicators.get("ema20")
    macd = indicators.get("macd")
    macd_signal = indicators.get("macd_signal")

    # MACD va EMA mavjud bo‘lishini tekshiramiz
    if ema is None:
        return "unknown"
    if macd is None or macd_signal is None:
        return "neutral"

    # MACD chizig‘i signal chizig‘idan yuqorida bo‘lsa — bullish trend
    if macd > macd_signal:
        return "uptrend"
    elif macd < macd_signal:
        return "downtrend"
    else:
        return "neutral"

def get_rsi_status(rsi: float) -> str:
    """RSI qiymatiga ko‘ra holatni aniqlaydi"""
    if rsi is None:
        return "unknown"
    if rsi > 70:
        return "overbought"
    elif rsi < 30:
        return "oversold"
    else:
        return "neutral"

def calculate_spread(prices: Dict) -> float:
    """Spread foizini hisoblash"""
    buy = prices.get('buy', 0)
    sell = prices.get('sell', 0)
    return ((sell - buy) / buy * 100) if buy > 0 else 0

def get_bollinger_status(prices: Dict, indicators: Dict) -> str:
    """Bollinger Bands holati"""
    current_price = prices.get('buy', 0)
    upper = indicators.get('bb_upper', 0)
    lower = indicators.get('bb_lower', 0)
    
    if current_price > upper: return "ABOVE UPPER BAND ⬆️"
    if current_price < lower: return "BELOW LOWER BAND ⬇️"
    return "WITHIN BANDS ✅"

def get_volatility_status(asset: str, indicators: Dict) -> str:
    """Volatillik holati"""
    # Soddalashtirilgan volatillik hisobi
    return "MEDIUM"  # Haqiqiy loyihada batafsil hisoblash kerak

def get_signal_strength(asset: str, signal: str, indicators: Dict) -> str:
    """Signal kuchliligi"""
    # Signal hisoblash mantiqiga asoslangan
    return "STRONG" if indicators.get('rsi', 50) < 35 or indicators.get('rsi', 50) > 65 else "MODERATE"

def get_support_resistance_status(indicators: Dict) -> str:
    """Support/Resistance holati"""
    return "KEY SUPPORT NEARBY" if indicators.get('rsi', 50) < 35 else "KEY RESISTANCE NEARBY" if indicators.get('rsi', 50) > 65 else "NEUTRAL ZONE"

def set_global_instances(db, api):
    """Global DB va API instancelarini sozlash"""
    global global_db_instance, global_api_instance
    global_db_instance = db
    global_api_instance = api
    logger.info("✅ Global DB va API instancelari sozlandi.")


def get_global_instances():
    """Global instancelarni olish"""
    return global_db_instance, global_api_instance


def get_tashkent_time() -> datetime.datetime:
    """O'zbekiston vaqtini qaytaradi (GMT+5)."""
    tz = pytz.timezone('Asia/Tashkent')
    return datetime.datetime.now(tz)


def is_market_open(asset: str) -> bool:
    """
    Toshkent vaqti bo'yicha bozor ochiq vaqtlarini tekshiradi.
    """
    # Kriptovalyutalar doim ochiq
    cryptos = ["Bitcoin", "Ethereum"]
    if asset in cryptos:
        return True

    # Qolgan aktivlar uchun mantiqingiz o'zgarishsiz qoladi
    now = datetime.datetime.now(pytz.timezone('Asia/Tashkent'))
    current_time = now.time()
    current_day = now.weekday()  # 0-6: Dushanba-Yakshanba
    
    # Aksiyalar (Stocks)
    stocks = ["Tesla", "Apple", "Nvidia", "Coca-Cola"]
    if asset in stocks:
        if current_day == 0:  # Dushanba
            return current_time >= datetime.time(13, 0) and current_time < datetime.time(23, 59, 59)
        elif 1 <= current_day <= 4:  # Seshanba-Juma
            return (current_time >= datetime.time(0, 0) and current_time < datetime.time(5, 0)) or \
                   (current_time >= datetime.time(13, 0) and current_time < datetime.time(23, 59, 59))
        elif current_day == 5:  # Shanba
            return current_time >= datetime.time(0, 0) and current_time < datetime.time(2, 0)
        return False  # Yakshanba yopiq

    # Forex va xom ashyolar
    forex_commodities = ["Gold", "Crude Oil", "Natural Gas", "USD/JPY", "EUR/USD"]
    if asset in forex_commodities:
        if current_day == 0:  # Dushanba
            return current_time >= datetime.time(3, 0) and current_time < datetime.time(23, 59, 59)
        elif 1 <= current_day <= 4:  # Seshanba-Juma
            return (current_time >= datetime.time(0, 0) and current_time < datetime.time(2, 0)) or \
                   (current_time >= datetime.time(3, 0) and current_time < datetime.time(23, 59, 59))
        elif current_day == 5:  # Shanba
            return current_time >= datetime.time(0, 0) and current_time < datetime.time(2, 0)
        return False # Yakshanba yopiq
    
    # Noma'lum aktivlar uchun default - ochiq
    return True

    
    # Forex va xom ashyolar
    forex_commodities = ["Gold", "Crude Oil", "Natural Gas", "USD/JPY", "EUR/USD"]
    if asset in forex_commodities:
        if current_day == 0:  # Dushanba
            return current_time >= datetime.time(3, 0) and current_time < datetime.time(23, 59, 59)
        elif 1 <= current_day <= 4:  # Seshanba-Juma
            return (current_time >= datetime.time(0, 0) and current_time < datetime.time(2, 0)) or \
                   (current_time >= datetime.time(3, 0) and current_time < datetime.time(23, 59, 59))
        elif current_day == 5:  # Shanba
            return current_time >= datetime.time(0, 0) and current_time < datetime.time(2, 0)
        return False # Yakshanba yopiq
    
    # Noma'lum aktivlar uchun default - ochiq
    return True



async def start_trading_loops(context: CallbackContext):
    """Bot ishga tushganda avtomatik savdo tsikllarini ishga tushirish"""
    try:
        logger.info("🚀 Bot savdo tsikllarini ishga tushirmoqda...")
        
        # Bot_data yordamida ma'lumotlarni saqlaymiz va olamiz
        bot_data = context.application.bot_data
        
        # CHAT_ID uchun lug'at mavjudligini tekshiramiz va agar yo'q bo'lsa, uni yaratamiz
        user_data = bot_data.setdefault(CHAT_ID, {})
        
        user_data['db'] = InMemoryDB(user_id=CHAT_ID)
        settings = await user_data['db'].get_settings()
        
        is_demo = settings.get("demo_account_status", False)
        is_real = settings.get("real_account_status", False)
        is_auto_trading_enabled = settings.get("auto_trading_enabled", True)

        if is_demo or is_real:
            api_key = CAPITAL_COM_DEMO_API_KEY if is_demo else CAPITAL_COM_REAL_API_KEY
            api_pass = CAPITAL_COM_DEMO_API_KEY_PASSWORD if is_demo else CAPITAL_COM_REAL_API_KEY_PASSWORD
            
            # ✅ CapitalComAPI instance yaratish
            capital_api = CapitalComAPI(
                username=CAPITAL_COM_USERNAME,
                password=CAPITAL_COM_PASSWORD,
                demo_api_key=api_key,
                demo_api_key_password=api_pass,
                account_type="demo" if is_demo else "real"
            )
            
            login_result = await capital_api.login()
            
            if login_result.get("success"):
                # ✅ GLOBAL INSTANCELARNI SOZLASH (MUHIM QISMI)
                logger.info("✅ Global instancelar sozlanmoqda...")
                set_global_instances(user_data['db'], capital_api)
                logger.info("✅ Global instancelar muvaffaqiyatli sozlandi")
                
                # Context uchun user_data ni to'ldirish
                context.user_data = user_data
                
                await refresh_positions(context)

                if is_auto_trading_enabled:
                    asyncio.create_task(trading_logic_loop(context))
                    asyncio.create_task(refresh_positions_loop(context))
                    asyncio.create_task(close_profitable_positions_loop(context))
                    asyncio.create_task(check_trailing_stop_loop(context))
                    asyncio.create_task(check_stop_loss_loop(context))  
                    

                    logger.info("Savdo looplari muvaffaqiyatli ishga tushirildi.")

                    await context.bot.send_message(
                        chat_id=CHAT_ID,
                        text="✅ Avtomatik savdo muvaffaqiyatli ishga tushirildi"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=CHAT_ID,
                        text="⏸️ Avtomatik savdo sozlamalarda o'chirilgan. Ishga tushirilmadi."
                    )
            else:
                logger.error(f"❌ API ga ulanishda xato: {login_result.get('message')}")
        else:
            logger.info("ℹ️ Hisob turi tanlanmagan")

    except Exception as e:
        logger.error(f"Bot ishga tushirishda xato: {e}")
async def get_prices_with_retry(api, epic: str, retries: int = 3) -> Optional[Dict]:
    """Qayta urinishlar bilan narxlarni olish"""
    for attempt in range(retries):
        try:
            prices = await api.get_prices(epic)
            if prices and prices.get("buy") and prices.get("sell"):
                # Narxlarni float ga o'tkazish
                return {
                    "buy": float(prices["buy"]),
                    "sell": float(prices["sell"]),
                    "timestamp": datetime.datetime.now().isoformat()
                }
            await asyncio.sleep(1)  # Qisqa kutish
        except Exception as e:
            logger.warning(f"Narxlarni olishda xato ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return None

async def send_trading_status(context: ContextTypes.DEFAULT_TYPE, message: str, level: str = "info"):
    """
    Savdo holati haqida Telegramga xabar yuborish.
    level: "info", "warning", "error", "success"
    """
    try:
        db: InMemoryDB = context.user_data['db']
        settings = await db.get_settings()
        chat_id = settings.get("chat_id")
        
        if not chat_id and CHAT_ID:
            chat_id = CHAT_ID
        
        if not chat_id:
            logger.warning("Telegram xabarnomasi uchun chat_id topilmadi.")
            return

        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅"
        }
        
        emoji = emoji_map.get(level, "ℹ️")
        formatted_message = f"{emoji} {message}"
        
        await context.bot.send_message(chat_id=chat_id, text=formatted_message)
        
    except Exception as e:
        logger.error(f"Xabar yuborishda xato: {e}")


async def calculate_test_signals(api, epic: str, settings: Dict) -> Optional[str]:
    """
    TEST rejimi - har doim BUY qaytaradi (testing uchun)
    """
    logger.info(f"[{epic}] TEST rejimi: Har doim BUY signal")
    return "BUY"

async def calculate_weak_signals(api, epic: str, settings: Dict) -> Optional[str]:
    """Zaif signal hisoblash (faqat RSI asosida, nisbat bilan)"""
    try:
        # Narxlarni olish
        prices_data = None
        resolutions_to_try = ["HOUR", "DAY"]

        for resolution in resolutions_to_try:
            prices_data = await api.get_historical_prices(epic, resolution, 50)
            if prices_data and len(prices_data) >= 14:
                logger.debug(f"[{epic}] WEAK: {resolution} resolutionda yetarli ma'lumot topildi: {len(prices_data)} ta")
                break
            else:
                if prices_data:
                    logger.debug(f"[{epic}] WEAK: {resolution} resolutionda {len(prices_data)} ta ma'lumot topildi, lekin 14 tadan kam")
                else:
                    logger.debug(f"[{epic}] WEAK: {resolution} resolutionda ma'lumot topilmadi")

        if not prices_data or len(prices_data) < 14:
            logger.debug(f"[{epic}] WEAK: Yetarli tarixiy ma'lumot topilmadi")
            return None

        # Ma'lumotlarni to‘g‘ri qayta ishlash
        closes = []
        for price in prices_data:
            if isinstance(price, dict):
                close_price = None
                if "closePrice" in price and isinstance(price["closePrice"], dict):
                    close_price = price["closePrice"].get("bid")
                elif "openPrice" in price and isinstance(price["openPrice"], dict):
                    close_price = price["openPrice"].get("bid")
                elif "bid" in price and "ask" in price:
                    close_price = (float(price["bid"]) + float(price["ask"])) / 2

                if close_price is not None:
                    closes.append(float(close_price))

        if len(closes) < 14:
            logger.debug(f"[{epic}] WEAK: Yetarli yopilish narxlari topilmadi ({len(closes)} ta)")
            return None

        # Pandas Series yaratish
        closes_series = pd.Series(closes)

        # RSI hisoblash
        rsi_values = talib.RSI(closes_series, timeperiod=14)
        if len(rsi_values) == 0:
            logger.debug(f"[{epic}] WEAK: RSI qiymatlari topilmadi")
            return None

        rsi = rsi_values.iloc[-1]

        # Nisbati log qilish (faqat RSI -> 1 indikator)
        buy_signals = 0
        sell_signals = 0
        max_possible = 1

        if rsi < settings.get("rsi_buy_level", 35):
            buy_signals += 1
        elif rsi > settings.get("rsi_sell_level", 65):
            sell_signals += 1

        signal_ratio = max(buy_signals, sell_signals) / max_possible
        logger.info(f"[{epic}] WEAK: Signal nisbati: {signal_ratio:.2f} ({buy_signals}/{max_possible} BUY, {sell_signals}/{max_possible} SELL)")

        # Qaror
        if buy_signals == 1:
            logger.info(f"[{epic}] WEAK: BUY signal qabul qilindi!")
            return "BUY"
        elif sell_signals == 1:
            logger.info(f"[{epic}] WEAK: SELL signal qabul qilindi!")
            return "SELL"

        logger.debug(f"[{epic}] WEAK: Signal etarli emas")
        return None

    except Exception as e:
        logger.error(f"Weak signal hisoblashda xato: {e}")

    return None


async def calculate_strong_signals(api, epic: str, settings: Dict) -> Optional[str]:
    """
    Kuchli signal hisoblash (bir nechta resolutionda ma'lumot olish bilan)
    """
    try:
        prices_data = None
        resolutions_to_try = ["HOUR", "HOUR_4", "DAY"]

        for resolution in resolutions_to_try:
            # ✅ API'dan tarixiy ma'lumotni olamiz
            prices_data = await api.get_historical_prices(epic, resolution, 200)
            if prices_data and len(prices_data) >= 50:
                logger.debug(f"[{epic}] STRONG: {resolution} resolutionda yetarli ma'lumot topildi: {len(prices_data)} ta")
                break
            else:
                logger.debug(f"[{epic}] STRONG: {resolution} resolutionda ma'lumot yetarli emas")
        
        if not prices_data or len(prices_data) < 50:
            logger.debug(f"[{epic}] STRONG: Hech qanday resolutionda yetarli tarixiy ma'lumot topilmadi")
            return None

        # ✅ Ma'lumotlarni Pandas DataFrame'ga aylantiramiz
        df = pd.DataFrame(prices_data)
        
        # Narxlar ustunini yaratamiz
        if 'bid' in df.columns:
            closes = (df['bid'] + df['ask']) / 2
        elif 'closePrice' in df.columns:
            closes = df['closePrice'].apply(lambda x: x.get('bid'))
        else:
            return None

        closes_series = pd.Series(closes)
        
        # ✅ Indikatorlarni hisoblash uchun yordamchi funksiyadan foydalanamiz
        rsi_val = calculate_rsi(closes_series, 14)
        ema_20_val = calculate_ema(closes_series, 20)
        ema_50_val = calculate_ema(closes_series, 50)
        macd_vals = calculate_macd(closes_series)
        bollinger_vals = calculate_bollinger_bands(closes_series, 20)
        
        # Agar qandaydir indikator hisoblanmasa, signal yo'q deb hisoblaymiz
        if any(v is None for v in [rsi_val, ema_20_val, ema_50_val, macd_vals, bollinger_vals]):
            logger.debug(f"[{epic}] STRONG: Indikator ma'lumotlari to'liq emas.")
            return None

        buy_signals = 0
        sell_signals = 0
        max_possible = 5 # RSI, EMA, MACD, Bollinger Bands

        # ✅ 1. RSI
        if rsi_val < settings.get("rsi_buy_level", 35):
            buy_signals += 1
        elif rsi_val > settings.get("rsi_sell_level", 65):
            sell_signals += 1

        # ✅ 2. EMA kesishmasi
        if ema_20_val > ema_50_val:
            buy_signals += 1
        elif ema_20_val < ema_50_val:
            sell_signals += 1
            
        # ✅ 3. MACD kesishmasi
        if macd_vals['hist'] > 0:
            buy_signals += 1
        elif macd_vals['hist'] < 0:
            sell_signals += 1

        # ✅ 4. Bollinger Bands
        current_price = closes_series.iloc[-1]
        if current_price < bollinger_vals['lower']:
            buy_signals += 1
        elif current_price > bollinger_vals['upper']:
            sell_signals += 1

        # ✅ 5. MACD trendi
        if macd_vals['macd'] > macd_vals['signal']:
            buy_signals += 1
        elif macd_vals['macd'] < macd_vals['signal']:
            sell_signals += 1
            
        max_possible = 5
        signal_ratio = max(buy_signals, sell_signals) / max_possible

        logger.info(f"[{epic}] STRONG: Signal nisbati: {signal_ratio:.2f} ({buy_signals}/{max_possible} BUY, {sell_signals}/{max_possible} SELL)")

        # Qabul qilish qoidalari
        if buy_signals >= math.ceil(max_possible * 0.8): # 5 tadan 4 tasi mos kelsa
            return "BUY"
        elif sell_signals >= math.ceil(max_possible * 0.8): # 5 tadan 4 tasi mos kelsa
            return "SELL"

        return None

    except Exception as e:
        logger.error(f"Strong signal hisoblashda xato: {e}")
        return None
async def calculate_mnl_signals(capital_api, epic: str, settings: Dict, enabled_indicators: Dict) -> Optional[str]:
    """
    Faqat yoqilgan indikatorlardan foydalanib signal hisoblaydi (MNL rejimi)
    """
    # enabled_indicators bo'sh bo'lsa, default qiymatlar
    if not enabled_indicators:
        enabled_indicators = {
            "ema": True, "rsi": True, "macd": True, 
            "bollinger": True, "trend": True
        }
    
    # Narxlarni olish - TO'G'RI resolution formatlari bilan urinib ko'ramiz
    prices_data = None
    resolutions_to_try = ["HOUR", "HOUR_4", "DAY", "MINUTE"]  # ✅ TO'G'RI FORMATLAR
    
    for resolution in resolutions_to_try:
        prices_data = await capital_api.get_historical_prices(epic, resolution, 50)
        if prices_data and len(prices_data) >= 20:
            logger.debug(f"[{epic}] {resolution} resolutionda yetarli ma'lumot topildi: {len(prices_data)} ta")
            break
        else:
            if prices_data:
                logger.debug(f"[{epic}] {resolution} resolutionda {len(prices_data)} ta ma'lumot topildi, lekin 20 tadan kam")
            else:
                logger.debug(f"[{epic}] {resolution} resolutionda ma'lumot topilmadi")
    
    if not prices_data or len(prices_data) < 20:
        logger.debug(f"[{epic}] MNL: Hech qanday resolutionda yetarli tarixiy ma'lumot topilmadi")
        return None
    
    # Ma'lumotlarni to'g'ri qayta ishlash
    closes = []
    for price in prices_data:
        if isinstance(price, dict):
            close_price = None
            if "closePrice" in price and isinstance(price["closePrice"], dict):
                close_price = price["closePrice"].get("bid")  # yoki ask
            elif "openPrice" in price and isinstance(price["openPrice"], dict):
                close_price = price["openPrice"].get("bid")
            elif "highPrice" in price and isinstance(price["highPrice"], dict):
                close_price = price["highPrice"].get("bid")
            elif "lowPrice" in price and isinstance(price["lowPrice"], dict):
                close_price = price["lowPrice"].get("bid")
            elif "bid" in price and "ask" in price:
                close_price = (float(price["bid"]) + float(price["ask"])) / 2

            if close_price is not None:
                closes.append(float(close_price))

    
    if len(closes) < 20:
        logger.debug(f"[{epic}] MNL: Yetarli yopilish narxlari topilmadi ({len(closes)} ta)")
        return None
    
    # Pandas seriesga o'tkazamiz
    prices_series = pd.Series(closes)
    last_price = prices_series.iloc[-1] if not prices_series.empty else None
    
    if last_price is None:
        logger.warning(f"[{epic}] MNL: Oxirgi narx topilmadi")
        return None
    
    buy_signals = 0
    sell_signals = 0
    max_possible = 0
    
    # EMA tekshirish
    if enabled_indicators.get("ema", True):
        max_possible += 1
        ema20 = calculate_ema(prices_series, 20)
        ema50 = calculate_ema(prices_series, 50)
        if ema20 is not None and ema50 is not None:
            if ema20 > ema50:
                buy_signals += 1
            elif ema20 < ema50:
                sell_signals += 1
    
    # RSI tekshirish
    if enabled_indicators.get("rsi", True):
        max_possible += 1
        rsi = calculate_rsi(prices_series, 14)
        if rsi is not None:
            if rsi < settings.get("rsi_buy_level", 35):
                buy_signals += 1
            elif rsi > settings.get("rsi_sell_level", 65):
                sell_signals += 1
    
    # MACD tekshirish
    if enabled_indicators.get("macd", True):
        max_possible += 1
        macd_data = calculate_macd(prices_series)
        if macd_data and macd_data.get("macd") is not None and macd_data.get("signal") is not None:
            if macd_data["macd"] > macd_data["signal"]:
                buy_signals += 1
            elif macd_data["macd"] < macd_data["signal"]:
                sell_signals += 1
    
    # Bollinger Bands tekshirish
    if enabled_indicators.get("bollinger", True):
        max_possible += 1
        bb_data = calculate_bollinger_bands(prices_series, 20)
        if bb_data and bb_data.get("upper") is not None and bb_data.get("lower") is not None:
            if last_price <= bb_data["lower"]:
                buy_signals += 1
            elif last_price >= bb_data["upper"]:
                sell_signals += 1
    
    # Trend analiz tekshirish
    if enabled_indicators.get("trend", True):
        max_possible += 1
        if len(prices_series) >= 20:
            short_trend = prices_series.iloc[-1] - prices_series.iloc[-5]
            long_trend = prices_series.iloc[-1] - prices_series.iloc[-20]
            if short_trend > 0 and long_trend > 0:
                buy_signals += 1
            elif short_trend < 0 and long_trend < 0:
                sell_signals += 1
    
    # Signalni qaytarish
    if max_possible == 0:
        logger.debug(f"[{epic}] MNL: Hech qanday indikator yoqilmagan")
        return None
    
    signal_ratio = max(buy_signals, sell_signals) / max_possible
    logger.info(f"[{epic}] MNL: Signal nisbati: {signal_ratio:.2f} ({buy_signals}/{max_possible} BUY, {sell_signals}/{max_possible} SELL)")
    
    if buy_signals >= math.ceil(max_possible * 0.6):
        logger.info(f"[{epic}] MNL: BUY signal qabul qilindi!")
        return "BUY"
    elif sell_signals >= math.ceil(max_possible * 0.6):
        logger.info(f"[{epic}] MNL: SELL signal qabul qilindi!")
        return "SELL"
    
    logger.debug(f"[{epic}] MNL: Signal etarli emas")
    return None


def calculate_indicators(historical_prices: List[Dict]) -> Optional[Dict[str, Any]]:
    """Tarixiy narxlardan indikatorlarni hisoblash (Capital.com API uchun).
    Agar yetarli ma'lumot bo'lmasa -> None qaytaradi.
    """
    logger.info(">>> ENTER calculate_indicators (info)")
    logger.debug("calculate_indicators ga kelgan ma'lumotlar len=%s", len(historical_prices) if historical_prices else 0)

    try:
        if not historical_prices or len(historical_prices) < 20:
            # 20 dan kam -> indikatorlar uchun yetarli emas (MNL/WEAK talablariga qarab bu qiymatni o'zgartiring)
            logger.debug("calculate_indicators: historical_prices yetarli emas")
            return None

        # Close qiymatlarini yig'ish (robust fallback)
        closes = []
        for price in historical_prices:
            if not isinstance(price, dict):
                continue

            close_price = None
            if "closePrice" in price and isinstance(price["closePrice"], dict):
                # prefer bid (yoki strategiyaga qarab 'ask')
                close_price = price["closePrice"].get("bid")
            elif "openPrice" in price and isinstance(price["openPrice"], dict):
                close_price = price["openPrice"].get("bid")
            elif "highPrice" in price and isinstance(price["highPrice"], dict):
                close_price = price["highPrice"].get("bid")
            elif "lowPrice" in price and isinstance(price["lowPrice"], dict):
                close_price = price["lowPrice"].get("bid")
            elif "price" in price:
                close_price = price.get("price")
            elif "bid" in price and "ask" in price:
                try:
                    close_price = (float(price["bid"]) + float(price["ask"])) / 2.0
                except Exception:
                    close_price = None

            if close_price is not None:
                try:
                    closes.append(float(close_price))
                except Exception:
                    # ignore unparsable values
                    continue

        if len(closes) < 14:
            logger.debug("calculate_indicators: yetarli closes topilmadi (%s ta)", len(closes))
            return None

        # numpy arrayga o'tkazish
        closes_array = np.array(closes, dtype=float)

        indicators: Dict[str, Any] = {}

        # RSI
        if len(closes_array) >= 14:
            try:
                rsi = talib.RSI(closes_array, timeperiod=14)
                indicators["rsi"] = float(rsi[-1]) if not np.isnan(rsi[-1]) else None
            except Exception:
                indicators["rsi"] = None

        # EMA20 / EMA50
        if len(closes_array) >= 20:
            try:
                ema20 = talib.EMA(closes_array, timeperiod=20)
                indicators["ema20"] = float(ema20[-1]) if not np.isnan(ema20[-1]) else None
            except Exception:
                indicators["ema20"] = None

        if len(closes_array) >= 50:
            try:
                ema50 = talib.EMA(closes_array, timeperiod=50)
                indicators["ema50"] = float(ema50[-1]) if not np.isnan(ema50[-1]) else None
            except Exception:
                indicators["ema50"] = None

        # MACD
        if len(closes_array) >= 26:
            try:
                macd, macd_signal, macd_hist = talib.MACD(closes_array, fastperiod=12, slowperiod=26, signalperiod=9)
                indicators["macd"] = float(macd[-1]) if not np.isnan(macd[-1]) else None
                indicators["macd_signal"] = float(macd_signal[-1]) if not np.isnan(macd_signal[-1]) else None
                indicators["macd_hist"] = float(macd_hist[-1]) if not np.isnan(macd_hist[-1]) else None
            except Exception:
                indicators["macd"] = indicators["macd_signal"] = indicators["macd_hist"] = None

        # Bollinger va boshqalar qisqartirilgan misol:
        if len(closes_array) >= 20:
            try:
                upper, middle, lower = talib.BBANDS(closes_array, timeperiod=20)
                indicators["bb_upper"] = float(upper[-1]) if not np.isnan(upper[-1]) else None
                indicators["bb_middle"] = float(middle[-1]) if not np.isnan(middle[-1]) else None
                indicators["bb_lower"] = float(lower[-1]) if not np.isnan(lower[-1]) else None
            except Exception:
                indicators["bb_upper"] = indicators["bb_middle"] = indicators["bb_lower"] = None

        logger.debug("calculate_indicators natija: %s", indicators)
        return indicators

    except Exception as e:
        logger.exception("Indikatorlarni hisoblashda xato: %s", e)
        return None

# ✅ YANGI: Dynamic AI Trailing Stop funksiyalari
import re

async def get_dynamic_ai_trailing_decision(asset_name: str, direction: str, open_price: float, 
                                         current_price: float, indicators: Dict, deal_id: str,
                                         prices: Dict) -> Dict:  # ✅ prices qo'shildi
    """
    Dynamic AI trailing stop - spread va costlarni hisobga oladi
    """
    # Savdo xarajatlarini hisoblash
    trading_costs = calculate_trading_costs(prices, direction)
    profit_percent = (current_price - open_price) / open_price * 100 if direction == "BUY" else (open_price - current_price) / open_price * 100
    
    # Net foyda (xarajatlardan keyin)
    net_profit = profit_percent - trading_costs["total_entry_cost"]
    
    prompt = f"""
🎯 **DYNAMIC TRAILING STOP ANALYSIS - COST AWARE**

📊 **CURRENT POSITION:**
- ASSET: {asset_name}
- DIRECTION: {direction}
- OPEN PRICE: {open_price:.2f}
- CURRENT PRICE: {current_price:.2f}
- GROSS PROFIT: {profit_percent:+.2f}%

💰 **TRADING COSTS:**
- SPREAD: {trading_costs['spread_percent']:.3f}%
- COMMISSION: {trading_costs['commission_percent']:.3f}%
- TOTAL ENTRY COST: {trading_costs['total_entry_cost']:.3f}%
- NET PROFIT: {net_profit:+.2f}%
- MIN PROFIT REQUIRED: {trading_costs['min_profit_required']:.2f}%

📈 **TECHNICAL ANALYSIS:**
- RSI: {indicators.get('rsi', 'N/A'):.1f} {get_rsi_status(indicators.get('rsi'))}
- TREND: {get_trend_status(indicators)}
- MACD: {get_macd_status(indicators)}
- VOLATILITY: {get_volatility_status(asset_name, indicators)}
- SUPPORT/RESISTANCE: {get_support_resistance_status(indicators)}

🎯 **TRADING DECISION REQUEST:**
NET profit {net_profit:+.2f}% ni hisobga olgan holda analiz qiling:
1. Savdoni Hozir YOPISH kerakmi? (xarajatlarni qoplaganmisiz?)
2. Agar YOPMASLIK kerak bo'lsa, optimal NET Take Profit foizi qancha?
3. Spread va commission xarajatlarini hisobga olgan holda qaror qiling

📝 **RESPONSE FORMAT:**
CLOSE: [Sabab - NET profit va xarajatlar asosida]
YOKI  
HOLD: [Taklif qilingan NET TP: X%, Ishonch: Y%, Sabab]
"""

    ai_response = await get_ai_approval(asset_name, direction, prices, indicators)
    return parse_dynamic_ai_response(ai_response, current_price, open_price, direction, trading_costs)


def parse_dynamic_ai_response(ai_response: Dict, current_price: float, open_price: float, 
                            direction: str, trading_costs: Dict) -> Dict:
    """
    AI javobini parsing qilish - NET profit asosida
    """
    text = ai_response.get('reason', '').upper()
    
    if "CLOSE" in text:
        return {"action": "CLOSE", "reason": ai_response.get('reason', 'AI NET profit asosida yopishni tavsiya qiladi')}
    elif "HOLD" in text:
        # NET Take Profit ni extract qilish
        tp_match = re.search(r'NET TP:\s*([\d.]+)%', text) or re.search(r'TP:\s*([\d.]+)%', text)
        confidence_match = re.search(r'Confidence:\s*([\d.]+)%', text) or re.search(r'Ishonch:\s*([\d.]+)%', text)
        
        # NET TP ni olish yoki default
        net_tp_percent = float(tp_match.group(1)) if tp_match else 2.0  # default 2% NET
        
        # GROSS TP ni hisoblash (NET TP + costs)
        gross_tp_percent = net_tp_percent + trading_costs["total_entry_cost"]
        
        confidence = float(confidence_match.group(1)) if confidence_match else 70.0
        
        # Take profit narxini hisoblash (GROSS asosida)
        if direction == "BUY":
            take_profit_price = open_price * (1 + gross_tp_percent / 100)
        else:  # SELL
            take_profit_price = open_price * (1 - gross_tp_percent / 100)
            
        return {
            "action": "HOLD", 
            "take_profit_percent": gross_tp_percent,  # GROSS TP
            "net_take_profit_percent": net_tp_percent,  # NET TP
            "take_profit_price": take_profit_price,
            "confidence": confidence,
            "reason": ai_response.get('reason', 'AI NET profit asosida davom ettirishni tavsiya qiladi')
        }
    else:
        # Default - hozir yopmaslik
        return {"action": "HOLD", "take_profit_percent": 3.0, "net_take_profit_percent": 2.5, "confidence": 60.0, "reason": "AI noaniq javob berdi"}


def calculate_trading_costs(prices: Dict, direction: str) -> Dict:
    """Savdo xarajatlarini hisoblash"""
    spread = prices['sell'] - prices['buy']
    spread_percent = (spread / prices['buy']) * 100
    
    # Taxminiy commission (brokerga qarab)
    commission_percent = 0.001  # 0.1%
    
    # Jami kirish xarajati
    total_entry_cost = spread_percent + commission_percent
    
    # Minimal foyda (xarajatlarni qoplash uchun)
    min_profit_to_break_even = total_entry_cost * 1.5  # 50% safety margin
    
    return {
        "spread_percent": spread_percent,
        "commission_percent": commission_percent,
        "total_entry_cost": total_entry_cost,
        "min_profit_required": min_profit_to_break_even
    }






async def get_ai_trade_signal_enhanced(asset: str, signal: str, prices: Dict, indicators: Dict) -> Dict:
    """
    Mukammal AI so'rovi - barcha kerakli ma'lumotlar bilan
    """
    prompt = f"""
🎯 **PROFESSIONAL TRADING SIGNAL EVALUATION**

📊 **TRADE OPPORTUNITY:**
- ASSET: {asset}
- PROPOSED ACTION: {signal}
- CURRENT PRICE: {prices.get('buy' if signal == 'BUY' else 'sell', 'N/A')}
- SPREAD: {calculate_spread(prices):.3f}%

📈 **TECHNICAL ANALYSIS:**
- RSI: {indicators.get('rsi', 'N/A'):.1f} {get_rsi_status(indicators.get('rsi'))}
- TREND: {get_trend_status(indicators)}
- MACD: {get_macd_status(indicators)}
- BOLLINGER BANDS: {get_bollinger_status(prices, indicators)}
- SUPPORT/RESISTANCE: {get_support_resistance_status(indicators)}

⚡ **MARKET CONTEXT:**
- MARKET HOURS: {'OPEN' if is_market_open(asset) else 'CLOSED'}
- VOLATILITY: {get_volatility_status(asset, indicators)}
- SIGNAL STRENGTH: {get_signal_strength(asset, signal, indicators)}

📋 **TRADING PARAMETERS:**
- POSITION SIZE: Medium
- RISK LEVEL: {'LOW' if signal == 'BUY' and indicators.get('rsi', 50) < 40 else 'MEDIUM'}
- TIME FRAME: Swing Trade (1-3 days)

❓ **EVALUATION REQUEST:**
Should I execute this {signal} trade for {asset} based on the current market conditions and technical setup?

📝 **RESPONSE FORMAT:**
APPROVE: [Brief reasoning - max 2 lines]
OR  
REJECT: [Brief reasoning - max 2 lines]

Focus on risk/reward ratio, technical confirmation, and market context.
"""
    
    return await get_ai_approval(asset, signal, prices, indicators)


async def send_hourly_report(context: ContextTypes.DEFAULT_TYPE):
    """Har soat faol aktivlar va ochiq savdolar haqida hisobot yuborish"""
    try:
        db, api = get_global_instances()
        if not db or not api:
            logger.warning("Soatlik hisobot: global db/api topilmadi, o‘tkazib yuborildi")
            return

        settings = await db.get_settings()
        chat_id = settings.get("chat_id") or CHAT_ID
        
        if not chat_id:
            return

        # Ochiq pozitsiyalarni olish
        open_positions = await api.get_open_positions()
        positions_count = len(open_positions) if open_positions else 0

        message = "🕐 **Soatlik Hisobot**\n\n"
        has_open_positions = False

        # ✅ YANGI: Faqat ochiq savdolari bo'lgan aktivlarni ko'rsatamiz
        if open_positions:
            message += "🔓 **Ochiq Savdolar:**\n\n"
            
            for i, pos in enumerate(open_positions, 1):
                deal_id = pos.get("dealId") or pos.get("positionId")
                if not deal_id:
                    continue

                # Pozitsiya tafsilotlarini olish
                detail = await api.get_position_details(deal_id)
                position = detail.get("position", {})
                market = detail.get("market", {})

                asset_name = market.get("instrumentName", "Noma'lum")
                epic = market.get("epic", "")
                direction = position.get("direction", "").upper()
                open_price = position.get("level", 0)
                size = position.get("size", 0)
                leverage = position.get("leverage", 1)
                profit_loss = position.get("upl", 0)  # UPL - Unrealized P/L
                
                # Vaqtni formatlash
                created_date = position.get("createdDateUTC", "")
                open_time = "Noma'lum"
                if created_date:
                    try:
                        opened_at = datetime.datetime.fromisoformat(created_date.replace("Z", "+00:00"))
                        tashkent_time = opened_at.astimezone(pytz.timezone('Asia/Tashkent'))
                        open_time = tashkent_time.strftime('%Y-%m-%d %H:%M')
                    except:
                        open_time = created_date

                message += f"📊 **{asset_name} ({epic}):**\n"
                message += f"   • Yo'nalish: {direction}\n"
                message += f"   • Ochiq narx: {open_price}\n"
                message += f"   • Leverage: {leverage}\n"
                message += f"   • Ochilgan vaqti: {open_time}\n"
                message += f"   • Foyda/zarar: {profit_loss:.2f} USD\n\n"
                
                has_open_positions = True

        # Agar ochiq savdo yo'q bo'lsa
        if not has_open_positions:
            message += "📭 Hozirda ochiq savdolar yo'q\n\n"

        # Aktivlar narxlari (qisqacha)
        message += "💹 **Aktivlar Narxlari:**\n\n"
        active_assets_shown = 0
        
        for asset_name, details in ACTIVE_INSTRUMENTS.items():
            # Faqat bir nechta asosiy aktivlarni ko'rsatamiz
            if active_assets_shown >= 5:  # 5 ta aktiv ko'rsatamiz
                break
                
            asset_settings = settings.get("buy_sell_status_per_asset", {}).get(asset_name, {})
            if not asset_settings.get("active", True):
                continue

            # Joriy narxlarni olish
            prices = await api.get_prices(details["id"])
            if not prices:
                continue

            buy_price = prices.get("buy", 0)
            sell_price = prices.get("sell", 0)
            
            if buy_price > 0 and sell_price > 0:
                spread = sell_price - buy_price
                spread_percent = (spread / buy_price) * 100
                
                message += f"• {asset_name}: ${buy_price:.2f} / ${sell_price:.2f} ({spread_percent:.2f}%)\n"
                active_assets_shown += 1

        # Yakuniy ma'lumotlar
        message += f"\n🔢 **Jami:** {positions_count} ta ochiq savdo\n"
        message += f"⏰ **Vaqt:** {get_tashkent_time().strftime('%H:%M')}\n"
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=message, 
            parse_mode='Markdown'
        )
        logger.info("✅ Soatlik hisobot yuborildi")

    except Exception as e:
        logger.error(f"Soatlik hisobot yuborishda xato: {e}")


async def execute_trade(api, asset_name, asset_id, signal, asset_settings, context):
    """
    Xavfsiz savdo amalga oshirish
    """
    try:
        # Savdo hajmini hisoblash
        trade_amount = asset_settings.get("trade_amount_usd", 50)
        prices = await api.get_prices(asset_id)
        
        if signal == "BUY":
            price = prices.get("buy", 0)
            direction = "BUY"
        else:
            price = prices.get("sell", 0)
            direction = "SELL"
        
        if price <= 0:
            logger.error(f"{asset_name} uchun noto'g'ri narx: {price}")
            return
            
        # Lot hajmini hisoblash
        size = trade_amount / price
        
        # Savdoni amalga oshirish
        result = await api.create_position(
            currency_pair=asset_id,
            direction=direction,
            size=size
        )
        
        if result.get("success"):
            logger.info(f"✅ {asset_name} {direction} savdosi muvaffaqiyatli ochildi")
            # Pozitsiyani saqlash
            await save_position(context, asset_name, asset_id, direction, size, result)
        else:
            logger.error(f"❌ {asset_name} {direction} savdosi ochilmadi: {result.get('error')}")
            
    except Exception as e:
        logger.error(f"{asset_name} savdosi uchun xato: {str(e)}")


async def get_ai_trailing_approval(asset_name: str, direction: str, open_price: float, current_price: float, profit_percent: float) -> Dict[str, str]:
    """
    Trailing stop uchun AI tasdiqini olish
    """
    if not GEMINI_API_KEY:
        return {"decision": "REJECT", "reason": "API Key not found"}
    
    prompt = f"""
    Siz professional trader sifatida trailing stop qarori qabul qilishingiz kerak.
    
    Aktiv: {asset_name}
    Savdo turi: {direction}
    Ochilish narxi: {open_price}
    Joriy narx: {current_price}
    Foyda/zarar: {profit_percent:.2f}%
    
    Ushbu savdoni trailing stop orqali yopish kerakmi? Faqat "APPROVE" yoki "REJECT" qaytaring.
    Sababini qisqacha izohlang.
    """
    
    try:
        # Gemini AI ga so'rov yuborish
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 100,
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    text = result['candidates'][0]['content']['parts'][0]['text']
                    
                    # Javobni tahlil qilish
                    if "APPROVE" in text.upper():
                        return {"decision": "APPROVE", "reason": text}
                    else:
                        return {"decision": "REJECT", "reason": text}
                else:
                    return {"decision": "REJECT", "reason": "API xatosi"}
                    
    except Exception as e:
        logger.error(f"AI trailing so'rovida xato: {e}")
        return {"decision": "REJECT", "reason": f"Xato: {str(e)}"}        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    text = result['candidates'][0]['content']['parts'][0]['text']
                    
                    # Javobni tahlil qilish
                    if "APPROVE" in text.upper():
                        return {"decision": "APPROVE", "reason": text}
                    else:
                        return {"decision": "REJECT", "reason": text}
                else:
                    return {"decision": "REJECT", "reason": "API xatosi"}
                    
    except Exception as e:
        logger.error(f"AI trailing so'rovida xato: {e}")
        return {"decision": "REJECT", "reason": f"Xato: {str(e)}"}

async def refresh_positions(context: ContextTypes.DEFAULT_TYPE):
    """API'dan ochiq pozitsiyalarni olib, db.json ga yozadi."""
    try:
        # ✅ Global instancelardan foydalanish
        db, api = get_global_instances()
        
        if not api or not db:
            logger.warning("refresh_positions: Global API yoki DB topilmadi.")
            return

        open_positions = await api.get_open_positions()
        settings = await db.get_settings()
        
        if not open_positions:
            settings['positions'] = {}
            await db.save_settings(settings)
            return

        if isinstance(open_positions, dict):
            pos_list = open_positions.get('positions') or open_positions.get('data') or open_positions.get('results') or []
        elif isinstance(open_positions, (list, tuple)):
            pos_list = list(open_positions)
        else:
            pos_list = []

        new_positions = {}

        for pos in pos_list:
            epic = pos.get('epic')
            asset_name = get_asset_name_by_epic(epic)
            
            # deal id topish
            deal_id = pos.get('dealId') or pos.get('positionId') or str(uuid.uuid4())
            asset_name = pos.get('instrumentName') or pos.get('epic') or "Noma'lum"
            direction = pos.get('direction') or pos.get('dealType') or "Noma'lum"
            open_price = pos.get('level') or pos.get('openPrice') or 0
            size = pos.get('size') or pos.get('dealSize') or 0
            
            new_positions[deal_id] = {
                "asset_name": asset_name,
                "direction": direction,
                "deal_type": direction,
                "opened_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
                "open_price": open_price,
                "deal_id": deal_id,
                "size": size,
                "raw": pos,
                "epic": epic,
            }
        
        settings['positions'] = new_positions
        await db.save_settings(settings)
        logger.info(f"Ochiq pozitsiyalar yangilandi. Jami: {len(new_positions)}")

    except Exception as e:
        logger.error("Pozitsiyalarni yangilashda xato: %s", e)
        traceback.print_exc()


# trading_logic.py da get_trailing_stop_percent funksiyasini yangilaymiz

def get_trailing_stop_percent(settings, local_position, current_prices, indicators=None):
    """
    Yangi MNL rejim: spread + komissiya + foydalanuvchi kiritgan minimal foyda
    """
    try:
        mode = settings.get("trailing_mode", "MNL")
        buy = current_prices.get("buy", 0)
        sell = current_prices.get("sell", 0)

        # Spread hisoblash (AUTO kabi)
        if buy > 0 and sell > 0:
            mid_price = (buy + sell) / 2
            spread = abs(sell - buy)
            spread_percent = spread / mid_price
        else:
            spread_percent = 0.002  # default 0.2%

        commission_percent = 0.0015  # 0.15%

        if mode == "MNL":
            user_percent = settings.get("trailing_stop_percent", 0.01)
            if user_percent < 1:
                user_min_profit = user_percent / 100
            else:
                user_min_profit = user_percent / 100
            
            # ✅ YANGI: MNL rejimda ham SPREAD va KOMISSIYA qo'shamiz
            if buy > 0 and sell > 0:
                mid_price = (buy + sell) / 2
                spread = abs(sell - buy)
                spread_percent = spread / mid_price
            else:
                spread_percent = 0.002  # default 0.2%
                
            commission_percent = 0.0015  # 0.15%
            
            # ✅ ENDI: spread + komissiya + foydalanuvchi minimal foydasi
            trailing_stop = spread_percent + commission_percent + user_min_profit
            return trailing_stop


        elif mode == "AUTO":
            # Avvalgidek AUTO rejim
            min_profit_percent = 0.003   # 0.3%
            trailing_stop = spread_percent + commission_percent + min_profit_percent
            trailing_stop = max(0.004, min(trailing_stop, 0.03))
            return trailing_stop

        else:  # AI, TEST
            return settings.get("trailing_stop_percent", 0.01)

    except Exception as e:
        logger.error(f"get_trailing_stop_percent xatosi: {e}")
        return 0.01


async def trading_logic_loop(context: ContextTypes.DEFAULT_TYPE):
    """Sozlamalarga mos auto savdo funksiyasi"""
    logger.info("🔄 Auto savdo aylanmasi ishlayapti...")
    db: InMemoryDB = context.user_data['db']
    api: CapitalComAPI = context.user_data['capital_api']

    while not stop_event.is_set():
        try:
            settings = await db.get_settings()

            if not settings.get("auto_trading_enabled", True):
                logger.info("⏸️ Auto savdo o'chirilgan")
                await asyncio.sleep(10)
                continue

            # Ochiq pozitsiyalarni olish
            try:
                open_positions = await api.get_open_positions()
                active_trade_count = len(open_positions) if open_positions else 0
                if active_trade_count > 0:
                    logger.info(f"📊 Ochiq pozitsiyalar soni: {active_trade_count}")
            except Exception as e:
                logger.error(f"Ochiq pozitsiyalarni olishda xato: {e}")
                active_trade_count = 0

            max_trades_count = settings.get("max_trades_count", 3)
            if active_trade_count >= max_trades_count:
                logger.info("⛔ Maksimal savdolar soniga yetildi.")
                await asyncio.sleep(10)
                continue

            # trading_logic.py - trading_logic_loop ichida

            for asset, details in ACTIVE_INSTRUMENTS.items():
                logger.info(f"📊 {asset} tekshirilmoqda...")

                asset_settings = settings.get("buy_sell_status_per_asset", {}).get(asset, {})
                if not asset_settings.get("active", True):
                    continue
                if not is_market_open(asset):
                    continue

                # ✅ AI uchun kerak bo'lsa, indicators ni oldindan tayyorlaymiz
                ai_enabled = settings.get("trade_signal_ai_enabled", False)
                indicators = None
                
                # Agar AI yoqilmagan bo'lsa, indicators ni hisoblamaymiz
                if ai_enabled and signal_level != "TEST":
                    # Faqat AI yoqilgan bo'lsa indicators ni hisoblaymiz
                    historical_prices = []
                    for res in ["HOUR", "DAY", "MINUTE"]:
                        historical_prices = await api.get_historical_prices(details['id'], res, 50)
                        if historical_prices and len(historical_prices) >= 20:
                            break
                    indicators = calculate_indicators(historical_prices or [])
                else:
                    indicators = {}  # Bo'sh dict

                # Narxlarni olish
                prices = await get_prices_with_retry(api, details["id"], 3)
                if not prices:
                    logger.warning(f"❌ [{asset}] narxlari topilmadi. O'tkazib yuborildi.")
                    continue

                # Signal hisoblash
                trade_signal = None
                signal_level = settings.get("trade_signal_level", "MNL")
                
                if signal_level == "MNL":
                    enabled_indicators = settings.get("enabled_indicators", {})
                    trade_signal = await calculate_mnl_signals(api, details['id'], settings, enabled_indicators)
                elif signal_level == "WEAK":
                    trade_signal = await calculate_weak_signals(api, details['id'], settings)
                elif signal_level == "STRONG":
                    trade_signal = await calculate_strong_signals(api, details['id'], settings)
                elif signal_level == "TEST":
                    trade_signal = "BUY"

                if trade_signal:
                    logger.info(f"🎯 {asset} uchun {trade_signal} SIGNAL TOPILDI!")
                    
                    # ✅ AI tasdiqlash - CACHEsiz
                    if ai_enabled and signal_level != "TEST":
                        try:
                            # Har doim yangi AI so'rovi
                            ai_approval = await get_ai_trade_signal_enhanced(
                                asset, trade_signal, prices, indicators or {}
                            )

                            if ai_approval.get("decision") != "APPROVE":
                                reason = ai_approval.get('reason', 'Noma\'lum sabab')
                                await send_trading_status(
                                    context, 
                                    f"❌ [AI] {asset} {trade_signal} rad etildi\n📝 {reason}", 
                                    "warning"
                                )
                                continue
                            else:
                                logger.info(f"[{asset}] AI tasdiqladi: {trade_signal}")
                                await send_trading_status(
                                    context, 
                                    f"✅ [AI] {asset} tasdiqlandi: {trade_signal.upper()}", 
                                    "success"
                                )
                                
                        except Exception as e:
                            logger.error(f"AI tasdiqlashda xato: {e}")
                            # AI da xato bo'lsa, savdoni o'tkazib yuboramiz
                            continue
                    
       
                    # ✅ Savdoni TEST rejimiga o'xshatib amalga oshirish
                    try:
                        usd_amount = settings.get("trade_amount_per_asset", {}).get(asset, 50)
                        price = prices["buy"] if trade_signal == "BUY" else prices["sell"]
                        calculated_size = usd_amount / price                        
                        # API orqali savdoni amalga oshirish
                        order_response = await api.open_position(details['id'], trade_signal, calculated_size)

                        if order_response and not order_response.get("errorCode"):
                            # Agar javob bo'lsa va xato kodi bo'lmasa, savdo ochilgan deb hisoblash
                            logger.info(f"✅ {asset} uchun {trade_signal} savdosi ochildi. Miqdor: {calculated_size:.4f}")
                            await send_trading_status(
                                context,
                                f"✅ Savdo ochildi: {asset} ({trade_signal})\nNarx: {price:.2f} | Miqdor: {calculated_size:.4f}",
                                "success"
                            )
                            # Ushbu qatorda order_response tarkibini tekshirish foydali bo'lishi mumkin
                            if order_response.get("dealReference"):
                                await db.add_position(asset, order_response)
                            else:
                                logger.warning(f"Savdo ochildi, ammo dealReference topilmadi: {order_response}")
                                # Shuningdek, ma'lumotnomani keyinroq olish uchun logga yozishingiz mumkin

                        else:
                            # Agar javobda xato kodi bo'lsa yoki javob bo'sh bo'lsa
                            error_msg = order_response.get("error", "Noma'lum xato") if order_response else "Javob yo'q"
                            logger.error(f"Savdo ochishda xato: {error_msg}")
                            await send_trading_status(context, f"❌ Savdo ochilmadi: {asset} - {error_msg}", "error")

                    except Exception as e:
                        logger.error(f"Savdo ochishda istisno: {e}")
                        await send_trading_status(context, f"❌ Savdo ochishda xato: {asset} - {str(e)}", "error")

            await asyncio.sleep(10)

        except Exception as e:
            error_msg = f"Savdo jarayonida xato: {str(e)}"
            logger.error(error_msg)
            traceback.print_exc()
            await send_trading_status(context, error_msg, "error")
            await asyncio.sleep(60)


async def close_profitable_positions_loop(context: ContextTypes.DEFAULT_TYPE):
    """Sozlamalarga mos ravishda trailing stop va savdo yopish funksiyasi"""
    logger.info("✅ Trailing stop loop ishga tushdi.")

    logger.info("⏳ Global instancelar sozlanishini kutish...")
    await asyncio.sleep(10)  # 10 soniya kutish

    # ✅ YANGI: Dynamic AI trailing positions tracker
    ai_trailing_positions = {}

    while not stop_event.is_set():
        try:
            await asyncio.sleep(30)  # ⬅️ ASOSIY LOOP 30 soniyada bir
            
            # Global instancelarni tekshirish
            db, api = get_global_instances()
            if not db or not api:
                # ✅ Contextdan ham topishga urinib ko'ramiz
                db = context.user_data.get('db')
                api = context.user_data.get('capital_api')
                if db and api:
                    logger.info("✅ Global instancelar contextdan topildi")
                    set_global_instances(db, api)
                else:
                    logger.debug("⏳ Global instancelar hali topilmadi. Kutilyapti...")
                    continue

            settings = await db.get_settings()
            
            if not settings.get("demo_account_status", False) and not settings.get("real_account_status", False):
                logger.info("⏸️ Hisoblar o'chirilgan. Trailing stop to'xtatildi.")
                continue

            open_positions = await api.get_open_positions()
            
            if not open_positions:
                logger.debug("📭 Ochiq pozitsiyalar yo'q")
                continue

            logger.info(f"📋 {len(open_positions)} ta pozitsiya tekshirilmoqda...")
            for i, pos in enumerate(open_positions):
                deal_id = pos.get("dealId") or pos.get("positionId")
                if not deal_id:
                    continue

                # ✅ LOG: Har bir pozitsiya uchun
                logger.debug(f"🔎 {i+1}-pozitsiya tekshirilmoqda: {deal_id}")
                
                detail = await api.get_position_details(deal_id)
                position = detail.get("position", {})
                market = detail.get("market", {})

                asset_name = market.get("instrumentName", "Noma'lum")
                epic = market.get("epic", None)
                
                # ✅ LOG: Aktiv nomi
                logger.debug(f"📊 Aktiv: {asset_name}")
                
                # Bozor ochiq/yopiqligini tekshirish
                if not is_market_open(asset_name):
                    logger.debug(f"⏸️ {asset_name} bozori yopiq")
                    continue
                
                direction = position.get("direction", "").upper()
                open_price = position.get("level", 0)
                size = position.get("size", 0)

                # ✅ LOG: Narxlarni olish
                current_prices = await api.get_prices(epic)
                if not current_prices:
                    logger.debug(f"❌ {asset_name} uchun narx topilmadi")
                    continue

                # Trailing mode ni aniqlash
                trailing_mode = settings.get("trailing_mode", "MNL")
                use_ai_trailing = settings.get("use_ai_trailing_stop", False)

                # Trailing stop foizini olish
                trailing_percent = get_trailing_stop_percent(settings, position, current_prices)

                # Yo'nalishga qarab narxni aniqlash va foyda foizini hisoblash
                if direction == "BUY":
                    current_price = current_prices.get("sell", 0)
                    price_diff = (current_price - open_price) / open_price if open_price else 0
                elif direction == "SELL":
                    current_price = current_prices.get("buy", 0)
                    price_diff = (open_price - current_price) / open_price if open_price else 0
                else:
                    continue

                # Trailing stop shartini tekshirish
                should_close = False
                close_reason = ""

                logger.info(f"🔧 DEBUG: {asset_name} | Mode: {trailing_mode} | AI Trailing: {use_ai_trailing}")

                # ✅ YANGI: Dynamic AI trailing stop (spread bilan)
                if trailing_mode == "AI" and use_ai_trailing:
                    logger.info(f"🎯 AI TRAILING BLOKIGA KIRDI: {asset_name}")

                    current_time = time.time()


                    
                    # Har 2 daqiqada bir AI so'rovi
                    last_ai_check = ai_trailing_positions.get(deal_id, {}).get('last_ai_check', 0)

                    logger.info(f"⏰ DEBUG: {asset_name} | Last check: {last_ai_check} | Current: {current_time} | Diff: {current_time - last_ai_check}")
                    if current_time - last_ai_check < 120:
                        logger.info(f"⏰ {asset_name} - 2 daqiqa o'tmagan, keyingi loopda")
                        continue

                    logger.info(f"🚀 {asset_name} - AI SO'ROVI BOSHLANMOQDA...")
                    
                    net_profit = 0
                    should_close = False
                    close_reason = ""
                    ai_decision = {} 


                    try:
                        # Indicators ni olish
                        historical_prices = await api.get_historical_prices(epic, "MINUTE", 30)
                        indicators = calculate_indicators(historical_prices) if historical_prices else {}
                        
                        # Savdo xarajatlarini hisoblash
                        trading_costs = calculate_trading_costs(current_prices, direction)
                        
                        # NET profit hisoblash
                        current_profit = (current_price - open_price) / open_price if direction == "BUY" else (open_price - current_price) / open_price
                        net_profit = current_profit - trading_costs["total_entry_cost"]
                        
                        # Dynamic AI qarori
                        ai_decision = await get_dynamic_ai_trailing_decision(
                            asset_name, direction, open_price, current_price, indicators, deal_id, current_prices
                        )
                        
                        # Position ma'lumotlarini yangilash
                        ai_trailing_positions[deal_id] = {
                            'last_ai_check': current_time,
                            'current_tp': ai_decision.get('take_profit_price'),
                            'net_tp': ai_decision.get('net_take_profit_percent'),
                            'confidence': ai_decision.get('confidence')
                        }
                        
                        # AI qarorni bajarish
                        if ai_decision.get("action") == "CLOSE":
                            should_close = True
                            close_reason = f"AI Dynamic: {ai_decision.get('reason', '')}"
                            logger.info(f"🤖 AI CLOSE: {asset_name} | NET: {net_profit*100:+.2f}%")
                        else:
                            should_close = False
                            gross_tp = ai_decision.get('take_profit_percent', 0)
                            net_tp = ai_decision.get('net_take_profit_percent', 0)
                            confidence = ai_decision.get('confidence', 0)
                            logger.info(f"🤖 AI HOLD: {asset_name} | Joriy NET: {net_profit*100:+.2f}% | TP: {gross_tp:.1f}% (NET: {net_tp:.1f}%) | Ishonch: {confidence:.0f}%")
                            
                    except Exception as e:
                        logger.error(f"🤖 Dynamic AI trailing xato: {e}")
                        ai_decision = {"action": "FALLBACK"}
                        should_close = price_diff >= trailing_percent
                        close_reason = f"AI xato: Oddiy trailing {trailing_percent*100:.2f}%"
                        logger.info(f"🤖 AI FALLBACK: {asset_name} | Oddiy trailing: {should_close}")

                # ✅ ODDIY TRAILING STOP (MNL/AUTO/TEST) - AVVALGIDEK O'ZGARMASIN
                else:
                    should_close = price_diff >= trailing_percent
                    close_reason = f"Trailing stop: {trailing_percent*100:.2f}%"

                # ✅ YANGI LOG - NET profit bilan
                if trailing_mode == "AI" and use_ai_trailing:
                    logger.info(f"📊 {asset_name} - Trailing AI: Joriy NET {net_profit*100:+.2f}%")
                    
                    if ai_decision.get("action") == "CLOSE":
                        logger.info(f"🤖 AI CLOSE: {asset_name} | NET: {net_profit*100:+.2f}%")
                    else:
                        gross_tp = ai_decision.get('take_profit_percent', 0)
                        net_tp = ai_decision.get('net_take_profit_percent', 0)
                        logger.info(f"🤖 AI HOLD: {asset_name} | Joriy NET: {net_profit*100:+.2f}% | TP: {gross_tp:.1f}% (NET: {net_tp:.1f}%)")

                # ✅ SAVDO YOPISH - AVVALGIDEK
                if should_close:
                    logger.info(f"🚨 TRAILING STOP TRIGGERED [{trailing_mode}]")
                    logger.info(f"   📊 Aktiv: {asset_name}")
                    logger.info(f"   📈 Joriy foiz: {price_diff*100:.2f}%")
                    logger.info(f"   🔔 Sabab: {close_reason}")

                    # Pozitsiyani yopish
                    result = await api.close_position(deal_id=deal_id, direction=direction, epic=epic, size=size)
                    
                    # ✅ YANGI: Foyda/zarar bilan xabar yuborish
                    if result.get("success"):
                        try:
                            # Foyda/zarar hisoblash
                            if direction == "BUY":
                                profit_loss = (current_price - open_price) * size
                            else:  # SELL
                                profit_loss = (open_price - current_price) * size
                            
                            # Formatlash
                            if profit_loss >= 0:
                                profit_text = f"+{profit_loss:.2f} USD"
                            else:
                                profit_text = f"{profit_loss:.2f} USD"
                                
                            logger.info(f"✅ {asset_name} pozitsiyasi {profit_text} trailing stop bilan yopildi!")
                            await send_trading_status(
                                context, 
                                f"✅ {asset_name} pozitsiyasi {profit_text} trailing stop bilan yopildi!", 
                                "success"
                            )
                        except Exception as e:
                            logger.error(f"Foyda hisoblashda xato: {e}")
                            # Fallback
                            logger.info(f"✅ {asset_name} pozitsiyasi trailing stop bilan yopildi!")
                            await send_trading_status(
                                context, 
                                f"✅ {asset_name} pozitsiyasi trailing stop bilan yopildi!", 
                                "success"
                            )

        except Exception as e:
            logger.error(f"Trailing stop loop error: {e}")
            await asyncio.sleep(60)


# trading_logic.py - close_profitable_positions_loop ga qo'shamiz

async def check_stop_loss_loop(context: ContextTypes.DEFAULT_TYPE):
    """Stop Loss ni tekshirish loopi"""
    logger.info("✅ Stop Loss loop ishga tushdi.")
    
    while not stop_event.is_set():
        try:
            await asyncio.sleep(30)  # Har 30 soniyada tekshiramiz
            
            db, api = get_global_instances()
            if not db or not api:
                continue
                
            settings = await db.get_settings()
            
            # Stop Loss o'chiq bo'lsa, ishlamaymiz
            if not settings.get("stop_loss_enabled", False):
                continue
                
            stop_loss_percent = settings.get("stop_loss_percent", 2.0) / 100  # 2% -> 0.02
            
            open_positions = await api.get_open_positions()
            if not open_positions:
                continue

            for pos in open_positions:
                deal_id = pos.get("dealId") or pos.get("positionId")
                if not deal_id:
                    continue

                detail = await api.get_position_details(deal_id)
                position = detail.get("position", {})
                market = detail.get("market", {})

                asset_name = market.get("instrumentName", "Noma'lum")
                epic = market.get("epic", None)
                direction = position.get("direction", "").upper()
                open_price = position.get("level", 0)
                size = position.get("size", 0)

                current_prices = await api.get_prices(epic)
                if not current_prices:
                    continue

                # Zarar foizini hisoblash
                if direction == "BUY":
                    current_price = current_prices.get("sell", 0)
                    loss_percent = (open_price - current_price) / open_price if open_price else 0
                else:  # SELL
                    current_price = current_prices.get("buy", 0)
                    loss_percent = (current_price - open_price) / open_price if open_price else 0

                # Stop Loss shartini tekshirish
                if loss_percent >= stop_loss_percent:
                    logger.info(f"🛑 STOP LOSS TRIGGERED: {asset_name}")
                    logger.info(f"   📊 Aktiv: {asset_name}")
                    logger.info(f"   📉 Zarar foizi: {loss_percent*100:.2f}%")
                    logger.info(f"   🎯 Stop Loss: {stop_loss_percent*100:.2f}%")

                    # Pozitsiyani yopish
                    result = await api.close_position(deal_id=deal_id, direction=direction, epic=epic, size=size)
                    if result.get("success"):
                        # Foyda/zarar miqdorini hisoblaymiz
                        if direction == "BUY":
                            profit_loss = (current_price - open_price) * size
                        else:  # SELL
                            profit_loss = (open_price - current_price) * size
                        
                        profit_text = f"{profit_loss:+.2f} USD"
                        
                        logger.info(f"✅ {asset_name} pozitsiyasi Stop Loss bilan yopildi! ({profit_text})")
                        await send_trading_status(
                            context, 
                            f"🛑 {asset_name} pozitsiyasi {profit_text} Stop Loss bilan yopildi! (Zarar: {loss_percent*100:.2f}%)", 
                            "warning"
                        )

        except Exception as e:
            logger.error(f"Stop Loss loop error: {e}")
            await asyncio.sleep(60)


async def save_position(context, asset_name, asset_id, direction, size, result):
    """
    Pozitsiyani ma'lumotlar bazasiga saqlaydi
    """
    try:
        db = context.user_data.get('db')
        if db:
            settings = await db.get_settings()
            deal_ref = result.get("deal_id") or result.get("dealReference")
            
            if deal_ref:
                if "positions" not in settings:
                    settings["positions"] = {}
                
                settings["positions"][deal_ref] = {
                    "asset_name": asset_name,
                    "deal_type": direction,
                    "opened_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
                    "open_price": result.get("open_price"),
                    "deal_id": deal_ref,
                    "size": size,
                    "epic": asset_id
                }
                
                await db.save_settings(settings)
    except Exception as e:
        logger.error(f"Pozitsiyani saqlashda xato: {e}")
