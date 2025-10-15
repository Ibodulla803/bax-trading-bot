# trading_logic.py
import asyncio
import logging
import datetime
import random
import numpy as np
import pandas as pd
import pytz
import uuid
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
ai_trailing_cache = {}
AI_CACHE_DURATION = 300  # 5 minut
MIN_PROFIT_FOR_AI = 0.005  # 0.5% - AI ga so'rov yuborish uchun minimal foyda


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


# trading_logic.py - start_trading_loops funksiyasiga log qo'shamiz

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

            logger.debug("API'dan olingan narx obyekti keys=%s", list(price.keys()))

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

async def send_hourly_report(context: ContextTypes.DEFAULT_TYPE):
    """Har soat faol aktivlar haqida hisobot yuborish"""
    try:
        db, api = get_global_instances()
        if not db or not api:
            return

        settings = await db.get_settings()
        chat_id = settings.get("chat_id") or CHAT_ID
        
        if not chat_id:
            return

        # Faol aktivlarni tekshirish
        message = "🕐 **Soatlik Hisobot**\n\n"
        has_active_trades = False

        for asset_name, details in ACTIVE_INSTRUMENTS.items():
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
                
                message += f"📊 **{asset_name}**\n"
                message += f"   Sotish: ${sell_price:.2f}\n"
                message += f"   Sotib olish: ${buy_price:.2f}\n"
                message += f"   Spread: {spread_percent:.2f}%\n\n"
                has_active_trades = True

        if has_active_trades:
            # Ochiq pozitsiyalar soni
            open_positions = await api.get_open_positions()
            positions_count = len(open_positions) if open_positions else 0
            
            message += f"🔓 **Ochiq savdolar:** {positions_count} ta\n"
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

            # Har bir aktivni tekshirish
            for asset, details in ACTIVE_INSTRUMENTS.items():
                logger.info(f"📊 {asset} tekshirilmoqda...")

                asset_settings = settings.get("buy_sell_status_per_asset", {}).get(asset, {})
                if not asset_settings.get("active", True):
                    continue
                if not is_market_open(asset):
                    continue

                # ✅ YANGI: Aktivda ochiq savdo yo'nalishini tekshirish
                current_direction = None
                if open_positions:
                    for pos in open_positions:
                        pos_epic = pos.get('epic')
                        pos_asset_name = get_asset_name_by_epic(pos_epic) if pos_epic else None
                        if pos_asset_name == asset:
                            current_direction = pos.get('direction', '').upper()
                            logger.info(f"📊 {asset} da {current_direction} savdo ochiq")
                            break

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
                    # ✅ YANGI: Agar ochiq savdo bo'lsa va yo'nalish bir xil bo'lmasa, davom etamiz
                    if current_direction and current_direction == trade_signal:
                        logger.info(f"⏸️ {asset} da {current_direction} savdo ochiq. {trade_signal} signali o'tkazib yuborildi.")
                        continue

                    logger.info(f"🎯 {asset} uchun {trade_signal} SIGNAL TOPILDI!")
                     
                    # AI tasdiqlash bloki
                    if ai_enabled and signal_level != "TEST":
                        # To'g'ri resolution va son bilan ma'lumot oling
                        resolutions_to_try = ["HOUR", "DAY", "MINUTE"]
                        historical_prices = []
                        for res in resolutions_to_try:
                            historical_prices = await api.get_historical_prices(details['id'], res, 50)
                            if historical_prices and len(historical_prices) >= 20:
                                break

                        indicators = calculate_indicators(historical_prices or [])

                        
                        # ✅ AI'dan tasdiqlashni so'rash
                        ai_approval = await get_ai_approval(asset, trade_signal, prices, indicators or {})

                        if not ai_approval or not isinstance(ai_approval, dict) or ai_approval.get("decision") != "APPROVE":
                            # Agar savdo rad etilsa
                            reason = ai_approval.get('reason', 'Noma‘lum sabab')
                            logger.warning(f"[{asset}] savdosi AI tomonidan rad etildi yoki javob noto‘g‘ri. Sabab: {reason}")
                            
                            # ✅ Telegramga AI bergan sababni yuborish
                            await send_trading_status(context, f"❌ [AI] {asset} savdosi rad etildi. Sabab: {reason}", "warning")
                            
                            continue
                        else:
                            # Agar savdo tasdiqlansa
                            logger.info(f"[{asset}] savdosi AI tomonidan tasdiqlandi: {trade_signal}")
                            await send_trading_status(context, f"✅ [AI] {asset} savdosi tasdiqlandi: {trade_signal.upper()}", "success")

                    
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

    while not stop_event.is_set():
        try:
            await asyncio.sleep(30)
            
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
                ai_approval = None  # ✅ FIX: ai_approval ni default qiymat bilan ishga tushiramiz

                # ✅ YANGI: OPTIMALLASHTIRILGAN AI TRAILING STOP
                if trailing_mode == "AI" and use_ai_trailing:
                    # ✅ 1. MINIMAL FOYDA TEKSHIRISH
                    if price_diff < MIN_PROFIT_FOR_AI:
                        should_close = False
                        close_reason = f"Foyda {price_diff*100:.2f}% < minimal {MIN_PROFIT_FOR_AI*100:.2f}%"
                        logger.debug(f"🤖 {asset_name} - {close_reason}")
                        ai_approval = {"decision": "REJECT", "reason": close_reason}  # ✅ FIX: ai_approval ni to'ldiramiz
                    
                    else:
                        # ✅ 2. CACHE TEKSHIRISH
                        cache_key = f"{asset_name}_{direction}_{int(price_diff*1000)}"  # 0.1% precision
                        
                        current_time = time.time()
                        if (cache_key in ai_trailing_cache and 
                            current_time - ai_trailing_cache[cache_key]['timestamp'] < AI_CACHE_DURATION):
                            
                            # ✅ CACHE DAN OLISH
                            ai_approval = ai_trailing_cache[cache_key]['approval']
                            logger.debug(f"🤖 {asset_name} - AI qaror cache dan olindi")
                            
                        else:
                            # ✅ YANGI SO'ROV YUBORISH
                            try:
                                ai_approval = await get_ai_trailing_approval(
                                    asset_name,
                                    direction,
                                    open_price,
                                    current_price,
                                    price_diff
                                )
                                
                                # ✅ CACHE GA SAQLASH
                                ai_trailing_cache[cache_key] = {
                                    'approval': ai_approval,
                                    'timestamp': current_time
                                }
                                logger.debug(f"🤖 {asset_name} - Yangi AI so'rovi yuborildi")
                                
                            except Exception as e:
                                logger.error(f"🤖 AI so'rovida xato: {e}")
                                # ✅ FALLBACK: Oddiy trailing stop
                                should_close = price_diff >= trailing_percent
                                close_reason = f"AI xato: Oddiy trailing {trailing_percent*100:.2f}%"
                                ai_approval = {"decision": "REJECT", "reason": f"API xato: {e}"}
                        
                        # ✅ AI QARORINI QAYTA ISHLASH (faqat ai_approval mavjud bo'lsa)
                        if ai_approval:
                            should_close = ai_approval.get("decision") == "APPROVE"
                            close_reason = f"AI trailing: {ai_approval.get('reason', '')}"
                        else:
                            # Agar ai_approval hali ham None bo'lsa, oddiy trailing stop ishlatamiz
                            should_close = price_diff >= trailing_percent
                            close_reason = f"Trailing stop: {trailing_percent*100:.2f}%"

                else:
                    # ✅ ODDIY TRAILING STOP (AUTO/MNL)
                    should_close = price_diff >= trailing_percent
                    close_reason = f"Trailing stop: {trailing_percent*100:.2f}%"

                # ✅ YANGI: BATAFSIL LOGLAR
                if trailing_mode == "AI" and use_ai_trailing:
                    logger.info(f"📊 {asset_name} - Trailing AI: Joriy {price_diff*100:.2f}%")
                    if ai_approval:  # ✅ FIX: ai_approval mavjudligini tekshiramiz
                        if should_close:
                            logger.info(f"🤖 AI qaror: APPROVE - {ai_approval.get('reason', '')}")
                        else:
                            logger.info(f"🤖 AI qaror: REJECT - {ai_approval.get('reason', 'Foyda yetarli emas' if price_diff < MIN_PROFIT_FOR_AI else ai_approval.get('reason', ''))}")
                    else:
                        logger.info(f"🤖 AI qaror: REJECT - AI qaror mavjud emas")
                else:
                    logger.info(f"📊 {asset_name} - Trailing {trailing_mode}: Joriy {price_diff*100:.2f}% < Talab {trailing_percent*100:.2f}%")

                if should_close:
                    logger.info(f"🚨 TRAILING STOP TRIGGERED [{trailing_mode}]")
                    logger.info(f"   📊 Aktiv: {asset_name}")
                    logger.info(f"   📈 Joriy foiz: {price_diff*100:.2f}%")
                    logger.info(f"   🎯 Talab foiz: {trailing_percent*100:.2f}%")
                    logger.info(f"   🔔 Sabab: {close_reason}")

                    # Pozitsiyani yopish
                    result = await api.close_position(deal_id=deal_id, direction=direction, epic=epic, size=size)
                    if result.get("success"):
                        logger.info(f"✅ {asset_name} pozitsiyasi trailing stop bilan yopildi!")
                        await send_trading_status(context, f"{asset_name} pozitsiyasi trailing stop bilan yopildi!", "success")

        except Exception as e:
            logger.error(f"Trailing stop loop error: {e}")
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
