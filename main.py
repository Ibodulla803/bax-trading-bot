# main.py
import os
import sys

# Bax papkasini import yo'liga qo'shish
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))

import asyncio
import logging
import datetime
import pytz
from aiohttp.client_exceptions import ClientConnectionError
import re
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler,
    CallbackContext,
)

# Absolute importlar
from config import (
    TELEGRAM_TOKEN, CAPITAL_COM_DEMO_API_KEY, CAPITAL_COM_REAL_API_KEY,
    CAPITAL_COM_USERNAME, CAPITAL_COM_PASSWORD, CHAT_ID,
    CAPITAL_COM_DEMO_API_KEY_PASSWORD, INDICATORS_MENU, CAPITAL_COM_REAL_API_KEY_PASSWORD,
    start_menu_keyboard, main_menu_keyboard, get_assets_keyboard, get_sell_buy_keyboard,
    get_price_keyboard, get_max_trades_keyboard, get_settings_keyboard, get_max_trades_options_keyboard,
    ACTIVE_INSTRUMENTS,
    DEFAULT_SETTINGS,
    get_manual_trade_assets_keyboard,
    get_manual_trade_options_keyboard,
    get_indicators_keyboard,
    get_asset_name_by_epic,
    ALLOWED_USER_ID
)
from trading_logic import (
    refresh_positions, 
    close_profitable_positions_loop, 
    set_global_instances,
    start_trading_loops,
    trading_logic_loop, 
    calculate_mnl_signals,
)
from db import InMemoryDB
from capital_api import CapitalComAPI, CapitalAPIError

# Conversation handler holatlari
SELECT_ACCOUNT_TYPE, MAIN_MENU, ASSETS_MENU, PRICE_INPUT, MAX_TRADES_INPUT, SELL_BUY_MENU, SETTINGS_MENU, MANUAL_TRADE_MENU, MANUAL_TRADE_ACTION, MANUAL_AMOUNT_INPUT, CURRENT_TRADE_MENU = range(11)



from functools import wraps

def only_me(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        if update.effective_user.id != 252935510:  # O'zingizni ID
            await update.message.reply_text("⛔️ Sizga ruxsat yo‘q!")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# =====================================================================================
# =====================================================================================
logger = logging.getLogger(__name__)
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Yangi, filtrlarsiz konfiguratsiya
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot_full.log", encoding='utf-8'),
        logging.StreamHandler()  # Konsol uchun
    ]
)

# Keraksiz loglarni bloklash
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
# Qolgan barcha LogFilter va FilteredStreamHandler klasslarini
# vaqtincha o'chirib turing yoki kommentariyaga oling.
# Ular sizga hozircha kerak emas.

# =====================================================================================
# Asosiy bot funksiyalari
# =====================================================================================
async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log filterini o'zgartirish uchun komanda"""
    text = update.message.text.lower()
    
    if 'log all' in text:
        # Handler ni o'zgartirish
        for handler in logging.root.handlers:
            if isinstance(handler, FilteredStreamHandler):
                handler.filter_type = 'all'
        await update.message.reply_text("🔍 Barcha loglar ko'rsatilmoqda")
    
    elif 'log trade' in text:
        for handler in logging.root.handlers:
            if isinstance(handler, FilteredStreamHandler):
                handler.filter_type = 'trade'
        await update.message.reply_text("💰 Faqat savdo loglari ko'rsatilmoqda")
    
    elif 'log important' in text:
        for handler in logging.root.handlers:
            if isinstance(handler, FilteredStreamHandler):
                handler.filter_type = 'important'
        await update.message.reply_text("✅ Faqat muhim loglar ko'rsatilmoqda")


async def check_auto_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto savdo holatini tekshirish"""
    try:
        # Trading loop ishlayotganini tekshirish
        if 'trading_task_instance' in context.user_data:
            status = "✅ ISHLAYAPTI"
        else:
            status = "❌ TO'XTAGAN"
        
        await update.message.reply_text(
            f"Auto savdo holati: {status}\n"
            f"Log fayli: bot.log\n"
            f"Sozlamalar: /settings"
        )
    except Exception as e:
        await update.message.reply_text(f"Xato: {str(e)}")




async def debug_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """API dan qaytgan pozitsiya ma'lumotlarini ko'rish"""
    api = context.user_data.get('capital_api')
    if not api:
        await update.message.reply_text("API topilmadi")
        return MAIN_MENU
    
    try:
        positions = await api.get_open_positions()
        
        if not positions:
            await update.message.reply_text("Ochiq pozitsiyalar yo'q")
            return MAIN_MENU
            
        message = "🔍 API dan qaytgan pozitsiyalar:\n\n"
        
        for i, pos in enumerate(positions, 1):
            message += f"#{i}:\n"
            message += f"• Instrument: {pos.get('instrumentName', 'N/A')}\n"
            message += f"• Size: {pos.get('size', 'N/A')}\n"
            message += f"• Direction: {pos.get('direction', 'N/A')}\n"
            message += f"• Deal ID: {pos.get('dealId', 'N/A')}\n"
            
            # Barcha mavjut keylarni ko'rsatish
            for key, value in pos.items():
                if key not in ['instrumentName', 'size', 'direction', 'dealId']:
                    message += f"• {key}: {value}\n"
            
            message += "\n"
            
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"Xato: {str(e)}")
    
    return MAIN_MENU

async def debug_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """API debug funksiyasi"""
    api = context.user_data.get('capital_api')
    if not api:
        await update.message.reply_text("API topilmadi")
        return
    
    try:
        result = await api.debug_positions()
        await update.message.reply_text(f"Debug natijasi: {result}")
    except Exception as e:
        await update.message.reply_text(f"Debugda xato: {e}")

async def debug_states(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hozirgi state ni ko'rsatish"""
    try:
        # Conversation handler dan state ni olish
        current_state = await context.application.persistence.get_conversation(
            update.effective_chat.id, 
            update.effective_chat.id
        )
        
        # User_data dagi state ni tekshirish
        user_state = context.user_data.get('state', 'No state in user_data')
        
        message = f"🔍 Debug ma'lumotlari:\n\n"
        message += f"• Conversation state: {current_state}\n"
        message += f"• User_data state: {user_state}\n"
        message += f"• Chat ID: {update.effective_chat.id}\n"
        message += f"• User ID: {update.effective_user.id}\n"
        
        # User_data dagi boshqa muhim ma'lumotlar
        if 'manual_asset' in context.user_data:
            message += f"• Manual asset: {context.user_data['manual_asset']}\n"
        if 'manual_deal_type' in context.user_data:
            message += f"• Manual deal type: {context.user_data['manual_deal_type']}\n"
        if 'current_asset' in context.user_data:
            message += f"• Current asset: {context.user_data['current_asset']}\n"
            
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"Debugda xato: {str(e)}")
@only_me
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Botni boshlash uchun /start buyrug'i."""
    user_id = str(update.effective_user.id)
    if 'db' not in context.user_data:
        context.user_data['db'] = InMemoryDB(user_id)

    db = context.user_data['db']
    settings = await db.get_settings()
    if not settings:
        settings = DEFAULT_SETTINGS.copy()
        settings["chat_id"] = CHAT_ID
        await db.save_settings(settings)
    # Global instancelarni o'rnatish
    if 'capital_api' in context.user_data:
        set_global_instances(db, context.user_data['capital_api'])
        logger.info("✅ Global instancelar start komandasida sozlandi.")

    await update.message.reply_text(
        "Xush kelibsiz! Botdan foydalanish uchun hisob turini tanlang:",
        reply_markup=start_menu_keyboard
    )
    return SELECT_ACCOUNT_TYPE


# main.py ga test komandasi qo'shing
async def test_epics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha EPIC larni test qilish"""
    api = context.user_data.get('capital_api')
    
    message = "🔍 EPIC Test Natijalari:\n\n"
    
    for asset_name, asset_data in ACTIVE_INSTRUMENTS.items():
        epic = asset_data["id"]
        
        # Joriy narxlarni tekshirish
        prices = await api.get_prices(epic)
        
        # Tarixiy ma'lumotlarni tekshirish
        history = await api.get_historical_prices(epic, "HOUR", 5)
        
        if prices and prices.get("buy", 0) > 0:
            message += f"✅ {asset_name}\n"
            message += f"   EPIC: {epic}\n"
            message += f"   Narx: {prices['buy']:.2f} / {prices['sell']:.2f}\n"
            message += f"   Tarix: {len(history)} ta\n"
        else:
            message += f"❌ {asset_name}\n"
            message += f"   EPIC: {epic}\n"
            message += f"   Narx: TOPILMADI\n"
            message += f"   Tarix: {len(history)} ta\n"
        
        message += "\n"
    
    await update.message.reply_text(message)


async def load_dynamic_instruments(context: ContextTypes.DEFAULT_TYPE):
    """
    Dynamic ravishda EPIC formatlarini yuklash
    """
    try:
        api = context.user_data.get('capital_api')
        if not api:
            logger.warning("API topilmadi, dynamic instrumentlar yuklanmadi")
            return

     
        
        # config.py dagi ACTIVE_INSTRUMENTS ni yangilash
        from config import ACTIVE_INSTRUMENTS
        ACTIVE_INSTRUMENTS.clear()
        ACTIVE_INSTRUMENTS.update(dynamic_instruments)
        
        # Settingsga saqlash
        db = context.user_data.get('db')
        if db:
            settings = await db.get_settings()
            settings["dynamic_instruments_loaded"] = True
            settings["active_instruments"] = dynamic_instruments
            await db.save_settings(settings)
        
        logger.info("✅ Dynamic instrumentlar muvaffaqiyatli yuklandi")
        
    except Exception as e:
        logger.error(f"Dynamic instrumentlar yuklashda xato: {e}")

async def toggle_indicator_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Indikatorlarni yoqish/o'chirish"""
    query = update.callback_query
    await query.answer()
    
    db = context.user_data.get('db')
    if not db:
        await query.answer(text="Ichki xato: DB topilmadi.", show_alert=True)
        return INDICATORS_MENU  # ⬅️ INDICATORS_MENU ga qaytish
        
    settings = await db.get_settings()
    data = query.data
    
    # enabled_indicators mavjudligini tekshirish
    if "enabled_indicators" not in settings:
        settings["enabled_indicators"] = {
            "ema": True, "rsi": True, "macd": True, 
            "bollinger": True, "trend": True
        }
    
    # Toggle qilish
    indicator = data.replace("toggle_", "")
    current_value = settings["enabled_indicators"].get(indicator, True)
    settings["enabled_indicators"][indicator] = not current_value
    
    status = "✅ YOQILDI" if settings["enabled_indicators"][indicator] else "❌ O'CHIRILDI"
    await query.answer(text=f"{indicator.upper()} {status}")
    
    await db.save_settings(settings)
    await query.edit_message_reply_markup(get_indicators_keyboard(settings))
    return INDICATORS_MENU  # ⬅️ INDICATORS_MENU ga qaytish


async def back_to_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sozlamalar menyusiga qaytish"""
    query = update.callback_query
    await query.answer()
    
    db = context.user_data.get('db')
    settings = await db.get_settings()
    
    await query.edit_message_text(
        "Bot sozlamalarini o'zgartirish uchun kerakli parametrlarni tanlang:",
        reply_markup=get_settings_keyboard(settings)
    )
    return SETTINGS_MENU

async def handle_account_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Hisob turini (Demo yoki Real) tanlash va API tekshiruvini boshqaradi."""
    text = update.message.text
    db = context.user_data.get('db')

    if text == "Demo Hisob":
        api = CapitalComAPI(
            CAPITAL_COM_USERNAME,
            CAPITAL_COM_PASSWORD,
            demo_api_key=CAPITAL_COM_DEMO_API_KEY,
            demo_api_key_password=CAPITAL_COM_DEMO_API_KEY_PASSWORD,
            real_api_key=None,
            real_api_key_password=None,
            account_type="demo"
        )
        context.user_data['capital_api'] = api

        login_result = await api.login()
        if login_result['success']:
            settings = await db.get_settings()
            settings["demo_account_status"] = True
            settings["real_account_status"] = False
            await db.save_settings(settings)

            await setup_bot_tasks(context)
            await update.message.reply_text("✅ Demo hisobga muvaffaqiyatli kirdingiz!", reply_markup=main_menu_keyboard)
            return MAIN_MENU
        else:
            await update.message.reply_text(f"Demo hisobga kirishda xato: {login_result.get('message', 'Noma\'lum xato')}")
            return SELECT_ACCOUNT_TYPE
    elif text == "Real Hisob":
        api = CapitalComAPI(
            CAPITAL_COM_USERNAME,
            CAPITAL_COM_PASSWORD,
            demo_api_key=None,
            demo_api_key_password=None,
            real_api_key=CAPITAL_COM_REAL_API_KEY,
            real_api_key_password=CAPITAL_COM_REAL_API_KEY_PASSWORD,
            account_type="real"
        )
        context.user_data['capital_api'] = api

        login_result = await api.login()
        if login_result['success']:
            settings = await db.get_settings()
            settings["demo_account_status"] = False
            settings["real_account_status"] = True
            await db.save_settings(settings)

            await setup_bot_tasks(context)
            await update.message.reply_text("⚠️ Real hisobga muvaffaqiyatli kirdingiz!", reply_markup=main_menu_keyboard)
            return MAIN_MENU
        else:
            await update.message.reply_text(f"Real hisobga kirishda xato: {login_result.get('message', 'Noma\'lum xato')}")
            return SELECT_ACCOUNT_TYPE
    elif text == "Indikatorlar":
        return await indicators_menu(update, context)
    elif text == "Tekshiruv":
        api = CapitalComAPI(
            CAPITAL_COM_USERNAME,
            CAPITAL_COM_PASSWORD,
            demo_api_key=CAPITAL_COM_DEMO_API_KEY,
            demo_api_key_password=CAPITAL_COM_DEMO_API_KEY_PASSWORD,
            real_api_key=CAPITAL_COM_REAL_API_KEY,
            real_api_key_password=CAPITAL_COM_REAL_API_KEY_PASSWORD
        )
        context.user_data['capital_api'] = api
        await check_status(update, context)
        return SELECT_ACCOUNT_TYPE
    else:
        await update.message.reply_text("Noto'g'ri tanlov. Iltimos, Demo, Real hisobni tanlang yoki Tekshiruv tugmasini bosing.")
        return SELECT_ACCOUNT_TYPE

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asosiy menyu tugmalarini boshqaradi."""
    text = update.message.text
    db = context.user_data.get('db')

    if not db:
        await update.message.reply_text("Iltimos, avval /start buyrug'i bilan botni qayta ishga tushiring.")
        return ConversationHandler.END

    api = context.user_data.get('capital_api')
    if not api:
        await update.message.reply_text("API topilmadi. Iltimos, /start buyrug'i bilan botni qayta ishga tushiring va hisob turini tanlang.")
        return ConversationHandler.END

    settings = await db.get_settings()

    if text == "Aktiv shartlari":
        return await get_active_conditions(update, context)
    elif text == "Joriy savdolar":
        return await get_trading_status(update, context)
    elif text == "Manual savdo":
        return await manual_trade_menu(update, context)
    elif text == "Aktivlar":
        await update.message.reply_text("Aktivlar ro'yxati:", reply_markup=get_assets_keyboard(settings))
        return ASSETS_MENU
    elif text == "Joriy narxlar":
        await get_current_prices(update, context)
        return MAIN_MENU
    elif text == "Narx belgilash":
        await update.message.reply_text(
            "Qaysi aktiv uchun narx belgilashni xohlaysiz?",
            reply_markup=get_price_keyboard(ACTIVE_INSTRUMENTS)
        )
        return PRICE_INPUT
    elif text == "Savdolar soni":
        await update.message.reply_text("Maksimal savdo sonini belgilamoqchi bo'lgan aktivni tanlang:", reply_markup=get_max_trades_keyboard(ACTIVE_INSTRUMENTS))
        return MAX_TRADES_INPUT
    elif text == "SELL & BUY":
        await update.message.reply_text("Har bir aktiv uchun SELL/BUY funksiyalarini ON/OFF qiling:", reply_markup=get_sell_buy_keyboard(settings))
        return SELL_BUY_MENU
    elif text == "Sozlamalar":
        return await settings_menu(update, context)
    elif text == "Indikatorlar":  # ⬅️ YANGI QATOR - INDIKATORLAR TUGMASI
        return await indicators_menu(update, context)
    elif text == "Tekshiruv":
        api = context.user_data.get('capital_api')
        if api:
            await check_status(update, context)
        else:
            await update.message.reply_text("Hisob topilmadi. Iltimos, /start buyrug'i bilan botni ishga tushiring.")
        return MAIN_MENU
    elif text == "Asosiy menyu":
        await update.message.reply_text("Asosiy menyu.", reply_markup=main_menu_keyboard)
        return MAIN_MENU
    
    await update.message.reply_text("Tushunarsiz buyruq. Iltimos, menyudagi tugmalardan birini tanlang.", reply_markup=main_menu_keyboard)
    return MAIN_MENU
async def check_min_sizes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Minimal savdo hajmlarini ko'rsatish"""
    message = "📋 Minimal savdo hajmlari:\n\n"
    
    min_sizes = [
        ("Bitcoin (BTC)", "0.0001"),
        ("Ethereum (ETH)", "0.001"), 
        ("Gold (XAU/USD)", "0.01"),
        ("Tesla, Apple", "0.1"),
        ("Crude Oil", "1"),
        ("Natural Gas", "10"),
        ("Euro/USD, USD/JPY", "100")
    ]
    
    for asset, size in min_sizes:
        message += f"• {asset}: {size}\n"
    
    message += "\nℹ️ Agar hisoblangan miqdor minimaldan kichik bo'lsa, minimal hajm qo'llaniladi."
    
    await update.message.reply_text(message)
    return MAIN_MENU

async def check_reality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Haqiqiy miqdor vs ilovadagi ko'rinishni tekshirish"""
    api = context.user_data.get('capital_api')
    if not api:
        await update.message.reply_text("API topilmadi")
        return MAIN_MENU
    
    try:
        positions = await api.get_open_positions()
        
        message = "🔍 Haqiqiy vs Ilovadagi ko'rinish:\n\n"
        
        for pos in positions:
            real_size = pos.get('size', 0)
            displayed_size = int(float(real_size)) + 1  # Ilovadagi ko'rinish
            instrument = pos.get('instrumentName', 'Noma\'lum')
            
            message += f"• {instrument}:\n"
            message += f"  - Haqiqiy: {real_size}\n"
            message += f"  - Ilovada: {displayed_size} kontrakt\n\n"
            
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"Xato: {str(e)}")
    
    return MAIN_MENU

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Hisoblar holatini tekshirish."""
    db: InMemoryDB = context.user_data['db']
    api: CapitalComAPI = context.user_data['capital_api']
    settings = await db.get_settings()

    demo_status = "✅ ON" if settings["demo_account_status"] else "❌ OFF"
    real_status = "✅ ON" if settings["real_account_status"] else "❌ OFF"

    account_details = await api.get_account_details()
    if account_details:
        account_id = account_details.get("accountId", "N/A")
        balance = account_details.get('funds', {}).get('available', 'N/A')
        message = (
            "Hisob holati:\n\n"
            f"Demo Hisob: {demo_status}\n"
            f"Real Hisob: {real_status}\n\n"
            f"Hisob ID: {account_id}\n"
            f"Mavjud mablag': {balance} USD"
        )
    else:
        message = "Hisob holatini tekshirishda xato yuz berdi. Iltimos, keyinroq urinib ko'ring."

    await update.message.reply_text(message)
    return SELECT_ACCOUNT_TYPE

async def get_current_prices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Aktivlarning joriy narxlarini olish funksiyasi."""
    message = "<b>Joriy narxlar:</b>\n\n"
    api = context.user_data.get('capital_api')

    if api:
        for asset, data in ACTIVE_INSTRUMENTS.items():
            price_data = await api.get_prices(data["id"])
            if price_data and 'buy' in price_data and 'sell' in price_data:
                buy_price = price_data.get("buy")
                sell_price = price_data.get("sell")
                message += f"<b>{asset}</b>:\n  - Sotish: ${sell_price}\n  - Sotib olish: ${buy_price}\n"
            else:
                message += f"<b>{asset}</b>: Narx topilmadi\n"
    else:
        message += "API mavjud emas. Iltimos, avval /start buyrug'i bilan botni ishga tushiring."

    await update.message.reply_html(message, reply_markup=main_menu_keyboard)

async def handle_assets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Aktivlar menyusidagi tugmalarni boshqaradi."""
    query = update.callback_query
    await query.answer()
    db = context.user_data.get('db')
    settings = await db.get_settings()

    asset_name = query.data.replace("asset_", "")

    status = settings["buy_sell_status_per_asset"].get(asset_name, {}).get("active", True)
    new_status = not status
    if asset_name not in settings["buy_sell_status_per_asset"]:
        settings["buy_sell_status_per_asset"][asset_name] = {}
    settings["buy_sell_status_per_asset"][asset_name]["active"] = new_status
    await db.save_settings(settings)

    status_text = "YOQILDI" if new_status else "O'CHIRILDI"
    
    await query.message.reply_text(
        f"'{asset_name}' aktiviga savdo qilish {status_text}!",
        reply_markup=get_assets_keyboard(settings)
    )
    await query.delete_message()
    
    return ASSETS_MENU

async def handle_price_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Narx belgilash uchun aktivni tanlash funksiyasi."""
    query = update.callback_query
    await query.answer()

    asset_name = query.data.replace("set_price_", "")
    context.user_data["current_asset"] = asset_name

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Asosiy menyu", callback_data="back_to_main_menu")]
    ])

    await query.edit_message_text(
        f"<b>{asset_name}</b> uchun savdo hajmini (USD) kiriting:",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    return PRICE_INPUT

async def handle_max_trades_selection_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Maksimal savdo sonini tanlash uchun aktivni tanlash funksiyasi."""
    query = update.callback_query
    await query.answer()

    asset_name = query.data.replace("set_max_trades_", "")
    context.user_data['current_asset'] = asset_name

    await query.edit_message_text(
        f"'{asset_name}' uchun maksimal savdo sonini tanlang:",
        reply_markup=get_max_trades_options_keyboard(asset_name)
    )
    return MAX_TRADES_INPUT

async def indicators_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Indikatorlar menyusini ko'rsatadi."""
    db: InMemoryDB = context.user_data['db']
    settings = await db.get_settings()
    
    # Agar sozlamalarda indikatorlar bo'lmasa, default qiymat beramiz
    if "enabled_indicators" not in settings:
        settings["enabled_indicators"] = {
            "ema": True,
            "rsi": True,
            "macd": True,
            "bollinger": True,
            "trend": True,
        }
        await db.save_settings(settings)
    
    await update.message.reply_text(
        "🎛️ Indikatorlarni yoqish/o'chirish:\n\n"
        "FAQAT MNL rejimida ishlaydi!",
        reply_markup=get_indicators_keyboard(settings)
    )
    return INDICATORS_MENU

async def handle_max_trades_value_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Maksimal savdo soni qiymatini belgilash funksiyasi."""
    query = update.callback_query
    await query.answer()
    db = context.user_data.get('db')
    settings = await db.get_settings()

    data = query.data
    try:
        asset_name = data.split("_")[2]
        new_max_trades = int(data.split("_")[3])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Noto'g'ri qiymat. Iltimos, qaytadan urinib ko'ring.", reply_markup=get_max_trades_keyboard(ACTIVE_INSTRUMENTS))
        return MAX_TRADES_INPUT
    
    settings["max_trades_per_asset"][asset_name] = new_max_trades
    await db.save_settings(settings)

    await query.edit_message_text(
        f"'{asset_name}' uchun maksimal savdo soni {new_max_trades} ga o'rnatildi.",
        reply_markup=get_max_trades_keyboard(ACTIVE_INSTRUMENTS)
    )
    return MAX_TRADES_INPUT

async def handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Foydalanuvchi savdo hajmini kiritganda ishlaydi."""
    try:
        new_price = float(update.message.text)
        asset = context.user_data.get('current_asset')
        db = context.user_data.get('db')

        if not db:
            await update.message.reply_text("Iltimos, avval /start buyrug'i bilan botni qayta ishga tushiring.")
            return ConversationHandler.END

        settings = await db.get_settings()

        if asset:
            # Faqat mana shu qatorni yangilang:
            settings.setdefault("trade_amount_per_asset", {})[asset] = new_price
            await db.save_settings(settings)
            await update.message.reply_text(
                f"'{asset}' uchun savdo hajmi ${new_price} ga o'rnatildi.",
                reply_markup=main_menu_keyboard
            )
        else:
            await update.message.reply_text("Noto'g'ri aktiv tanlangan. Qaytadan urinib ko'ring.", reply_markup=main_menu_keyboard)

    except (ValueError, KeyError):
        await update.message.reply_text("Noto'g'ri format. Faqat raqam kiriting.", reply_markup=main_menu_keyboard)

    return MAIN_MENU


async def handle_sell_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """SELL & BUY tugmalarini boshqaradi."""
    query = update.callback_query
    await query.answer()
    db = context.user_data.get('db')
    settings = await db.get_settings()

    data = query.data
    asset_name = data.split("_")[2]
    action = data.split("_")[1] # 'sell' yoki 'buy'

    if asset_name not in settings["buy_sell_status_per_asset"]:
        settings["buy_sell_status_per_asset"][asset_name] = {}

    status = settings["buy_sell_status_per_asset"].get(asset_name, {}).get(action, True)
    settings["buy_sell_status_per_asset"][asset_name][action] = not status
    await db.save_settings(settings)

    status_text = "YOQILDI" if not status else "O'CHIRILDI"

    await query.edit_message_text(
        f"'{asset_name}' uchun {action.upper()} funksiyasi {status_text}!",
        reply_markup=get_sell_buy_keyboard(settings)
    )
    return SELL_BUY_MENU

# =====================================================================================
# YANGI VA TO'G'RILANGAN FUNKSIYALAR
# =====================================================================================

async def get_active_conditions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Aktivlar bo'yicha belgilangan shartlarni ko'rsatadi."""
    db: InMemoryDB = context.user_data.get('db')
    if not db:
        await update.message.reply_text("Iltimos, avval /start buyrug'i bilan botni qayta ishga tushiring.")
        return MAIN_MENU

    settings = await db.get_settings()
    message = "<b>Aktivlar bo'yicha shartlar:</b>\n\n"

    for asset_name, details in ACTIVE_INSTRUMENTS.items():
        trade_amount = settings["trade_amount_per_asset"].get(asset_name, "belgilanmagan")
        max_trades = settings["max_trades_per_asset"].get(asset_name, "belgilanmagan")
        
        message += f"<b>{asset_name}:</b>\n"
        message += f"  - Savdolar soni: {max_trades}\n"
        message += f"  - Belgilangan narx: ${trade_amount}\n\n"

    await update.message.reply_html(message, reply_markup=main_menu_keyboard)
    return MAIN_MENU

async def get_trading_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ochiq savdolarni (sdelkalar) market bilan birga chiqaradi va yopish tugmasi qo'shadi."""

    db: InMemoryDB = context.user_data.get('db')
    api: CapitalComAPI = context.user_data.get('capital_api')
    if not db or not api:
        await update.message.reply_text("Iltimos, avval /start buyrug'i bilan botni qayta ishga tushiring.")
        return MAIN_MENU

    # Pozitsiyalarni yangilash
    await refresh_positions(context)
    settings = await db.get_settings()
    positions = settings.get("positions", {})

    if not positions:
        await update.message.reply_text("Hozirda faol savdolar mavjud emas.", reply_markup=main_menu_keyboard)
        return MAIN_MENU

    message = "<b>Faol savdolar ro'yxati:</b>\n\n"
    keyboard_buttons = []

    # Har bir pozitsiya uchun alohida so‘rov yuboriladi
    tasks = []
    for position_id, position_info in positions.items():
        deal_id = position_info.get('deal_id', position_id)
        tasks.append(api.get_position_details(deal_id))

    details_list = await asyncio.gather(*tasks)

    for detail in details_list:
        position = detail.get("position", {})
        market = detail.get("market", {})

        asset_name = market.get("instrumentName", "Noma'lum")
        epic = market.get("epic", "")
        direction = position.get("direction", "Noma'lum")
        open_price = position.get("level", "Noma'lum")
        leverage = position.get("leverage", "Noma'lum")
        open_time_utc = position.get("createdDateUTC") or position.get("createdDate") or ""
        profit_loss = position.get("upl", "Noma'lum")
        deal_id = position.get("dealId") or position.get("dealReference") or ""

        # Vaqtni chiroyli formatlash
        if open_time_utc:
            try:
                opened_at_utc = datetime.datetime.fromisoformat(open_time_utc.replace("Z", "+00:00"))
                opened_at_tashkent = opened_at_utc.astimezone(pytz.timezone('Asia/Tashkent'))
                open_time_str = opened_at_tashkent.strftime('%Y-%m-%d %H:%M')
            except Exception:
                open_time_str = open_time_utc
        else:
            open_time_str = "Noma'lum"

        message += (
            f"<b>{asset_name} ({epic})</b>:\n"
            f"  - Yo‘nalish: {direction}\n"
            f"  - Ochiq narx: {open_price}\n"
            f"  - Leverage: {leverage}\n"
            f"  - Ochilgan vaqti: {open_time_str}\n"
            f"  - Foyda/zarar: {profit_loss} USD\n\n"
        )

        # Deal_id bo‘lsa, yopish tugmasi
        if deal_id:
            keyboard_buttons.append([
                InlineKeyboardButton(f"Yopish ({asset_name})", callback_data=f"close_trade_{deal_id}")
            ])

    keyboard_buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data='back_to_main_menu')])
    reply_markup = InlineKeyboardMarkup(keyboard_buttons)

    await update.message.reply_html(message, reply_markup=reply_markup)
    return CURRENT_TRADE_MENU


async def manual_trade_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manual savdo menyusini ko'rsatadi."""
    await update.message.reply_text(
        "Qaysi aktiv bo'yicha savdo qilmoqchisiz?",
        reply_markup=get_manual_trade_assets_keyboard()
    )
    return MANUAL_TRADE_MENU

async def handle_manual_asset_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manual savdo uchun aktiv tanlanganda ishlaydi."""
    query = update.callback_query
    await query.answer()
    asset_name = query.data.replace("manual_trade_asset_", "")
    context.user_data['manual_asset'] = asset_name
    await query.edit_message_text(
        f"<b>{asset_name}</b> uchun savdo turini tanlang:",
        parse_mode="HTML",
        reply_markup=get_manual_trade_options_keyboard(asset_name)
    )
    return MANUAL_TRADE_MENU


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sozlamalar menyusini ko'rsatadi."""
    db: InMemoryDB = context.user_data['db']
    settings = await db.get_settings()
    
    reply_markup = get_settings_keyboard(settings)
    
    text = "Bot sozlamalarini o'zgartirish uchun kerakli parametrlarni tanlang:"
    
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
    
    return SETTINGS_MENU

async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sozlamalar menyusidagi tugmalarni boshqaradi."""
    query = update.callback_query
    await query.answer()
    db = context.user_data.get('db')
    
    if not db:
        await query.answer(text="Ichki xato: DB topilmadi.", show_alert=True)
        return SETTINGS_MENU
        
    settings = await db.get_settings()
    data = query.data

    # Auto savdo
    if data == "toggle_auto_trading":
        settings["auto_trading_enabled"] = not settings.get("auto_trading_enabled", True)
        status = "✅ YOQILDI" if settings["auto_trading_enabled"] else "❌ O'CHIRILDI"
        await query.answer(text=f"Auto savdo {status}")

    # Demo hisob
    elif data == "toggle_demo":
        settings["demo_account_status"] = not settings.get("demo_account_status", False)
        status = "✅ YOQILDI" if settings["demo_account_status"] else "❌ O'CHIRILDI"
        await query.answer(text=f"Demo hisob {status}")

    # Real hisob
    elif data == "toggle_real":
        settings["real_account_status"] = not settings.get("real_account_status", False)
        status = "✅ YOQILDI" if settings["real_account_status"] else "❌ O'CHIRILDI"
        await query.answer(text=f"Real hisob {status}")

    # Trailing Mode MNL → AUTO → AI → TEST
    elif data == "toggle_trailing_mode":
        current = settings.get("trailing_mode", "MNL")
        modes = ["TEST", "MNL", "AUTO", "AI"]
        current_index = modes.index(current) if current in modes else 1
        new_index = (current_index + 1) % len(modes)
        new_mode = modes[new_index]
        settings["trailing_mode"] = new_mode
        await query.answer(text=f"Trailing mode: {new_mode} ✅")

    # AI Trailing Stop
    elif data == "toggle_ai_trailing_stop":
        settings["use_ai_trailing_stop"] = not settings.get("use_ai_trailing_stop", False)
        status = "✅ YOQILDI" if settings["use_ai_trailing_stop"] else "❌ O'CHIRILDI"
        await query.answer(text=f"AI Trailing Stop {status}")

    # Trade Signal Weak → Strong → MNL
    elif data == "toggle_trade_signal_level":
        current_level = settings.get("trade_signal_level", "MNL")
        levels = ["TEST", "MNL", "WEAK", "STRONG"]
        current_index = levels.index(current_level) if current_level in levels else 1
        new_index = (current_index + 1) % len(levels)
        new_level = levels[new_index]
        settings["trade_signal_level"] = new_level
        await query.answer(text=f"Signal darajasi: {new_level.upper()} ✅")

    # Trade Signal AI
    elif data == "toggle_trade_signal_ai_enabled":
        settings["trade_signal_ai_enabled"] = not settings.get("trade_signal_ai_enabled", False)
        status = "✅ ON" if settings["trade_signal_ai_enabled"] else "❌ OFF"
        await query.answer(text=f"Trade signal AI: {status}")

    # Trailing Stop foizi
    elif data == "set_trailing_stop":
        context.user_data['awaiting_trailing_stop'] = True
        await query.edit_message_text(
            "Trailing Stop foizini kiriting (1-100):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_settings")]
            ])
        )
        return SETTINGS_MENU

    # Balanslarni tekshirish
    elif data == "check_balances":
        return await check_balances(update, context)

    # Sozlamalarga qaytish
    elif data == "back_to_settings":
        await query.edit_message_text(
            "Bot sozlamalarini o'zgartirish uchun kerakli parametrlarni tanlang:",
            reply_markup=get_settings_keyboard(settings)
        )
        return SETTINGS_MENU

    # Asosiy menyuga qaytish
    elif data == "back_to_main_menu":
        await query.answer(text="Asosiy menyuga qaytildi")
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Asosiy menyu.",
            reply_markup=main_menu_keyboard
        )
        return MAIN_MENU

    # Sozlamalarni saqlash
    await db.save_settings(settings)
    await query.edit_message_reply_markup(reply_markup=get_settings_keyboard(settings))
    return SETTINGS_MENU


async def handle_trailing_stop_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Foydalanuvchi trailing stop foizini kiritganda ishlaydi."""
    if not context.user_data.get('awaiting_trailing_stop'):
        return await handle_main_menu(update, context)
    
    try:
        trailing_value = float(update.message.text)
        if trailing_value < 1 or trailing_value > 100:
            await update.message.reply_text("❌ Foiz 1 dan 100 gacha bo'lishi kerak. Qaytadan kiriting:")
            return SETTINGS_MENU
        
        db = context.user_data.get('db')
        settings = await db.get_settings()
        settings["trailing_stop_percent"] = trailing_value / 100
        await db.save_settings(settings)
        
        context.user_data['awaiting_trailing_stop'] = False
        
        await update.message.reply_text(
            f"✅ Trailing Stop foizi {trailing_value}% ga o'rnatildi.",
            reply_markup=get_settings_keyboard(settings)
        )
        
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format. Faqat raqam kiriting:")
        return SETTINGS_MENU
    
    return SETTINGS_MENU

async def check_balances(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Hisob balanslarini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    
    db = context.user_data.get('db')
    settings = await db.get_settings()
    
    # Demo hisob balansi
    demo_balance = "Noma'lum"
    if settings.get("demo_account_status"):
        try:
            demo_api = CapitalComAPI(
                CAPITAL_COM_USERNAME,
                CAPITAL_COM_PASSWORD,
                demo_api_key=CAPITAL_COM_DEMO_API_KEY,
                demo_api_key_password=CAPITAL_COM_DEMO_API_KEY_PASSWORD,
                account_type="demo"
            )
            login_result = await demo_api.login()
            if login_result.get('success'):
                details = await demo_api.get_account_details()
                if details:
                    demo_balance = f"{details.get('balance', {}).get('available', 'N/A')} USD"
        except Exception as e:
            demo_balance = f"Xato: {str(e)}"
    
    # Real hisob balansi
    real_balance = "Noma'lum"
    if settings.get("real_account_status"):
        try:
            real_api = CapitalComAPI(
                CAPITAL_COM_USERNAME,
                CAPITAL_COM_PASSWORD,
                real_api_key=CAPITAL_COM_REAL_API_KEY,
                real_api_key_password=CAPITAL_COM_REAL_API_KEY_PASSWORD,
                account_type="real"
            )
            login_result = await real_api.login()
            if login_result.get('success'):
                details = await real_api.get_account_details()
                if details:
                    real_balance = f"{details.get('balance', {}).get('available', 'N/A')} USD"
        except Exception as e:
            real_balance = f"Xato: {str(e)}"
    
    message = (
        f"💰 <b>Hisob Balanslari</b>\n\n"
        f"📊 Demo hisob: {demo_balance}\n"
        f"🏦 Real hisob: {real_balance}\n\n"
        f"<i>Sozlamalarga qaytish uchun 'Ortga' tugmasini bosing.</i>"
    )
    
    await query.edit_message_text(
        message,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_settings")]
        ])
    )
    return SETTINGS_MENU
async def handle_trailing_stop_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Foydalanuvchi trailing stop foizini kiritganda ishlaydi."""
    if not context.user_data.get('awaiting_trailing_stop'):
        return await handle_main_menu(update, context)
    
    try:
        trailing_value = float(update.message.text)
        if trailing_value < 1 or trailing_value > 100:
            await update.message.reply_text("❌ Foiz 1 dan 100 gacha bo'lishi kerak. Qaytadan kiriting:")
            return SETTINGS_MENU
        
        db = context.user_data.get('db')
        settings = await db.get_settings()
        settings["trailing_stop_percent"] = trailing_value / 100
        await db.save_settings(settings)
        
        context.user_data['awaiting_trailing_stop'] = False
        
        await update.message.reply_text(
            f"✅ Trailing Stop foizi {trailing_value}% ga o'rnatildi.",
            reply_markup=get_settings_keyboard(settings)
        )
        
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri format. Faqat raqam kiriting:")
        return SETTINGS_MENU
    
    return SETTINGS_MENU

async def handle_ai_rejection_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """AI rad javobi xabarnomalarini yoqish/o'chirishni boshqaradi."""
    query = update.callback_query
    await query.answer()
    
    db = context.user_data.get('db')
    settings = await db.get_settings()

    current_status = settings.get("ai_rejection_notifications", True)
    settings["ai_rejection_notifications"] = not current_status
    await db.save_settings(settings)

    new_status_text = "YOQILDI" if not current_status else "O'CHIRILDI"

    try:
        await query.message.delete()
    except Exception as e:
        logger.error(f"Eski xabarni o'chirishda xato: {e}")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🤖 AI rad javobi xabarnomalari **{new_status_text}**.",
        parse_mode='Markdown',
        reply_markup=get_settings_keyboard(settings)
    )
    return SETTINGS_MENU

async def set_trailing_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Trailing stop foizini o'zgartirish uchun kiritishni kutadi."""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Asosiy menyu", callback_data="back_to_main_menu")]
    ])
    
    await query.edit_message_text(
        "Iltimos, trailing stop foizini 0 dan 100 gacha bo'lgan butun son sifatida kiriting (masalan, 90):",
        reply_markup=keyboard
    )
    context.user_data['state'] = 'awaiting_trailing_stop_value'
    
    return SETTINGS_MENU

async def handle_user_input_for_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Foydalanuvchining kiritgan qiymatlarini qayta ishlaydi."""
    db: InMemoryDB = context.user_data['db']
    settings = await db.get_settings()

    if context.user_data.get('state') == 'awaiting_trailing_stop_value':
        try:
            new_value = float(update.message.text)
            if 0 <= new_value <= 100:
                settings["trailing_stop_percent"] = new_value / 100.0
                await db.save_settings(settings)
                
                await update.message.reply_text(f"✅ Trailing Stop foizi {new_value:.0f}% ga o'rnatildi.", reply_markup=get_settings_keyboard(settings))
                context.user_data['state'] = None
            else:
                await update.message.reply_text("❌ Qiymat 0 va 100 oralig'ida bo'lishi kerak. Qaytadan kiriting:")
        except (ValueError, TypeError):
            await update.message.reply_text("❌ Noto'g'ri format. Iltimos, 0 dan 100 gacha bo'lgan butun son kiriting:")
        finally:
            return SETTINGS_MENU
    else:
        return await handle_main_menu(update, context)

# Botga yangi buyruq qo'shing
async def check_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Hisob ma'lumotlarini va leverage ni tekshirish"""
    api = context.user_data.get('capital_api')
    if not api:
        await update.message.reply_text("API topilmadi")
        return MAIN_MENU
    
    try:
        # Account details olish
        account_details = await api.get_account_details()
        leverage = account_details.get('leverage', 1)
        
        # Pozitsiyalarni olish
        positions = await api.get_open_positions()
        
        message = f"🔧 Hisob ma'lumotlari:\n\n"
        message += f"• Leverage: {leverage}x\n"
        
        if positions:
            for position_id, position_info in positions.items():
                epic = position_info.get('epic') or position_info.get('asset_id')  # epic har doim bo‘lishi shart
                asset_name = get_asset_name_by_epic(epic)
                # endi asset_name ni ishlating:
                message += f"<b>{asset_name}</b>:\n"
            
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"Xato: {str(e)}")
    
    return MAIN_MENU

async def set_leverage_1x(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Leverage ni 1x ga sozlash (ko'rsatma beradi)"""
    await update.message.reply_text(
        "⚠️ Leverage ni sozlash uchun:\n"
        "1. Capital.com veb-saytiga yoki ilovasiga kiring\n"
        "2. Hisob sozlamalariga kiring\n" 
        "3. Leverage ni 1x ga o'zgartiring\n"
        "4. Bot leverage ni avtomatik oladi"
    )
    return MAIN_MENU

async def check_contract_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Kontrakt detalilarini tekshirish"""
    api = context.user_data.get('capital_api')
    if not api:
        await update.message.reply_text("API topilmadi. Avval /start bilan botni ishga tushiring.")
        return MAIN_MENU
    
    try:
        # ETH uchun bozor ma'lumotlarini olish
        epic = "CS.D.ETHUSD.CFD.IP"  # ETH EPIC
        market_info = await api._get_market_info(epic)
        
        message = "📋 ETH Kontrakt detalilari:\n\n"
        
        if market_info:
            # Kontrakt koeffitsientini tekshirish
            contract_size = market_info.get('contractSize', market_info.get('lotSize', 1))
            message += f"• Kontrakt hajmi: {contract_size} ETH\n"
            
            # Min/max savdo hajmi
            if 'dealSize' in market_info:
                deal_size = market_info['dealSize']
                message += f"• Min savdo: {deal_size.get('min', 1)}\n"
                message += f"• Max savdo: {deal_size.get('max', 'Cheksiz')}\n"
                message += f"• Qadam: {deal_size.get('step', 1)}\n"
            
            # Unit info
            if 'units' in market_info:
                units = market_info['units']
                message += f"• Birlik: {units}\n"
                
            # Boshqa muhim ma'lumotlar
            for key in ['currency', 'instrumentName', 'epic']:
                if key in market_info:
                    message += f"• {key}: {market_info[key]}\n"
        else:
            message += "❌ Market ma'lumotlari topilmadi"
            
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"Xato: {str(e)}")
    
    return MAIN_MENU

async def set_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Leverage ni o'zgartirish"""
    try:
        new_leverage = float(context.args[0])
        if new_leverage < 1 or new_leverage > 100:
            await update.message.reply_text("Leverage 1 dan 100 gacha bo'lishi kerak")
            return MAIN_MENU
            
        db: InMemoryDB = context.user_data.get('db')
        if not db:
            await update.message.reply_text("DB topilmadi")
            return MAIN_MENU
        
        settings = await db.get_settings()
        settings["leverage"] = new_leverage
        await db.save_settings(settings)
        
        await update.message.reply_text(f"✅ Leverage {new_leverage}x ga o'rnatildi")
        
    except (IndexError, ValueError):
        await update.message.reply_text("Iltimos, raqam kiriting: /setleverage 5")
    
    return MAIN_MENU

async def check_balances(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Hisob balanslarini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    
    db = context.user_data.get('db')
    settings = await db.get_settings()
    
    # Demo hisob balansi
    demo_balance = "Noma'lum"
    if settings.get("demo_account_status"):
        try:
            demo_api = CapitalComAPI(
                CAPITAL_COM_USERNAME,
                CAPITAL_COM_PASSWORD,
                demo_api_key=CAPITAL_COM_DEMO_API_KEY,
                demo_api_key_password=CAPITAL_COM_DEMO_API_KEY_PASSWORD,
                account_type="demo"
            )
            login_result = await demo_api.login()
            if login_result.get('success'):
                details = await demo_api.get_account_details()
                if details:
                    demo_balance = f"{details.get('balance', {}).get('available', 'N/A')} USD"
        except Exception as e:
            demo_balance = f"Xato: {str(e)}"
    
    # Real hisob balansi
    real_balance = "Noma'lum"
    if settings.get("real_account_status"):
        try:
            real_api = CapitalComAPI(
                CAPITAL_COM_USERNAME,
                CAPITAL_COM_PASSWORD,
                real_api_key=CAPITAL_COM_REAL_API_KEY,
                real_api_key_password=CAPITAL_COM_REAL_API_KEY_PASSWORD,
                account_type="real"
            )
            login_result = await real_api.login()
            if login_result.get('success'):
                details = await real_api.get_account_details()
                if details:
                    real_balance = f"{details.get('balance', {}).get('available', 'N/A')} USD"
        except Exception as e:
            real_balance = f"Xato: {str(e)}"
    
    message = (
        f"💰 <b>Hisob Balanslari</b>\n\n"
        f"📊 Demo hisob: {demo_balance}\n"
        f"🏦 Real hisob: {real_balance}\n\n"
        f"<i>Sozlamalarga qaytish uchun 'Ortga' tugmasini bosing.</i>"
    )
    
    await query.edit_message_text(
        message,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Ortga", callback_data="back_to_settings")]
        ])
    )
    return SETTINGS_MENU

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Bosh menyuga qaytish uchun tugma."""
    query = update.callback_query
    await query.answer()

    await query.message.delete()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Asosiy menyu.",
        reply_markup=main_menu_keyboard
    )
    return MAIN_MENU

async def send_daily_summary(context: CallbackContext):
    """Har 24 soatda savdo hisobotini yuboradi."""
    db: InMemoryDB = context.user_data.get('db')
    api: CapitalComAPI = context.user_data.get('capital_api')

    if not db or not api:
        logger.warning("Hisobot yuborish uchun ma'lumot bazasi yoki API mavjud emas.")
        return

    settings = await db.get_settings()
    chat_id = settings.get("chat_id")

    if not chat_id:
        from config import CHAT_ID
        chat_id = CHAT_ID
        if not chat_id:
            logger.warning("Hisobot yuborish uchun chat_id topilmadi.")
            return

    try:
        account_details = await api.get_account_details()
        if not account_details:
            await context.bot.send_message(chat_id=chat_id, text="Hisobot olinmadi. API bilan bog'lanishda xato yuz berdi.")
            return

        balance = account_details.get('funds', {}).get('equity', 'N/A')
        open_positions = len(settings.get("positions", {}))

        summary_text = (
            f"📊 **Botning kunlik savdo hisoboti**\n\n"
            f"🗓️ Vaqt: {datetime.datetime.now(pytz.timezone('Asia/Tashkent')).strftime('%Y-%m-%d %H:%M')}\n\n"
            f"💰 **Hisob holati:**\n"
            f"Umumiy balans: {balance:.2f} USD\n"
            f"Ochiq savdolar soni: {open_positions}\n\n"
            f"Bu hisobot botning so'nggi 24 soatdagi umumiy faoliyatini ko'rsatadi."
        )

        await context.bot.send_message(chat_id=chat_id, text=summary_text, parse_mode='Markdown')
        logger.info("Kunlik hisobot muvaffaqiyatli yuborildi.")

    except Exception as e:
        logger.error(f"Kunlik hisobotni yuborishda kutilmagan xato: {e}")

async def run_websocket_task(api, instruments_to_subscribe):
    """Aloqa uzilganida qayta ulanishga harakat qiladi."""
    while True:
        try:
            logger.info("Websocket-ga ulanishga harakat qilinmoqda...")
            await api.connect_websocket(instruments_to_subscribe)
        except ClientConnectionError as e:
            logger.error(f"WebSocket-ga ulanishda xato: {e}. Qayta ulanishga urinish...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Kutilmagan xato: {e}. Vazifa to'xtatildi.")
            break

async def handle_manual_asset_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manual savdo uchun aktiv tanlanganda ishlaydi."""
    query = update.callback_query
    await query.answer()
    print(f"DEBUG: Asset selected: {query.data}")  # ✅ DEBUG
    asset_name = query.data.replace("manual_trade_asset_", "")
    context.user_data['manual_asset'] = asset_name
    
    await query.edit_message_text(
        f"<b>{asset_name}</b> uchun savdo turini tanlang:",
        parse_mode="HTML",
        reply_markup=get_manual_trade_options_keyboard(asset_name)
    )
    return MANUAL_TRADE_ACTION

async def handle_manual_trade_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Buy/Sell tugmalari bosilganda hajmni so'raydi."""
    query = update.callback_query
    await query.answer()
    print(f"DEBUG: Trade action: {query.data}")  # ✅ DEBUG
    data = query.data.split('_')
    deal_type = data[1] # 'buy' yoki 'sell'
    asset_name = data[2]
    context.user_data['manual_deal_type'] = deal_type

    await query.edit_message_text(
        f"Siz {asset_name} uchun {deal_type.upper()} savdosini tanladingiz.\n\n"
        "Savdo hajmini kiriting:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="back_to_manual_trade_menu")],
            [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="back_to_main_menu")]
        ])
     )
    return MANUAL_AMOUNT_INPUT


async def setup_bot_tasks(context: ContextTypes.DEFAULT_TYPE):
    """Websocket va savdo vazifalarini boshlaydi."""
    api = context.user_data.get('capital_api')
    instruments_to_subscribe = [details["id"] for details in ACTIVE_INSTRUMENTS.values()]

    if api and instruments_to_subscribe:
        # ... trading_task_instance va boshqalar ...
        context.user_data['trading_task_instance'] = asyncio.create_task(trading_logic_loop(context))
        context.user_data['closing_task_instance'] = asyncio.create_task(close_profitable_positions_loop(context))
        for task_name in ['trading_task_instance', 'closing_task_instance', 'websocket_task_instance']:
            if task_name in context.user_data and context.user_data[task_name]:
                try:
                    context.user_data[task_name].cancel()
                    await context.user_data[task_name]
                except asyncio.CancelledError:
                    pass
                finally:
                    context.user_data[task_name] = None
        
        context.user_data['trading_task_instance'] = asyncio.create_task(trading_logic_loop(context))
        context.user_data['closing_task_instance'] = asyncio.create_task(close_profitable_positions_loop(context))
        context.user_data['websocket_task_instance'] = asyncio.create_task(run_websocket_task(api, instruments_to_subscribe))

        logger.info("Savdo, pozitsiyalarni yopish va websocket vazifalari ishga tushirildi.")
    else:
        logger.error("API yoki obuna bo'lish uchun instrumentlar topilmadi. Vazifalar ishga tushirilmaydi.")

# --- REPLACE existing execute_manual_trade with this ---
async def execute_manual_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    print(f"DEBUG: Amount received: {update.message.text}")  # ✅ DEBUG
    """Manual savdo buyurtmasini amalga oshiradi va hajmni qabul qiladi."""
    message = update.message
    trade_amount_str = message.text

    # parse amount (expected USD)
    try:
        trade_amount = float(trade_amount_str)
        if trade_amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text("❌ Noto'g'ri hajm kiritildi. Iltimos, musbat son kiriting.")
        return MANUAL_AMOUNT_INPUT

    db = context.user_data.get('db')
    api = context.user_data.get('capital_api')

    if not api or not db:
        await message.reply_text("API yoki DB topilmadi. Botni qayta ishga tushiring.")
        return MAIN_MENU

    asset_name = context.user_data.get('manual_asset')
    deal_type = context.user_data.get('manual_deal_type')  # 'buy' yoki 'sell'

    if not asset_name or not deal_type:
        await message.reply_text("❌ Savdo ma'lumotlari topilmadi. Jarayonni qaytadan boshlang.")
        return MAIN_MENU

    asset_id = ACTIVE_INSTRUMENTS.get(asset_name, {}).get("id")
    if not asset_id:
        await message.reply_text(f"❌ '{asset_name}' aktiviga ID topilmadi.")
        return MAIN_MENU

    settings = await db.get_settings()
    # ensure positions dict exists
    if settings.get("positions") is None:
        settings["positions"] = {}
    max_trades = settings.get("max_trades_per_asset", {}).get(asset_name, float('inf'))

    open_positions = settings.get("positions", {})
    open_positions_count_for_asset = sum(
        1 for pos in open_positions.values() if pos.get('asset_name') == asset_name
    )

    if open_positions_count_for_asset >= max_trades:
        await message.reply_text(
            "❌ Ushbu aktiv bo'yicha maksimal savdolar soniga yetdingiz.",
            reply_markup=main_menu_keyboard
        )
        return MAIN_MENU

    # ✅ DEBUG: Telegramga debug habarini yuborish
    debug_message = f"🔍 DEBUG: Savdo ma'lumotlari:\n- Aktiv: {asset_name}\n- Tur: {deal_type.upper()}\n- Miqdor: ${trade_amount}"
    await message.reply_text(debug_message)

    # IMPORTANT: Miqdorni to'g'ri hisoblash
    try:
        # Narxni olish (Capital API dan)
        price_info = await api.get_prices(asset_id)
        if not price_info:
            await message.reply_text("❌ Narxni olishda muammo.")
            return MAIN_MENU

        buy_price = price_info.get("buy")
        sell_price = price_info.get("sell")

        # deal_type ga qarab narxni tanlash
        if deal_type.lower() == "buy":
            price = buy_price
        else:
            price = sell_price

        if not price or price <= 0:
            await message.reply_text("❌ Narx aniqlanmadi.")
            return MAIN_MENU

        # USD summadan lot hisoblash
        size = trade_amount / price

        # ✅ Savdoni amalga oshirish (YANGILANDI)
        result = await api.create_position(
            currency_pair=asset_id,
            direction=deal_type,
            size=size  # ✅ Lot miqdori to'g'ridan-to'g'ri yuboriladi
        )

    except Exception as e:
        logger.exception("Pozitsiya ochishda exception: %s", e)
        await message.reply_text(
            f"❌ Pozitsiya ochishda xato: {e}",
            reply_markup=main_menu_keyboard
        )
        return MAIN_MENU

    if result.get("success"):
        # get deal reference (deal_id / dealReference)
        deal_ref = (
            result.get("deal_id") or result.get("position_id")
            or (result.get("details") or {}).get("dealReference")
            or (result.get("details") or {}).get("dealId")
        )
        if not deal_ref:
            # agar API hech qanday id qaytarmagan bo'lsa, details ichini matn sifatida saqlaymiz
            deal_ref = str((result.get("details") or result))[:64]

        open_price = None
        try:
            open_price = (
                (result.get("details") or {}).get("level")
                or (result.get("details") or {}).get("openPrice")
            )
        except Exception:
            open_price = None

        # Saqlash: positions exist bo'lishi kerak
        if settings.get("positions") is None:
            settings["positions"] = {}

        settings["positions"][deal_ref] = {
            "asset_name": asset_name,
            "deal_type": deal_type.upper(),
            "opened_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
            "open_price": open_price,
            "deal_id": deal_ref,
            "amount_usd": trade_amount,
        }
        await db.save_settings(settings)

        # ✅ Muvaffaqiyatli savdo xabari
        success_message = f"""
✅ <b>{asset_name}</b> bo'yicha <b>{deal_type.upper()}</b> savdosi muvaffaqiyatli ochildi!
📊 Ma'lumotlar:
- Miqdor: ${trade_amount}
- Narx: ${price if price else 'N/A'}
- Kontrakt: {size}
- Deal ID: {deal_ref}
"""
        await message.reply_html(success_message)
        await message.reply_text("Asosiy menyu.", reply_markup=main_menu_keyboard)
    else:
        err = result.get("error") or result.get("message") or str(result)
        error_message = f"""
❌ <b>{asset_name}</b> bo'yicha savdoni ochishda xato:
{err}

📊 Ma'lumotlar:
- Miqdor: ${trade_amount}
- Narx: ${price if price else 'N/A'}
- Kontrakt: {size}
"""
        await message.reply_html(error_message)
        await message.reply_text("Asosiy menyu.", reply_markup=main_menu_keyboard)

    return MAIN_MENU


# --- REPLACE existing close_manual_trade with this ---
async def close_manual_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manual ravishda savdoni yopish funksiyasi (callback tugma yordamida)."""
    query = update.callback_query
    await query.answer()
    db = context.user_data.get('db')
    api = context.user_data.get('capital_api')
    position_id = query.data.replace("close_trade_", "")

    if not api or not db:
        await query.edit_message_text("API yoki DB topilmadi. Botni qayta ishga tushiring.")
        return MAIN_MENU

    settings = await db.get_settings()
    positions = settings.get("positions", {}) or {}
    pos_info = positions.get(position_id)

    direction = pos_info.get("deal_type") if pos_info else None
    epic = None
    if pos_info:
        epic = ACTIVE_INSTRUMENTS.get(pos_info.get("asset_name"), {}).get("id")

    try:
        result = await api.close_position(deal_id=position_id, direction=direction, epic=epic)
    except CapitalAPIError as e:
        logger.error("API close error: %s", e.message)
        await query.edit_message_text(f"❌ Pozitsiyani yopishda API xato: {e.message}")
        return MAIN_MENU
    except Exception as e:
        logger.exception("Pozitsiyani yopishda kutilmagan xato: %s", e)
        await query.edit_message_text(f"❌ Pozitsiyani yopishda xato: {e}")
        return MAIN_MENU

    if result.get("success"):
        # delete from saved positions if exist
        if position_id in settings.get("positions", {}):
            try:
                del settings["positions"][position_id]
                await db.save_settings(settings)
            except Exception:
                logger.exception("Positionsni o'chirishda xato.")
        await query.edit_message_text(f"✅ Savdo muvaffaqiyatli yopildi! ID: {position_id}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Asosiy menyu.", reply_markup=main_menu_keyboard)
    else:
        err = result.get("error") or result.get("message") or str(result)
        await query.edit_message_text(f"❌ Savdoni yopishda xato: {err}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Asosiy menyu.", reply_markup=main_menu_keyboard)

    return MAIN_MENU


async def back_to_manual_trade_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Manual savdo menyusiga qaytish."""
    query = update.callback_query
    await query.answer()

    asset_name = context.user_data.get("manual_asset")
    if not asset_name:
        # Agar aktiv tanlanmagan bo‘lsa, boshidan manual menyuga qaytaramiz
        await query.edit_message_text(
            "Qaysi aktiv bo‘yicha savdo qilmoqchisiz?",
            reply_markup=get_manual_trade_assets_keyboard()
        )
        return MANUAL_TRADE_MENU

    # Agar aktiv tanlangan bo‘lsa, savdo turi (BUY/SELL) menyusiga qaytaramiz
    await query.edit_message_text(
        f"<b>{asset_name}</b> uchun savdo turini tanlang:",
        parse_mode="HTML",
        reply_markup=get_manual_trade_options_keyboard(asset_name)
    )
    return MANUAL_TRADE_MENU

# =====================================================================================
# Dispatcher
# =====================================================================================

def start_bot():
    """Botni boshlaydi."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Kunlik hisobot
    application.job_queue.run_repeating(
        send_daily_summary,
        interval=datetime.timedelta(hours=24),
        first=datetime.time(hour=9, minute=0, tzinfo=pytz.timezone('Asia/Tashkent'))
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            SELECT_ACCOUNT_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_type_selection),
            ],
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$')
            ],
            ASSETS_MENU: [
                CallbackQueryHandler(handle_assets_callback, pattern=r'^asset_.*$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$'),
                MessageHandler(filters.Regex("^Asosiy menyu$"), handle_main_menu),
                MessageHandler(filters.Regex("^Tekshiruv$"), handle_main_menu),
            ],
            PRICE_INPUT: [
                CallbackQueryHandler(handle_price_selection_callback, pattern=r'^set_price_.*$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$'),
                MessageHandler(filters.Regex("^Asosiy menyu$"), handle_main_menu),
                MessageHandler(filters.Regex("^Tekshiruv$"), handle_main_menu),
            ],
            MAX_TRADES_INPUT: [
                CallbackQueryHandler(handle_max_trades_selection_callback, pattern=r'^set_max_trades_.*$'),
                CallbackQueryHandler(handle_max_trades_value_callback, pattern=r'^set_max_.*$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$'),
                MessageHandler(filters.Regex("^Asosiy menyu$"), handle_main_menu),
                MessageHandler(filters.Regex("^Tekshiruv$"), handle_main_menu),
            ],
            SELL_BUY_MENU: [
                CallbackQueryHandler(handle_sell_buy_callback, pattern=r'^(toggle_sell|toggle_buy)_.*$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$'),
                MessageHandler(filters.Regex("^Asosiy menyu$"), handle_main_menu),
                MessageHandler(filters.Regex("^Tekshiruv$"), handle_main_menu),
            ],
            SETTINGS_MENU: [
                CallbackQueryHandler(handle_settings_callback, pattern=r'^(toggle_auto_trading|toggle_demo|toggle_real|toggle_trailing_mode|toggle_ai_trailing_stop|toggle_trade_signal_level|toggle_trade_signal_ai_enabled|set_trailing_stop|check_balances|back_to_settings|back_to_main_menu)$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trailing_stop_input),
            ],
            MANUAL_TRADE_MENU: [
                CallbackQueryHandler(handle_manual_asset_selection, pattern=r'^manual_trade_asset_.*$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$'),
                MessageHandler(filters.Regex("^Asosiy menyu$"), handle_main_menu),
                MessageHandler(filters.Regex("^Tekshiruv$"), handle_main_menu),
            ],
            MANUAL_TRADE_ACTION: [
                CallbackQueryHandler(handle_manual_trade_action, pattern=r'^(manual_buy|manual_sell)_.*$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$'),
                MessageHandler(filters.Regex("^Asosiy menyu$"), handle_main_menu),
            ],
            MANUAL_AMOUNT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, execute_manual_trade),
                CallbackQueryHandler(back_to_manual_trade_menu, pattern=r'^back_to_manual_trade_menu$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$')
            ],
            INDICATORS_MENU: [
                CallbackQueryHandler(toggle_indicator_callback, pattern=r'^toggle_(ema|rsi|macd|bollinger|trend)$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$'),
                CallbackQueryHandler(back_to_settings_callback, pattern=r'^back_to_settings$'),
            ],
            CURRENT_TRADE_MENU: [
                CallbackQueryHandler(close_manual_trade, pattern=r'^close_trade_.*$'),
                CallbackQueryHandler(back_to_main_menu, pattern=r'^back_to_main_menu$')
            ],
        },
        fallbacks=[CommandHandler("start", start_command)],
        per_message=False
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("accountinfo", check_account_info))
    application.add_handler(CommandHandler("setleverage1x", set_leverage_1x))
    application.add_handler(CommandHandler("contractinfo", check_contract_details))
    application.add_handler(CommandHandler("debugpos", debug_positions))
    application.add_handler(CommandHandler("reality", check_reality))
    application.add_handler(CommandHandler("minsizes", check_min_sizes))
    application.add_handler(CommandHandler("debugapi", debug_api))
    application.add_handler(CommandHandler("debugstate", debug_states))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^log (all|trade|important)$'), log_command))
    application.add_handler(CommandHandler("status", check_auto_trade))
    application.add_handler(CommandHandler("testepics", test_epics))



    # Bot ishga tushganda avtomatik savdoni ishga tushirish
    application.job_queue.run_once(
        lambda ctx: start_trading_loops(ctx),
        when=0
    )
    
    logger.info("Bot ishga tushirildi. Chiqish uchun Ctrl+C tugmasini bosing.")

    try:
        application.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Bot o'chirilmoqda.")
    except Exception as e:
        logger.error(f"Kutilmagan xato: {e}")

if __name__ == "__main__":
    start_bot()
