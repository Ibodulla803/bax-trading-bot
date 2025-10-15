# db.py
import asyncio
import json
import os
from typing import Dict, Any, Optional

class InMemoryDB:
    """Ma'lumotlarni xotirada saqlaydi va JSON fayliga yozadi."""
    _data: Dict[str, Dict[str, Any]] = {}
    _lock = asyncio.Lock()
    _file_path = "db.json"

    def __init__(self, user_id: str):
        self._user_id = user_id
        self.load_data()

    def load_data(self):
        """Ma'lumotlarni JSON fayldan yuklaydi."""
        if os.path.exists(self._file_path):
            with open(self._file_path, "r", encoding="utf-8") as f:
                try:
                    self._data = json.load(f)
                except json.JSONDecodeError:
                    self._data = {}

    def save_data(self):
        """Ma'lumotlarni JSON faylga saqlaydi."""
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=4)

    async def save_api(self, api: Any):
        async with self._lock:
            if self._user_id not in self._data:
                self._data[self._user_id] = {"api": api, "settings": {}}
            else:
                self._data[self._user_id]["api"] = api
            self.save_data()

    async def save_settings(self, settings: Dict[str, Any]):
        async with self._lock:
            if self._user_id not in self._data:
                self._data[self._user_id] = {"api": None, "settings": settings}
            else:
                self._data[self._user_id]["settings"] = settings
            self.save_data()

    async def get_settings(self) -> Dict[str, Any]:
        async with self._lock:
            settings = self._data.get(self._user_id, {}).get("settings", {})
            
            # Agar settings bo'sh bo'lsa, default sozlamalarni yuklaymiz
            if not settings:
                from config import DEFAULT_SETTINGS
                settings = DEFAULT_SETTINGS.copy()
                
                # Faol aktivlar uchun default sozlamalarni yaratamiz
                from config import ACTIVE_INSTRUMENTS
                settings["buy_sell_status_per_asset"] = {
                    asset: {"buy": True, "sell": True, "active": True}
                    for asset in ACTIVE_INSTRUMENTS.keys()
                }
                settings["trade_amount_per_asset"] = {
                    asset: 100.0 for asset in ACTIVE_INSTRUMENTS.keys()
                }
                settings["max_trades_per_asset"] = {
                    asset: 3 for asset in ACTIVE_INSTRUMENTS.keys()
                }
                settings["current_trades_per_asset"] = {
                    asset: 0 for asset in ACTIVE_INSTRUMENTS.keys()
                }
                settings["consecutive_losses_per_asset"] = {
                    asset: 0 for asset in ACTIVE_INSTRUMENTS.keys()
                }
                
                # Yangi auto trading sozlamasini qo'shamiz
                settings["auto_trading_enabled"] = True
                
                # Saqlaymiz
                if self._user_id not in self._data:
                    self._data[self._user_id] = {"api": None, "settings": settings}
                else:
                    self._data[self._user_id]["settings"] = settings
                self.save_data()
            
            return settings
