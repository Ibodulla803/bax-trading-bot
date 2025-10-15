# capital_api.py
import json
import logging
import aiohttp
import websockets
import ssl
import certifi
import asyncio
from typing import Dict, Any, List, Optional
import base64

from Cryptodome.Cipher import PKCS1_v1_5
from Cryptodome.PublicKey import RSA
from datetime import datetime

# Relative import — loyihangiz strukturasiga mos holda config.py ichidagi o'zgaruvchilar
from config import (
    CAPITAL_COM_DEMO_API_KEY,
    CAPITAL_COM_USERNAME,
    CAPITAL_COM_PASSWORD,
    ACTIVE_INSTRUMENTS,
    CAPITAL_COM_REAL_API_KEY,
    CAPITAL_COM_DEMO_API_KEY_PASSWORD,
    CAPITAL_COM_REAL_API_KEY_PASSWORD,
)

# (Ixtiyoriy) agar kod boshqa joylarda tahlil va indikatorlar uchun pandas/talib/np ishlatsa,
# ularni saqlab qoldim — lekin agar sizga kerak bo'lmasa o'chirishingiz mumkin.
import pandas as pd
import talib
import numpy as np

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# SSL context for WebSocket connections
ssl_context = ssl.create_default_context(cafile=certifi.where())




# =====================================================================================
# Custom Exceptions
# =====================================================================================
class CapitalAPIError(Exception):
    """Custom exception for Capital.com related errors."""

    def __init__(self, status: int, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.data = data or {}


# =====================================================================================
# Capital.com API Class
# =====================================================================================
class CapitalComAPI:
    """
    Main class for interacting with Capital.com API.
    Konstruktor:
      CapitalComAPI(username, password,
                    demo_api_key=None, real_api_key=None,
                    demo_api_key_password=None, real_api_key_password=None,
                    account_type='demo')
    """

    current_prices: Dict[str, Dict[str, float]] = {}

    def __init__(
        self,
        username: str,
        password: str,
        demo_api_key: Optional[str] = None,
        real_api_key: Optional[str] = None,
        demo_api_key_password: Optional[str] = None,
        real_api_key_password: Optional[str] = None,
        account_type: str = "demo",
    ):
        self.username = username
        self.password = password
        self.account_type = account_type.lower() if account_type else "demo"

        self.demo_api_key = demo_api_key
        self.real_api_key = real_api_key
        self.demo_api_key_password = demo_api_key_password
        self.real_api_key_password = real_api_key_password

        self.api_key: Optional[str] = None
        self.api_key_password: Optional[str] = None
        self.base_url: str = ""
        self.websocket_url: str = ""
        self.session_token: Optional[str] = None
        self.cst_token: Optional[str] = None
        self.websocket_connection = None

        # set base according to account_type
        if self.account_type == "real":
            self.api_key = self.real_api_key
            self.api_key_password = self.real_api_key_password
            self.base_url = "https://api-capital.backend-capital.com"
            self.websocket_url = "wss://api-streaming-capital.backend-capital.com/connect"
        else:
            self.api_key = self.demo_api_key
            self.api_key_password = self.demo_api_key_password
            self.base_url = "https://demo-api-capital.backend-capital.com"
            self.websocket_url = "wss://api-streaming-capital.backend-capital.com/connect"

        # endpoints
        self.endpoints = {
            "session": "/api/v1/session",
            "encryption_key": "/api/v1/session/encryptionKey",
            "accounts": "/api/v1/accounts",
            "positions": "/api/v1/positions",
            "open_position": "/api/v1/positions",
            "close_position": "/api/v1/positions/",  # append deal id
            "markets": "/api/v1/markets",
            "prices": "/api/v1/prices",
        }

    def _full_url(self, path_or_url: str) -> str:
        """Return full URL if path given, otherwise return as-is."""
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"{self.base_url}{path_or_url}"

    @property
    def headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-CAP-API-KEY": self.api_key or "",
            "Version": "3",
        }
        if self.cst_token:
            headers["CST"] = self.cst_token
        if self.session_token:
            headers["X-SECURITY-TOKEN"] = self.session_token
        return headers
    async def get_cached_market_info(self, epic: str) -> Dict[str, Any]:
        """Keshlangan bozor ma'lumotlarini olish"""
        current_time = time.time()
        
        # Agar ma'lumot keshlangan va vaqti o'tmagan bo'lsa
        if (
            epic in self.market_cache
            and epic in self.cache_expiry
            and current_time < self.cache_expiry[epic]
        ):
            return self.market_cache[epic]
        
        # Yangi ma'lumot olish
        market_info = await self._get_market_info(epic)
        
        if market_info:
            self.market_cache[epic] = market_info
            self.cache_expiry[epic] = current_time + self.cache_duration
        
        return market_info

    def _full_url(self, path_or_url: str) -> str:
        """Return full URL if path given, otherwise return as-is."""
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"{self.base_url}{path_or_url}"

    # capital_api.py ga qo'shimcha funksiya qo'shing
    async def search_eth_markets(self):
        """Ethereum bozorlarini qidirish"""
        try:
            # Ethereum uchun bozorlarni qidirish
            result = await self.search_markets(search_term="Ethereum")
            logger.info(f"Ethereum bozorlari: {result}")
            
            # Yoki ETH uchun qidirish
            result_eth = await self.search_markets(search_term="ETH")
            logger.info(f"ETH bozorlari: {result_eth}")
            
            return result
        except Exception as e:
            logger.error(f"Bozor qidirishda xato: {e}")
            return None
    # -------------------------
    # Low-level HTTP helpers
    # -------------------------
    async def _get_json(self, url_or_path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        # _full_url metodidan foydalanish
        url = self._full_url(url_or_path)
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, params=params) as resp:
                    text = await resp.text()
                    if not resp.ok:
                        # try parse body for more info
                        try:
                            data = json.loads(text)
                        except Exception:
                            data = text
                        msg = f"GET {url} returned {resp.status}: {data}"
                        logger.error(msg)
                        raise CapitalAPIError(resp.status, msg, {"body": data})
                    if text:
                        return await resp.json()
                    return {}
        except aiohttp.ClientError as e:
            logger.error("HTTP GET error: %s", e)
            raise CapitalAPIError(500, f"HTTP GET error: {e}")

    async def _post_json(self, url_or_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # _full_url metodidan foydalanish
        url = self._full_url(url_or_path)
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.post(url, data=json.dumps(payload)) as resp:
                    text = await resp.text()
                    if not resp.ok:
                        try:
                            data = json.loads(text)
                        except Exception:
                            data = text
                        msg = f"POST {url} returned {resp.status}: {data}"
                        logger.error(msg)
                        raise CapitalAPIError(resp.status, msg, {"body": data})
                    if text:
                        return await resp.json()
                    return {}
        except aiohttp.ClientError as e:
            logger.error("HTTP POST error: %s", e)
            raise CapitalAPIError(500, f"HTTP POST error: {e}")

    async def _make_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """
        Generic request wrapper: method, path (relative), kwargs forwarded to session.request.
        """
        # _full_url metodidan foydalanish
        url = self._full_url(path)
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.request(method, url, **kwargs) as response:
                    text = await response.text()
                    if not response.ok:
                        try:
                            data = json.loads(text)
                        except Exception:
                            data = text
                        error_message = f"Request error: {method} {url} | Status: {response.status} | Message: {data}"
                        logger.error(error_message)
                        raise CapitalAPIError(response.status, error_message, {"body": data})
                    if text:
                        return await response.json()
                    return {}
        except aiohttp.ClientError as e:
            logger.error(f"HTTP request error occurred: {e}")
            raise CapitalAPIError(500, f"HTTP request error occurred: {e}")

    # -------------------------
    # Encryption & login
    # -------------------------
    # capital_api.py faylida get_encryption_key metodini yangilang
    async def get_encryption_key(self) -> Dict[str, Any]:
        """Request encryption key and timestamp from API."""
        path = self.endpoints["encryption_key"]
        headers = {"Content-Type": "application/json", "X-CAP-API-KEY": self.api_key or ""}
        
        # _full_url metodidan foydalanish
        url = self._full_url(path)
        
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url) as response:
                    text = await response.text()
                    if not response.ok:
                        try:
                            data = json.loads(text)
                        except Exception:
                            data = text
                        msg = f"Encryption key GET returned {response.status}: {data}"
                        logger.error(msg)
                        raise CapitalAPIError(response.status, msg, {"body": data})
                    return await response.json()
        except aiohttp.ClientError as e:
            logger.error("Failed to get encryption key: %s", e)
            raise CapitalAPIError(500, f"Failed to get encryption key: {e}")

    def _rsa_encrypt(self, public_key_b64: str, data: str) -> str:
        """
        RSA encrypt data using provided base64 public key (as returned by /session/encryptionKey).
        Steps (matching Capital.com docs):
          - base64 decode public key
          - base64 encode (password|timestamp) first
          - RSA encrypt that
          - base64 encode output
        """
        try:
            public_key_bytes = base64.b64decode(public_key_b64)
            public_key = RSA.import_key(public_key_bytes)
            cipher = PKCS1_v1_5.new(public_key)
            # Step: base64 encode the plaintext (password|timestamp)
            data_b64 = base64.b64encode(data.encode("utf-8"))
            encrypted = cipher.encrypt(data_b64)
            return base64.b64encode(encrypted).decode("utf-8")
        except Exception as e:
            logger.error("RSA encryption failed: %s", e)
            raise

    async def login(self) -> Dict[str, Any]:
        """
        Login using encrypted password flow:
          1) GET /session/encryptionKey -> encryptionKey + timeStamp
          2) encrypt "password|timeStamp" using RSA public key
          3) POST /session with identifier, password(encrypted), encryptedPassword True
        On success, extract CST and X-SECURITY-TOKEN headers.
        """
        path = self.endpoints["session"]
        try:
            encryption_data = await self.get_encryption_key()
        except CapitalAPIError as e:
            return {"success": False, "message": f"Failed to get encryption key: {e.message}"}
        except Exception as e:
            return {"success": False, "message": f"Failed to get encryption key: {e}"}

        encryption_key = encryption_data.get("encryptionKey")
        timestamp = encryption_data.get("timeStamp")
        if not encryption_key or not timestamp:
            return {"success": False, "message": "Encryption key or timestamp missing from server response."}

        password_to_encrypt = f"{self.password}|{timestamp}"
        try:
            encrypted_password = self._rsa_encrypt(encryption_key, password_to_encrypt)
        except Exception as e:
            logger.error("Password encryption error: %s", e)
            return {"success": False, "message": "Password encryption failed."}

        payload = {
            "identifier": self.username,
            "password": encrypted_password,
            "encryptedPassword": True
        }
        headers = {
            "X-CAP-API-KEY": self.api_key or "",
            "Content-Type": "application/json"
        }
        url = self._full_url(path)

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(url, data=json.dumps(payload)) as resp:
                    text = await resp.text()
                    if not resp.ok:
                        try:
                            data = json.loads(text)
                        except Exception:
                            data = text
                        msg = f"Login failed {resp.status}: {data}"
                        logger.error(msg)
                        return {"success": False, "message": msg}

                    # on success, tokens are in headers
                    self.cst_token = resp.headers.get("CST")
                    self.session_token = resp.headers.get("X-SECURITY-TOKEN")

                    if not self.cst_token or not self.session_token:
                        # sometimes tokens may be in body as well; try to parse body for debugging
                        try:
                            body = await resp.json()
                        except Exception:
                            body = text
                        msg = f"Login succeeded but tokens missing; body: {body}"
                        logger.error(msg)
                        return {"success": False, "message": msg}

                    logger.info("Login successful, tokens stored.")
                    return {"success": True, "message": "Login successful."}

        except aiohttp.ClientError as e:
            logger.error("Login request error: %s", e)
            return {"success": False, "message": f"Login request error: {e}"}

    # -------------------------
    # Account / Balances
    # -------------------------
    async def get_position_details(self, deal_id: str) -> dict:
        """
        Bitta ochiq pozitsiya va unga mos instrument (market) haqidagi barcha ma'lumotlarni qaytaradi.
        """
        if not self.cst_token or not self.session_token:
            raise CapitalAPIError(401, "Authentication tokens are missing.")

        path = f"/api/v1/positions/{deal_id}"
        try:
            data = await self._make_request("GET", path)
            return data  # {'position': {...}, 'market': {...}}
        except CapitalAPIError as e:
            logger.error(f"Pozitsiya tafsilotlarini olishda xato: {e.message}")
            return {}
        except Exception as e:
            logger.error(f"Pozitsiya tafsilotlarini olishda kutilmagan xato: {e}")
            return {}

    async def get_account_details(self) -> Dict[str, Any]:
        """
        GET /api/v1/accounts and return the active account dict.
        Prefer 'preferred' account if present, otherwise first element.
        """
        path = self.endpoints["accounts"]
        if not self.cst_token or not self.session_token:
            logger.error("Tokens missing; cannot request account details.")
            raise CapitalAPIError(401, "Authentication tokens are missing.")

        try:
            data = await self._make_request("GET", path)
            accounts = data.get("accounts", []) if isinstance(data, dict) else []
            if not accounts:
                logger.warning("No accounts returned by API.")
                return {}
            # prefer preferred=True, else first
            account = next((a for a in accounts if a.get("preferred") is True), accounts[0])
            return account
        except CapitalAPIError as e:
            logger.error("Error retrieving account details: %s", e.message)
            return {}
        except Exception as e:
            logger.error("Unexpected error retrieving account details: %s", e)
            return {}

    def _extract_available_balance(self, account: Dict[str, Any]) -> str:
        """
        Try several possible fields to extract 'available' funds from account dict.
        Returns string or 'N/A'.
        """
        if not isinstance(account, dict) or not account:
            return "N/A"
        try_order = [
            ("funds", "available"),
            ("funds", "availableCash"),
            ("balance", "available"),
            ("balance", "availableCash"),
            ("balance", "balance"),
            ("accountBalance", "available"),
        ]
        for top, child in try_order:
            val = account.get(top)
            if isinstance(val, dict) and val.get(child) is not None:
                return str(val.get(child))
        for key in ("available", "availableCash", "balance", "equity"):
            if account.get(key) is not None:
                return str(account.get(key))
        return "N/A"

    async def get_all_account_balances(self) -> Dict[str, str]:
        """
        Login to demo and real (if api keys set) and return both balances.
        Restores original instance state after operations.
        """
        real_balance = "Mavjud emas"
        demo_balance = "Mavjud emas"

        original = {
            "account_type": getattr(self, "account_type", None),
            "api_key": getattr(self, "api_key", None),
            "api_key_password": getattr(self, "api_key_password", None),
            "base_url": getattr(self, "base_url", None),
            "websocket_url": getattr(self, "websocket_url", None),
            "cst_token": getattr(self, "cst_token", None),
            "session_token": getattr(self, "session_token", None),
        }
        try:
            # DEMO
            if self.demo_api_key:
                self.account_type = "demo"
                self.api_key = self.demo_api_key
                self.api_key_password = self.demo_api_key_password
                self.base_url = "https://demo-api-capital.backend-capital.com"
                self.websocket_url = "wss://api-streaming-capital.backend-capital.com/connect"
                self.cst_token = None
                self.session_token = None

                login_res = await self.login()
                if login_res.get("success"):
                    acc = await self.get_account_details()
                    val = self._extract_available_balance(acc)
                    demo_balance = f"{val} USD" if val != "N/A" else "N/A"
                else:
                    logger.warning("Demo login failed: %s", login_res.get("message"))

            # REAL
            if self.real_api_key:
                self.account_type = "real"
                self.api_key = self.real_api_key
                self.api_key_password = self.real_api_key_password
                self.base_url = "https://api-capital.backend-capital.com"
                self.websocket_url = "wss://api-streaming-capital.backend-capital.com/connect"
                self.cst_token = None
                self.session_token = None

                login_res = await self.login()
                if login_res.get("success"):
                    acc = await self.get_account_details()
                    val = self._extract_available_balance(acc)
                    real_balance = f"{val} USD" if val != "N/A" else "N/A"
                else:
                    logger.warning("Real login failed: %s", login_res.get("message"))
        finally:
            # restore
            self.account_type = original["account_type"]
            if original["api_key"] is not None:
                self.api_key = original["api_key"]
            if original["api_key_password"] is not None:
                self.api_key_password = original["api_key_password"]
            if original["base_url"] is not None:
                self.base_url = original["base_url"]
            if original["websocket_url"] is not None:
                self.websocket_url = original["websocket_url"]
            self.cst_token = original["cst_token"]
            self.session_token = original["session_token"]

        return {"real": real_balance, "demo": demo_balance}

    # -------------------------
    # Instruments / Price helpers
    # -------------------------
    async def _get_market_info(self, epic: str) -> Dict[str, Any]:
        url = f"{self.endpoints['markets']}/{epic}"
        try:
            return await self._get_json(url)
        except Exception as e:
            logger.error("Error fetching market info for %s: %s", epic, e)
            return {}

    async def _get_last_price(self, epic: str) -> Optional[float]:
        # As fallback we request prices endpoint and try to take last bid/ask average
        url = f"{self.endpoints['prices']}/{epic}"
        try:
            data = await self._get_json(url, params={"resolution": "MINUTE", "max": 10})
            prices = data.get("prices", []) if isinstance(data, dict) else []
            if not prices:
                return None
            last = prices[-1]
            bid = last.get("bid") or last.get("bidPrice") or last.get("bid_level")
            ask = last.get("ask") or last.get("askPrice") or last.get("offer")
            if bid is not None and ask is not None:
                return (float(bid) + float(ask)) / 2.0
            # try alternative keys
            if "level" in last:
                return float(last["level"])
            return None
        except Exception as e:
            logger.warning("Cannot fetch last price for %s: %s", epic, e)
            return None

    def _round_to_step(self, value: float, step: float) -> float:
        if step <= 0:
            return value
        # floor to step
        return (value // step) * step

    async def _resolve_epic(self, currency_pair: str) -> str:
        # Try mapping from ACTIVE_INSTRUMENTS imported from config
        try:
            if currency_pair in ACTIVE_INSTRUMENTS:
                return ACTIVE_INSTRUMENTS[currency_pair]["id"]
        except Exception:
            pass
        return currency_pair

      # -------------------------
    # Orders: create / open / close
    # -------------------------

    async def create_position(
        self,
        currency_pair: str,
        direction: str,
        amount: float = None,
        size: float = None,
    ) -> dict:
        """
        Manual BUY/SELL uchun pozitsiya ochish.
        Kiruvchi:
          - amount: USD miqdor (foydalanuvchi sozlamasidan).
          - size: kontrakt soni (agar berilsa amount ishlatilmaydi).
        """

        direction_u = direction.strip().upper()
        if direction_u not in ("BUY", "SELL"):
            raise ValueError(f"Invalid direction: {direction}")

        # EPIC topamiz (masalan: Tesla -> TSLA)
        epic = await self._resolve_epic(currency_pair)

        # Bozor ma'lumotlari
        mkt = await self._get_market_info(epic)
        min_size, size_step, max_size = 1.0, 1.0, None
        try:
            if "dealSize" in mkt:
                min_size = float(mkt["dealSize"].get("min", min_size))
                size_step = float(mkt["dealSize"].get("step", size_step))
                max_size = float(mkt["dealSize"].get("max", 0)) or None
            elif "dealSizeConfiguration" in mkt:
                cfg = mkt["dealSizeConfiguration"]
                min_size = float(cfg.get("min", min_size))
                size_step = float(cfg.get("step", size_step))
                max_size = float(cfg.get("max", 0)) or None
            elif "minDealSize" in mkt:
                min_size = float(mkt.get("minDealSize", min_size))
            if "maxDealSize" in mkt:
                max_size = float(mkt.get("maxDealSize", 0)) or max_size
        except Exception:
            pass

        # Agar size yo'q bo'lsa — amount asosida hisoblaymiz
        if size is None:
            if amount and amount > 0:
                last_price = await self._get_last_price(epic)
                if last_price and last_price > 0:
                    raw = amount / last_price
                    size = self._round_to_step(raw, size_step)
                else:
                    size = min_size
            else:
                size = min_size

        # Min/max chegaralarga moslashtirish
        if size < min_size:
            size = min_size
        if max_size and size > max_size:
            size = max_size

        payload = {
            "direction": direction_u,
            "epic": epic,
            "size": float(size),
            "orderType": "MARKET",
            "currency": "USD",
            "forceOpen": True,
        }

        try:
            resp = await self._make_request("POST", self.endpoints["open_position"], data=json.dumps(payload))
            deal_ref = resp.get("dealReference") or resp.get("dealId")
            logger.info("Pozitsiya ochildi: %s %s size=%s deal=%s", epic, direction_u, size, deal_ref)
            return {"success": True, "deal_id": deal_ref, "details": resp}
        except Exception as e:
            logger.error("Pozitsiya ochishda xato: %s", e)
            return {"success": False, "error": str(e)}

    async def open_position(self, instrument_id: str, direction: str, amount: float) -> Dict[str, Any]:
        """
        Compatibility helper: open_position expects instrument_id, direction, amount (size).
        This function sends POST to open_position endpoint using 'size' equal to amount (if caller provides correct semantics).
        """
        path = self.endpoints["open_position"]
        if not self.cst_token or not self.session_token:
            raise CapitalAPIError(401, "Authentication tokens are missing.")
        payload = {
            "direction": direction.upper(),
            "epic": instrument_id,
            "orderType": "MARKET",
            "size": amount,
            "forceOpen": True
        }
        resp = await self._make_request("POST", path, data=json.dumps(payload))
        deal_ref = resp.get("dealReference") or resp.get("dealId")
        if not deal_ref:
            raise CapitalAPIError(500, f"Error opening trade: {resp}")
        return {"success": True, "deal_id": deal_ref}

    async def close_position(self, deal_id: Optional[str] = None, position_id: Optional[str] = None, direction: Optional[str] = None, epic: Optional[str] = None, size: Optional[float] = None) -> Dict[str, Any]:
        """
        Close a position. Accepts either deal_id or position_id param (both same).
        If only deal id is provided, tries to send close request with minimal required fields.
        """
        # support both names
        if not deal_id and position_id:
            deal_id = position_id
        if not deal_id:
            return {"success": False, "error": "No deal_id/position_id provided."}

        path = f"{self.endpoints['close_position']}{deal_id}"
        if not self.cst_token or not self.session_token:
            raise CapitalAPIError(401, "Authentication tokens are missing.")

        # if direction given, invert it (closing)
        if direction:
            close_direction = "SELL" if direction.upper() == "BUY" else "BUY"
        else:
            # if no direction, API might accept minimal payload; try to close with DEAL id only
            close_direction = None

        payload = {"dealId": deal_id, "orderType": "MARKET"}
        if close_direction:
            payload["direction"] = close_direction
        if epic:
            payload["epic"] = epic
        if size:
            payload["size"] = size

        resp = await self._make_request("DELETE", path, data=json.dumps(payload))
        # check response for confirmation
        if not (resp.get("dealReference") or resp.get("dealId") or resp.get("status")):
            # still treat as success if no error thrown (API varia)
            logger.warning("Close response did not include explicit reference: %s", resp)
        logger.info("Position %s closed (response: %s)", deal_id, resp)
        return {"success": True, "details": resp}

    # -------------------------
    # Positions / Instruments
    # -------------------------
    async def get_open_positions(self, account_type: str = None) -> List[Dict[str, Any]]:
        """Ochiq pozitsiyalarni olish."""
        try:
            endpoint = "/api/v1/positions"
            result = await self._make_request("GET", endpoint)

            # API javobini tahlil qilish
            if isinstance(result, dict):
                if "positions" in result:
                    positions_list = []
                    for position_item in result["positions"]:
                        if "position" in position_item and "market" in position_item:
                            # 🔥 Position va Market ni birlashtirib qaytaramiz
                            merged = {
                                **position_item["position"],   # barcha position fieldlari
                                **position_item["market"]      # barcha market fieldlari
                            }
                            positions_list.append(merged)
                        elif "position" in position_item:
                            positions_list.append(position_item["position"])
                        else:
                            positions_list.append(position_item)
                    return positions_list

                elif "errorCode" in result:
                    logger.error(f"API xatosi: {result.get('errorCode')} - {result.get('errorMessage', '')}")
                    return []

            elif isinstance(result, list):
                return result

            logger.warning(f"Noma'lum data formati: {type(result)} - {result}")
            return []

        except CapitalAPIError as e:
            logger.error(f"CapitalAPIError in get_open_positions: {e}")
            return []
        except Exception as e:
            logger.error(f"get_open_positions xatosi: {e}")
            return []


    async def debug_positions(self):
        """API javobini debug qilish"""
        try:
            result = await self._make_request("GET", "/api/v1/positions")
            print(f"DEBUG API RESPONSE: {result}")
            print(f"DEBUG RESPONSE TYPE: {type(result)}")
            if isinstance(result, dict):
                print(f"DEBUG DICT KEYS: {result.keys()}")
            return result
        except Exception as e:
            print(f"DEBUG ERROR: {e}")
            return None

    # -------------------------
    # Websocket: connect & subscribe
    # -------------------------
    async def connect_websocket(self, instruments_to_subscribe: List[str]):
        if not self.cst_token or not self.session_token:
            logger.error("Missing tokens to connect to WebSocket. Please log in first.")
            return

        websocket_url_with_tokens = f"{self.websocket_url}?cst={self.cst_token}&securityToken={self.session_token}"

        while True:
            try:
                logger.info("Attempting to connect to WebSocket...")
                async with websockets.connect(websocket_url_with_tokens, ssl=ssl_context) as ws:
                    self.websocket_connection = ws
                    logger.info("Connected to WebSocket.")
                    await self.subscribe_to_prices(instruments_to_subscribe)

                    ping_payload = {"destination": "ping", "cst": self.cst_token, "securityToken": self.session_token}

                    while True:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=600)
                            self.handle_websocket_message(message)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps(ping_payload))
                            logger.info("Sent websocket ping.")
                        except websockets.exceptions.ConnectionClosed as e:
                            logger.error("Websocket closed: %s", e)
                            break
            except Exception as e:
                logger.error("Websocket connection error: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)

    async def subscribe_to_prices(self, epics: List[str]):
        if not self.websocket_connection:
            return
        subscribe_payload = {"destination": "marketData.subscribe", "cst": self.cst_token, "securityToken": self.session_token, "payload": {"epics": epics}}
        try:
            await self.websocket_connection.send(json.dumps(subscribe_payload))
            logger.info("Subscribed to: %s", epics)
        except Exception as e:
            logger.error("Error sending websocket subscribe: %s", e)

    def handle_websocket_message(self, message: str):
        try:
            data = json.loads(message)
            # common destinations: 'quote', 'marketData.update'
            dest = data.get("destination")
            if dest in ("quote", "marketData.update"):
                payload = data.get("payload", {})
                epic = payload.get("epic")
                # some streams use 'bid'/'ofr' or 'bid'/'offer'
                buy = payload.get("bid")
                sell = payload.get("ofr", payload.get("offer"))
                if epic and buy is not None and sell is not None:
                    self.current_prices[epic] = {
    "buy": float(buy),
    "sell": float(sell),
    "timestamp": datetime.utcnow().isoformat() + "Z"
}
                    logger.debug("Price update %s buy=%s sell=%s", epic, buy, sell)
        except json.JSONDecodeError:
            logger.error("Websocket JSON decode error.")
        except Exception as e:
            logger.exception("Error handling websocket message: %s", e)

    # -------------------------
    # Price utilities
    # -------------------------
    async def get_prices(self, instrument_id: str) -> Dict[str, float]:
        return self.current_prices.get(instrument_id, {"buy": 0.0, "sell": 0.0})

    async def get_spread(self, epic_id: str) -> Optional[float]:
        prices = self.current_prices.get(epic_id)
        if not prices:
            return None
        b = prices.get("buy")
        s = prices.get("sell")
        if b is None or s is None:
            return None
        return abs(b - s)


    async def search_markets_by_name(self, search_term: str) -> List[Dict[str, Any]]:
        """
        Bozor nomi bo'yicha qidirish (masalan, 'Bitcoin' yoki 'BTC')
        """
        try:
            result = await self.search_markets(search_term=search_term)
            return result.get("markets", [])
        except Exception as e:
            logger.error(f"Bozor qidirishda xato: {e}")
            return []

    async def get_watchlists(self) -> List[Dict[str, Any]]:
        """
        Watchlist'larni olish
        """
        try:
            return await self._make_request("GET", "/api/v1/watchlists")
        except Exception as e:
            logger.error(f"Watchlist'larni olishda xato: {e}")
            return []

    async def get_watchlist_markets(self, watchlist_id: str) -> List[Dict[str, Any]]:
        """
        Watchlist'dagi bozorlarni olish
        """
        try:
            result = await self._make_request("GET", f"/api/v1/watchlists/{watchlist_id}")
            return result.get("markets", [])
        except Exception as e:
            logger.error(f"Watchlist bozorlarini olishda xato: {e}")
            return []

    # Yangi funksiya: To'g'ri EPIC formatlarini topish
    async def find_correct_epic_format(self, asset_name: str) -> Optional[str]:
        """
        Aktiv nomi bo'yicha to'g'ri EPIC formatini topish
        """
        try:
            # 1. Avvalo, aktiv nomi bo'yicha qidirish
            markets = await self.search_markets_by_name(asset_name)
            
            if markets:
                for market in markets:
                    epic = market.get('epic')
                    instrument_name = market.get('instrument', {}).get('name', '')
                    
                    # Faqat tradeable bozorlarni olish
                    if (epic and market.get('snapshot', {}).get('marketStatus') == 'TRADEABLE' and
                        asset_name.lower() in instrument_name.lower()):
                        logger.info(f"✅ Topildi: {epic} - {instrument_name}")
                        return epic
            
            # 2. Watchlist'lardan qidirish
            watchlists = await self.get_watchlists()
            for watchlist in watchlists:
                watchlist_id = watchlist.get('id')
                watchlist_markets = await self.get_watchlist_markets(watchlist_id)
                
                for market in watchlist_markets:
                    epic = market.get('epic')
                    instrument_name = market.get('instrument', {}).get('name', '')
                    
                    if (epic and asset_name.lower() in instrument_name.lower()):
                        logger.info(f"✅ Watchlistdan topildi: {epic} - {instrument_name}")
                        return epic
            
            # 3. Market navigation orqali qidirish
            market_navigation = await self.get_market_navigation()
            for node in market_navigation.get('nodes', []):
                node_id = node.get('id')
                sub_nodes = await self.get_market_navigation(node_id)
                
                for sub_node in sub_nodes.get('nodes', []):
                    if sub_node.get('name', '').lower() == asset_name.lower():
                        node_markets = await self.get_market_navigation(sub_node.get('id'))
                        for market in node_markets.get('markets', []):
                            epic = market.get('epic')
                            if epic:
                                logger.info(f"✅ Market navigationdan topildi: {epic}")
                                return epic
            
            logger.warning(f"❌ {asset_name} uchun EPIC topilmadi")
            return None
            
        except Exception as e:
            logger.error(f"{asset_name} uchun EPIC qidirishda xato: {e}")
            return None


    async def get_historical_prices(self, epic: str, resolution: str, num_points: int) -> List[Dict[str, Any]]:
        """Tarixiy narxlarni olish - REKURSIYASIZ soddalashtirilgan versiya"""
        try:
            # FAQAT bitta EPIC formatini ishlatish (alternative larsiz)
            path = f"/api/v1/prices/{epic}"
            params = {
                "resolution": resolution,
                "max": num_points,
            }
            
            logger.debug(f"Historical prices so'rovi: {epic}, {resolution}, {num_points}")
            
            # ✅ TO'GRIDAN-TO'G'RI aiohttp dan foydalaning, ichki funksiyalarsiz
            url = self._full_url(path)
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("prices", [])
                    else:
                        logger.error(f"HTTP {response.status}: {await response.text()}")
                        return []
                
        except Exception as e:
            logger.error(f"Historical prices error for {epic}: {e}")
            return []



    async def search_markets(self, search_term: Optional[str] = None, epics: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Bozorlarni qidirish yoki epic lar bo'yicha ma'lumot olish
        """
        params = {}
        if search_term:
            params["searchTerm"] = search_term
        elif epics:
            params["epics"] = ",".join(epics)
        
        try:
            return await self._make_request("GET", "/api/v1/markets", params=params)
        except Exception as e:
            logger.error(f"Market qidirishda xato: {e}")
            return {}

    async def get_market_details(self, epic: str) -> Dict[str, Any]:
        """
        maxsus bozor haqida batafsil ma'lumot olish
        """
        try:
            return await self._make_request("GET", f"/api/v1/markets/{epic}")
        except Exception as e:
            logger.error(f"Market details olishda xato: {e}")
            return {}


    async def fetch_historical_prices(self, node_id, resolution="HOUR", max=500) -> Optional[Dict[str, Any]]:
        """
        Asl API chaqiruvini bajarayotgan metod — fetch_... nomi rekursiyani oldini oladi.
        Returns: dict (API javobi) yoki None.
        """
        try:
            path = f"/api/v1/prices/{node_id}"
            params = {"resolution": resolution, "max": max}

            # Agar klassda _get_json mavjud bo'lsa undan foydalanamiz (tezroq)
            if hasattr(self, "_get_json"):
                data = await self._get_json(path, params=params)
                return data

            # Aks holda aiohttp orqali so'rov yuboramiz
            url = self._full_url(path)
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url, params=params) as resp:
                    if not resp.ok:
                        text = await resp.text()
                        logger.error(f"fetch_historical_prices returned {resp.status}: {text}")
                        return None
                    data = await resp.json()
                    return data

        except Exception as e:
            logger.error(f"fetch_historical_prices error for {node_id}: {e}")
            return None


    async def get_best_historical_prices(self, node_id, max=500) -> Optional[Dict[str, Any]]:
        """Eng yaxshi resolutiondagi tarixiy ma'lumotni topadi (klass ichida)"""
        try:
            resolutions = ["MINUTE", "MINUTE_5", "MINUTE_15", "HOUR", "HOUR_4", "DAY", "WEEK"]

            for res in resolutions:
                # MUHIM: bu yerda self.fetch_historical_prices ni chaqiramiz — rekursiya bo'lmaydi
                data = await self.fetch_historical_prices(node_id, resolution=res, max=max)

                # API javobi turlicha bo'lishi mumkin: dict ichida 'prices' yoki list
                if not data:
                    logger.debug(f"{res}: ma'lumot topilmadi")
                    continue

                prices = data.get("prices") if isinstance(data, dict) else data
                if prices and len(prices) >= 10:
                    logger.info(f"✅ {res} resolutionda {len(prices)} ta ma'lumot topildi")
                    return data

            logger.warning("❌ Hech qanday resolutionda yetarli ma'lumot topilmadi")
            return None

        except Exception as e:
            logger.error(f"Tarixiy ma'lumot olishda xato: {e}")
            return None
