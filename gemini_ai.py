import aiohttp
import logging
import os

logger = logging.getLogger(__name__)

# API konfiguratsiyasi (API KEY va URL)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")  # O'zgartiring yoki .env orqali o'zgartiring
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

async def get_ai_approval(asset, direction, prices, indicators, news=None, market_condition=None, sentiment=None):
    """
    AI'dan savdo uchun signalni tasdiqlash (APPROVE/REJECT) va sababini olish.
    Barcha kerakli kontekstlarni (aktiv, yo'nalish, narxlar, indikatorlar, yangiliklar, bozor holati, sentiment) yuborish mumkin.
    """
    # Promptni tuzamiz
    prompt = (
        f"Savdo uchun signal.\n"
        f"Aktiv: {asset}\n"
        f"Yo'nalish: {direction}\n"
        f"Narxlar: {prices}\n"
        f"Indikatorlar: {indicators}\n"
    )
    if news:
        prompt += f"So‘nggi yangiliklar: {news}\n"
    if market_condition:
        prompt += f"Bozor holati: {market_condition}\n"
    if sentiment:
        prompt += f"Sentiment: {sentiment}\n"
    prompt += (
        'Iltimos, faqat "APPROVE: ..." yoki "REJECT: ..." deb javob bering va sababini qisqacha izohlang.'
    )

    logger.debug(f"AI'ga yuborilayotgan ma'lumotlar: {prompt}")

    # Google Gemini API uchun so'rov tuzish
    data = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY
    }

    # Asinxron POST so'rov
    response_text = ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GEMINI_API_URL, json=data, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    logger.debug(f"Gemini javobi: {result}")
                    # Gemini javobidan matnni ajratib olish
                    try:
                        response_text = (
                            result["candidates"][0]
                            ["content"]["parts"][0]["text"]
                        ).strip()
                    except Exception as e:
                        logger.error(f"Gemini javobini o'qishda xato: {e}")
                        response_text = ""
                else:
                    logger.error(f"HTTP so'rovda xato: {resp.status}, {await resp.text()}")
    except Exception as e:
        logger.error(f"Gemini API so'rovda xato: {e}")

    # Javobni tahlil qilish
    if response_text:
        text = response_text.strip()
        if text.upper().startswith("APPROVE"):
            reason = text[8:].strip(": ").strip()
            return {"decision": "APPROVE", "reason": reason}
        elif text.upper().startswith("REJECT"):
            reason = text[7:].strip(": ").strip()
            return {"decision": "REJECT", "reason": reason}
        else:
            return {"decision": "REJECT", "reason": text}
    else:
        return {"decision": "REJECT", "reason": "AI'dan bo'sh javob keldi."}