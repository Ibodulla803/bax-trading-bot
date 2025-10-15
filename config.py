
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
import asyncio
from typing import Dict, Any

import os
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CAPITAL_COM_DEMO_API_KEY = os.getenv("CAPITAL_COM_DEMO_API_KEY")
CAPITAL_COM_REAL_API_KEY = os.getenv("CAPITAL_COM_REAL_API_KEY")
CAPITAL_COM_USERNAME = os.getenv("CAPITAL_COM_USERNAME")
CAPITAL_COM_PASSWORD = os.getenv("CAPITAL_COM_PASSWORD")
CHAT_ID = int(os.getenv("CHAT_ID"))

# YANGI O'ZGARISH: API kalitlari uchun maxsus parollar
CAPITAL_COM_DEMO_API_KEY_PASSWORD = os.getenv("CAPITAL_COM_DEMO_API_KEY_PASSWORD")
CAPITAL_COM_REAL_API_KEY_PASSWORD = os.getenv("CAPITAL_COM_REAL_API_KEY_PASSWORD")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"

ALLOWED_USER_ID = 252935510

# config.py faylida, faqat to'g'ri EPIC formatlarini qoldiring
ACTIVE_INSTRUMENTS: Dict[str, Dict[str, Any]] = {
    "Tesla": {"id": "TSLA"},
    "Apple": {"id": "AAPL"},
    "Nvidia": {"id": "NVDA"},
    "Coca-Cola": {"id": "KO"},
    "Bitcoin": {"id": "BTCUSD"},
    "Ethereum": {"id": "ETHUSD"},
    "Gold": {"id": "GOLD"},
    "Crude Oil": {"id": "OIL_CRUDE"},
    "Natural Gas": {"id": "NATURALGAS"},
    "USD/JPY": {"id": "USDJPY"},
    "EUR/USD": {"id": "EURUSD"}
}


# 2. NodeID larni tekshirish uchun test qilish
async def test_prices():
    api = context.user_data['capital_api']
    
    for asset, details in ACTIVE_INSTRUMENTS.items():
        prices = await api.get_prices(details["nodeId"])
        print(f"{asset} narxlari: {prices}")

# API vaqti oralig'i (resolutions)
TRADING_RESOLUTIONS = {
    "trading_loop": "MINUTE"
}

TRADE_SIGNAL_LEVELS = {
    "TEST": "TEST",
    "MNL": "MNL", 
    "WEAK": "WEAK",
    "STRONG": "STRONG"
}

TRADING_SETTINGS = {
    "min_order_size": 0.0002,
    "max_order_size": 1000,
    "stop_loss_percent": 0.05,
    "take_profit_percent": 0.1,
    "rsi_buy_level": 35,  # 35 dan past bo'lsa BUY signali
    "rsi_sell_level": 65   # 65 dan yuqori bo'lsa SELL signali
}

# Trailing mode lar
TRAILING_MODES = {
    "TEST": "TEST",
    "MNL": "MNL",
    "AUTO": "AUTO", 
    "AI": "AI"
}

# Default sozlamalar
DEFAULT_SETTINGS = {
    "demo_account_status": False,
    "real_account_status": False,
    "ai_rejection_notifications": True,
    "trailing_stop_percent": 0.0001,
    "weak_mode_fast": True,           # Tez weak rejim
    "weak_min_signals": 2,            # Minimal 2 ta signal
    "rsi_buy_level": 35,              # RSI 35 dan pastda sotib olish
    "rsi_sell_level": 65,             # RSI 65 dan yuqorida sotish
    "dynamic_instruments_loaded": False,
    
    # YANGI tugmalar uchun
    "trailing_manual_enabled": True,  # Trailing Stop manual ON/OFF
    "use_ai_trailing_stop": False,    # AI Trailing Stop ON/OFF
    "trade_signal_level": "STRONG",      
    "trailing_mode": "AUTO",
    "trade_signal_ai_enabled": False, # False (OFF) yoki True (ON)
  
    "enabled_indicators": {
        "ema": True,
        "rsi": True, 
        "macd": True,
        "bollinger": True,
        "trend": True
    },

    # Aktivlar sozlamalari
    "trade_amount_per_asset": {
        asset: 100.0 for asset in ACTIVE_INSTRUMENTS.keys()
    },
    "max_trades_per_asset": {
        asset: 10 for asset in ACTIVE_INSTRUMENTS.keys()
    },
    "buy_sell_status_per_asset": {
        asset: {"buy": True, "sell": True, "active": True}
        for asset in ACTIVE_INSTRUMENTS.keys()
    },
    
    # Pozitsiyalar va risk boshqaruvi
    "positions": {},
    "chat_id": None,
    "current_asset": None,
    "current_action": None,
    "consecutive_losses_per_asset": {
        asset: 0 for asset in ACTIVE_INSTRUMENTS.keys()
    },
    "max_consecutive_losses": 3,
    "max_risk_per_trade_percent": 0.01,
    "max_total_risk_percent": 0.05,
    
    # YANGI: Auto savdo sozlamalari
    "auto_trading_enabled": True,
    "current_trades_per_asset": {
        asset: 0 for asset in ACTIVE_INSTRUMENTS.keys()
    }
}
# Botning suhbat holatlari
(
    SELECT_ACCOUNT_TYPE,
    MAIN_MENU,
    ASSETS_MENU,
    PRICE_INPUT,
    MAX_TRADES_INPUT,           # Aktivlar uchun maksimal savdolar
    SELL_BUY_MENU,
    SETTINGS_MENU,
    MANUAL_TRADE_MENU,
    MANUAL_TRADE_ACTION,
    MANUAL_AMOUNT_INPUT,
    CURRENT_TRADE_MENU,
    INDICATORS_MENU,
    MAX_TRADES_COUNT_INPUT      # ✅ YANGI: Umumiy faol savdolar soni
) = range(13)  # ⬅️ 13 ga o'zgartiring

# Botning ishini boshqarish uchun global o'zgaruvchi
stop_event = asyncio.Event()

# Reply klaviaturalar (ekranning pastida chiqadi)
start_menu_keyboard = ReplyKeyboardMarkup(
    [["Demo Hisob", "Real Hisob"]], resize_keyboard=True
)

main_menu_keyboard = ReplyKeyboardMarkup(
    [
        ["Aktiv shartlari", "Joriy savdolar"],
        ["Manual savdo", "Aktivlar"], 
        ["Joriy narxlar", "Narx belgilash"],
        ["Savdolar soni", "SELL & BUY"],
        ["Sozlamalar", "Indikatorlar"],  # ⬅️ "Tekshiruv" o'rniga "Indikatorlar"
        ["Tekshiruv"]  # ⬅️ Yangi qator
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

def get_asset_name_by_epic(epic):
    for name, data in ACTIVE_INSTRUMENTS.items():
        if data.get("id") == epic:
            return name
    return epic  # topilmasa, ID qaytariladi

def get_assets_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    """Aktivlarni yoqish/o'chirish tugmalari"""
    buttons = []
    for key in ACTIVE_INSTRUMENTS.keys():
        status = settings.get("buy_sell_status_per_asset", {}).get(key, {}).get("active", True)
        status_text = '✅ ON' if status else '❌ OFF'
        buttons.append([InlineKeyboardButton(f"{key} ({status_text})", callback_data=f"asset_{key}")])
    buttons.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(buttons)


# config.py fayliga quyidagi funksiyalarni qo'shing

def get_trailing_mode_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    """Trailing mode tanlash uchun klaviatura"""
    current_mode = settings.get("trailing_mode", "MNL")
    
    keyboard = [
        [InlineKeyboardButton(f"🔄 AUTO {'✅' if current_mode == 'AUTO' else ''}", callback_data="trailing_mode_AUTO")],
        [InlineKeyboardButton(f"👤 MNL {'✅' if current_mode == 'MNL' else ''}", callback_data="trailing_mode_MNL")],
        [InlineKeyboardButton(f"🤖 AI {'✅' if current_mode == 'AI' else ''}", callback_data="trailing_mode_AI")],
        [InlineKeyboardButton(f"🧪 TEST {'✅' if current_mode == 'TEST' else ''}", callback_data="trailing_mode_TEST")],
        [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_settings")]
    ]
    
    return InlineKeyboardMarkup(keyboard)

def get_trade_signal_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    """Trade signal darajasini tanlash uchun klaviatura"""
    current_level = settings.get("trade_signal_level", "MNL")
    
    keyboard = [
        [InlineKeyboardButton(f"🟡 WEAK {'✅' if current_level == 'WEAK' else ''}", callback_data="signal_level_WEAK")],
        [InlineKeyboardButton(f"🟢 STRONG {'✅' if current_level == 'STRONG' else ''}", callback_data="signal_level_STRONG")],
        [InlineKeyboardButton(f"👤 MNL {'✅' if current_level == 'MNL' else ''}", callback_data="signal_level_MNL")],
        [InlineKeyboardButton(f"🧪 TEST {'✅' if current_level == 'TEST' else ''}", callback_data="signal_level_TEST")],
        [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_settings")]
    ]
    
    return InlineKeyboardMarkup(keyboard)


def get_indicators_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    """Indikatorlarni yoqish/o'chirish tugmalari"""
    enabled_indicators = settings.get("enabled_indicators", {})
    
    # Default qiymatlar agar bo'lmasa
    default_indicators = {
        "ema": True, 
        "rsi": True,
        "macd": True,
        "bollinger": True,
        "trend": True
    }
    
    # Har bir indikator uchun tugma
    keyboard = [
        [InlineKeyboardButton(f"📈 EMA {'✅' if enabled_indicators.get('ema', default_indicators['ema']) else '❌'}", callback_data="toggle_ema")],
        [InlineKeyboardButton(f"📊 RSI {'✅' if enabled_indicators.get('rsi', default_indicators['rsi']) else '❌'}", callback_data="toggle_rsi")],
        [InlineKeyboardButton(f"🔄 MACD {'✅' if enabled_indicators.get('macd', default_indicators['macd']) else '❌'}", callback_data="toggle_macd")],
        [InlineKeyboardButton(f"📉 Bollinger Bands {'✅' if enabled_indicators.get('bollinger', default_indicators['bollinger']) else '❌'}", callback_data="toggle_bollinger")],
        [InlineKeyboardButton(f"🚀 Trend Analysis {'✅' if enabled_indicators.get('trend', default_indicators['trend']) else '❌'}", callback_data="toggle_trend")],
        [
            InlineKeyboardButton("🔙 Sozlamalar", callback_data="back_to_settings"),  # ⬅️ Sozlamalarga qaytish
            InlineKeyboardButton("🏠 Asosiy menyu", callback_data="back_to_main_menu")  # ⬅️ Asosiy menyuga
        ]
    ]
    
    return InlineKeyboardMarkup(keyboard)


# main.py dagi get_settings_keyboard funksiyasini yangilang

# config.py - get_settings_keyboard funksiyasiga qo'shamiz

def get_settings_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    demo_status = "✅ ON" if settings.get("demo_account_status", False) else "❌ OFF"
    real_status = "✅ ON" if settings.get("real_account_status", False) else "❌ OFF"
    auto_trading_status = "✅ ON" if settings.get("auto_trading_enabled", True) else "❌ OFF"
    ai_trail_status = "✅ ON" if settings.get("use_ai_trailing_stop", False) else "❌ OFF"
    trailing_stop = settings.get("trailing_stop_percent", 0.10) * 100
    
    # ✅ YANGI: Faol savdolar soni
    max_trades = settings.get("max_trades_count", 3)
    max_trades_text = f"Faol savdolar: {max_trades} ta"
    
    # Trade Signal darajasi
    trade_signal_level = settings.get("trade_signal_level", "MNL")
    trade_signal_text = f"Trade signal: [{trade_signal_level.upper()}]"
    
    # Trailing Mode
    trailing_mode = settings.get("trailing_mode", "MNL")
    trailing_mode_text = f"Trailing Mode: [{trailing_mode.upper()}]"
    
    # Yangi "Trade Signal AI" tugmasini qo'shamiz
    trade_signal_ai_enabled = settings.get("trade_signal_ai_enabled", False)
    trade_signal_ai_text = f"Trade signal AI: [{'ON' if trade_signal_ai_enabled else 'OFF'}]"
    
    keyboard = [
        [InlineKeyboardButton(f"🤖 Auto Savdo: {auto_trading_status}", callback_data="toggle_auto_trading")],
        [InlineKeyboardButton(f"📊 Demo hisob: {demo_status}", callback_data="toggle_demo")],
        [InlineKeyboardButton(f"🏦 Real hisob: {real_status}", callback_data="toggle_real")],
        [InlineKeyboardButton(f"🔺 Trailing Stop: {trailing_stop:.1f}%", callback_data="set_trailing_stop")],
        [InlineKeyboardButton(f"📈 {max_trades_text}", callback_data="set_max_trades")],  # ✅ YANGI TUGMA
        [InlineKeyboardButton(trailing_mode_text, callback_data="trailing_mode_menu")],
        [InlineKeyboardButton(f"🧠 AI Trailing: {ai_trail_status}", callback_data="toggle_ai_trailing_stop")],
        [InlineKeyboardButton("💰 Hisob balansi", callback_data="check_balances")],
        [
            InlineKeyboardButton(trade_signal_text, callback_data="trade_signal_menu"),
            InlineKeyboardButton(trade_signal_ai_text, callback_data="toggle_trade_signal_ai_enabled"),
        ],
        [InlineKeyboardButton("⬅️ Ortga", callback_data="back_to_main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_sell_buy_keyboard(settings: Dict) -> InlineKeyboardMarkup:
    keyboard = []
    for asset in ACTIVE_INSTRUMENTS.keys():
        status = settings.get("buy_sell_status_per_asset", {}).get(asset, {})
        sell_status = "ON" if status.get("sell", True) else "OFF"
        buy_status = "ON" if status.get("buy", True) else "OFF"
        
        keyboard.append([
            InlineKeyboardButton(f"{asset} - SELL: {sell_status}", callback_data=f"toggle_sell_{asset}"),
            InlineKeyboardButton(f"{asset} - BUY: {buy_status}", callback_data=f"toggle_buy_{asset}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_price_keyboard(current_instruments: Dict) -> InlineKeyboardMarkup:
    keyboard = []
    for asset in current_instruments.keys():
        keyboard.append([InlineKeyboardButton(asset, callback_data=f"set_price_{asset}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_max_trades_keyboard(current_instruments: Dict) -> InlineKeyboardMarkup:
    keyboard = []
    for asset in current_instruments.keys():
        keyboard.append([InlineKeyboardButton(asset, callback_data=f"set_max_trades_{asset}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_to_main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_max_trades_options_keyboard(asset: str) -> InlineKeyboardMarkup:
    options = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    keyboard = [[InlineKeyboardButton(str(num), callback_data=f"set_max_{asset}_{num}") for num in options[:5]],
                [InlineKeyboardButton(str(num), callback_data=f"set_max_{asset}_{num}") for num in options[5:]],
                [InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_to_main_menu")]]
    return InlineKeyboardMarkup(keyboard)

# YANGI FUNKSIYALAR UCHUN INLINE KLAVIATURALAR
def get_manual_trade_assets_keyboard():
    keyboard = []
    for asset in ACTIVE_INSTRUMENTS.keys():
        keyboard.append([InlineKeyboardButton(asset, callback_data=f'manual_trade_asset_{asset}')])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data='back_to_main_menu')])
    return InlineKeyboardMarkup(keyboard)

def get_manual_trade_options_keyboard(asset_name):
    keyboard = [
        [InlineKeyboardButton("BUY", callback_data=f'manual_buy_{asset_name}'),
         InlineKeyboardButton("SELL", callback_data=f'manual_sell_{asset_name}')],
        [InlineKeyboardButton("🔙 Orqaga", callback_data='back_to_main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Graceful shutdown uchun hodisa obyektini yaratish
stop_event = asyncio.Event()