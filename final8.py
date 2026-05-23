import sqlite3
import random
import string
import logging
import asyncio
import httpx
import os
from datetime import datetime, timedelta
from api_client import SyriaAPIClient
from typing import Optional, Dict, Any
from pydantic import BaseModel, ValidationError, field_validator
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
    JobQueue
)
from functools import wraps
from enum import Enum, auto
from config import Config

# =============================================
# إعدادات التسجيل والبيئة
# =============================================
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# =============================================
# ثوابت المحادثة
# =============================================
class WayXBetConversationState(Enum):
    GET_WAYXBET_USERNAME = auto()
    GET_WAYXBET_PASSWORD = auto()

class DepositConversationState(Enum):
    DEPOSIT_METHOD = auto()
    SERITEL_CASH_TRANSACTION = auto()
    SERITEL_CASH_AMOUNT = auto()
    SERITEL_CASH_CODE = auto()  # NEW: لطلب الكود
    SERITEL_AMOUNT_CONFIRM = auto()
    SHAM_CASH_TRANSACTION = auto()
    SHAM_CASH_AMOUNT = auto()
    SHAM_CASH_CODE = auto()  # NEW: لطلب الكود لشام كاش
    SHAM_AMOUNT_CONFIRM = auto()
    USDT_AMOUNT = auto()
    USDT_TRANSACTION = auto()

class WithdrawConversationState(Enum):
    WITHDRAW_METHOD = auto()
    WITHDRAW_SERITEL_PHONE = auto()
    WITHDRAW_SERITEL_AMOUNT = auto()
    WITHDRAW_SERITEL_CONFIRM = auto()
    WITHDRAW_SHAM_ACCOUNT = auto()
    WITHDRAW_SHAM_AMOUNT = auto()
    WITHDRAW_SHAM_CONFIRM = auto()
    WITHDRAW_USDT_ADDRESS = auto()
    WITHDRAW_USDT_NETWORK = auto()
    WITHDRAW_USDT_AMOUNT = auto()
    WITHDRAW_USDT_CONFIRM = auto()

class WayXBetTransferConversationState(Enum):
    WAYXBET_DEPOSIT_AMOUNT = auto()
    WAYXBET_WITHDRAW_AMOUNT = auto()

class GiftBalanceConversationState(Enum):
    ENTER_RECEIVER = auto()
    ENTER_AMOUNT = auto()
    CONFIRM_GIFT = auto()

class VoucherConversationState(Enum):
    ENTER_VOUCHER_CODE = auto()

class PromoCodeConversationState(Enum):
    ENTER_PROMO_AMOUNT = auto()
    ENTER_PROMO_USES = auto()
    CONFIRM_PROMO = auto()

class AdminConversationState(Enum):
    ADMIN_MAIN = auto()
    ADMIN_FINANCE = auto()
    ADMIN_DEPOSIT_OPS = auto()
    ADMIN_WITHDRAW_OPS = auto()
    ADMIN_USER_OPS = auto()
    ADMIN_GIFTS = auto()
    ADMIN_BROADCAST = auto()
    ADMIN_MAINTENANCE = auto()
    ADMIN_COMMISSION_RATE = auto()
    ADMIN_CHANNELS_MENU = auto()
    ADMIN_CHANGE_CHANNEL = auto()
    
    # تعديل المستخدمين
    ADMIN_EDIT_BALANCE_USER = auto()
    ADMIN_EDIT_BALANCE_AMOUNT = auto()
    ADMIN_BAN_USER = auto()
    ADMIN_USER_HISTORY_USER = auto()
    ADMIN_USER_HISTORY_DAYS = auto()
    ADMIN_DELETE_USER_CONFIRM = auto()
    ADMIN_LINK_ACCOUNT_USER = auto()
    ADMIN_LINK_ACCOUNT_ID = auto()
    ADMIN_LINK_ACCOUNT_CONFIRM = auto()
    ADMIN_REFERRALS_USER = auto()
    ADMIN_SEND_MESSAGE_USER = auto()
    ADMIN_SEND_MESSAGE_TEXT = auto()
    
    # الكواد والهدايا
    ADMIN_CREATE_VOUCHER_AMOUNT = auto()
    ADMIN_CREATE_VOUCHER_COUNT = auto()
    ADMIN_CREATE_PROMO_AMOUNT = auto()
    ADMIN_CREATE_PROMO_USES = auto()
    
    # التدفقات المالية
    ADMIN_VIEW_WALLET_BALANCE = auto()
    ADMIN_TOGGLE_DEPOSIT_METHOD = auto()
    ADMIN_TOGGLE_WITHDRAW_METHOD = auto()
    ADMIN_CHANGE_COMMISSION = auto()
    ADMIN_CHANGE_COMMISSION_VALUE = auto()
    ADMIN_CHANGE_SERITEL = auto()
    ADMIN_CHANGE_SERITEL_CONFIRM = auto()
    ADMIN_CHANGE_SHAM = auto()
    ADMIN_CHANGE_SHAM_CONFIRM = auto()
    ADMIN_CHANGE_USD_RATE = auto()
    ADMIN_CHANGE_USDT_BEP20 = auto()
    ADMIN_CHANGE_USDT_TRC20 = auto()
    
    # البونص
    ADMIN_BONUS_METHOD = auto()
    ADMIN_BONUS_TYPE = auto()
    ADMIN_BONUS_PERCENT = auto()
    
    # البث والصيانة
    ADMIN_BROADCAST_MESSAGE = auto()
    ADMIN_MAINTENANCE_TEXT = auto()


    # =============================================
# نماذج البيانات والتحقق
# =============================================
class PlayerRegistration(BaseModel):
    username: str
    password: str
    phone: str
    email: Optional[str] = None

    @field_validator('phone')
    def validate_phone(cls, v):
        if not v.isdigit() or len(v) < 8:
            raise ValueError('رقم الهاتف يجب أن يحتوي على 8 أرقام على الأقل')
        return v

    @field_validator('username')
    def validate_username(cls, v):
        if ' ' in v:
            raise ValueError('اسم المستخدم يجب ألا يحتوي على مسافات')
        if len(v) < 4:
            raise ValueError('اسم المستخدم يجب أن يكون 4 أحرف على الأقل')
        return v

# =============================================
# واجهة WayXBet API
# =============================================
class WayXBetPlayerRegistrar:
    def __init__(self):
        self.base_url = Config.WAYXBET_BASE_URL
        self.cookies = {}
        self.headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers=self.headers
        )
        self.credentials = {
            "username": Config.WAYXBET_USERNAME,
            "password": Config.WAYXBET_PASSWORD
        }

    async def __aenter__(self):
        await self.login(**self.credentials)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def login(self, username: str, password: str) -> bool:
        try:
            payload = {"username": username, "password": password}
            response = await self.client.post(f"{self.base_url}/User/signIn", json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("status", False):
                cookies = response.cookies.jar
                for cookie in cookies:
                    self.cookies[cookie.name] = cookie.value
                logger.info("تم تسجيل الدخول إلى WayXBet بنجاح")
                return True
            logger.error("فشل تسجيل الدخول: لا توجد جلسة صالحة")
            return False
        except Exception as e:
            logger.error(f"خطأ في تسجيل الدخول: {str(e)}", exc_info=True)
            return False

    async def register_player(self, player_data: PlayerRegistration) -> dict:
        try:
            validated_data = player_data.model_dump()
        except ValidationError as e:
            errors = "\n".join([f"{error['loc'][0]}: {error['msg']}" for error in e.errors()])
            return {"success": False, "message": f"بيانات غير صالحة:\n{errors}"}

        payload = {
            "player": {
                "email": validated_data.get("email", ""),
                "login": validated_data["username"],
                "parentId": 2502446,
                "password": validated_data["password"],
                "phoneNumber": validated_data["phone"],
            }
        }

        logger.info(f"جاري تسجيل لاعب جديد: {validated_data['username']}")
        try:
            response = await self.client.post(
                f"{self.base_url}/Player/registerPlayer",
                json=payload,
                cookies=self.cookies
            )
            data = response.json()

            if data.get("status", False) and data.get("result") == 1:
                player_id = await self.get_player_id(validated_data["username"])
                return {
                    "success": True,
                    "message": "تم تسجيل اللاعب بنجاح",
                    "player_id": player_id or "غير معروف",
                    "raw_response": data
                }

            error_msg = data.get("message", "فشل في تسجيل اللاعب")
            if "username" in error_msg.lower():
                error_msg = "اسم المستخدم موجود مسبقاً"
            elif "phone" in error_msg.lower():
                error_msg = "رقم الهاتف مستخدم سابقاً"

            return {"success": False, "message": error_msg, "raw_response": data}
        except Exception as e:
            logger.error(f"خطأ غير متوقع في تسجيل اللاعب: {str(e)}", exc_info=True)
            return {"success": False, "message": f"حدث خطأ غير متوقع: {str(e)}", "raw_response": None}

    async def get_player_id(self, username: str) -> Optional[str]:
        try:
            payload = {
                "start": 0,
                "limit": 1,
                "filter": {"username": username},
                "isNextPage": False,
                "searchBy": {"getPlayersFromChildrenLists": username}
            }
            response = await self.client.post(
                f"{self.base_url}/Player/getPlayersForCurrentAgent",
                json=payload,
                cookies=self.cookies
            )
            data = response.json()
            if data.get("status", False) and data["result"]["records"]:
                return data["result"]["records"][0]["playerId"]
            return None
        except Exception as e:
            logger.error(f"خطأ في جلب ID اللاعب: {str(e)}")
            return None

    async def get_player_info_by_id(self, player_id: str) -> Optional[dict]:
        """جلب معلومات اللاعب عن طريق معرف اللاعب"""
        try:
            payload = {
                "start": 0,
                "limit": 1,
                "filter": {"playerId": int(player_id)},
                "isNextPage": False,
                "searchBy": {"getPlayersFromChildrenLists": str(player_id)}
            }
            response = await self.client.post(
                f"{self.base_url}/Player/getPlayersForCurrentAgent",
                json=payload,
                cookies=self.cookies
            )
            data = response.json()
            if data.get("status", False) and data["result"]["records"]:
                return data["result"]["records"][0]
            return None
        except Exception as e:
            logger.error(f"خطأ في جلب معلومات اللاعب: {str(e)}")
            return None

    async def deposit_to_player(self, player_id: str, amount: float) -> dict:
        try:
            payload = {
                "playerId": int(player_id),
                "amount": float(amount),
                "comment": "إيداع من البوت",
                "currency": "NSP",
                "currencyCode": "NSP",
                "moneyStatus": 5
            }
            response = await self.client.post(
                f"{self.base_url}/Player/depositToPlayer",
                json=payload,
                cookies=self.cookies
            )
            data = response.json()
            if data.get("status", False):
                return {"success": True, "message": "تم الإيداع بنجاح", "new_balance": data.get("result", {}).get("balance", 0)}
            return {"success": False, "message": data.get("message", "فشل في عملية الإيداع")}
        except Exception as e:
            logger.error(f"خطأ في عملية الإيداع: {str(e)}")
            return {"success": False, "message": f"حدث خطأ غير متوقع: {str(e)}"}

    async def withdraw_from_player(self, player_id: str, amount: float) -> dict:
        try:
            payload = {
                "playerId": int(player_id),
                "amount": -float(amount),
                "comment": "سحب من البوت",
                "currency": "NSP",
                "currencyCode": "NSP",
                "moneyStatus": 5
            }
            response = await self.client.post(
                f"{self.base_url}/Player/withdrawFromPlayer",
                json=payload,
                cookies=self.cookies
            )
            data = response.json()
            if data.get("status", False):
                return {"success": True, "message": "تم السحب بنجاح", "new_balance": data.get("result", {}).get("balance", 0)}
            return {"success": False, "message": data.get("message", "فشل في عملية السحب")}
        except Exception as e:
            logger.error(f"خطأ في عملية السحب: {str(e)}")
            return {"success": False, "message": f"حدث خطأ غير متوقع: {str(e)}"}

    async def get_player_balance(self, player_id: str) -> dict:
        try:
            payload = {"id": int(player_id), "playerId": int(player_id)}
            response = await self.client.post(
                f"{self.base_url}/Player/getPlayerBalanceById",
                json=payload,
                cookies=self.cookies
            )
            data = response.json()
            if data.get("status", False) and data.get("result"):
                return {"success": True, "balance": data["result"][0]["balance"], "currency": data["result"][0]["currencyCode"]}
            return {"success": False, "message": data.get("message", "فشل في جلب الرصيد")}
        except Exception as e:
            logger.error(f"خطأ في جلب رصيد اللاعب: {str(e)}")
            return {"success": False, "message": f"حدث خطأ غير متوقع: {str(e)}"}

    async def get_agent_balance(self) -> dict:
        """جلب رصيد المحفظة الخاصة بالوكيل"""
        try:
            response = await self.client.post(
                f"{self.base_url}/User/getAgentBalance",
                json={},
                cookies=self.cookies
            )
            data = response.json()
            if data.get("status", False):
                return {"success": True, "balance": data.get("result", {}).get("balance", 0)}
            return {"success": False, "message": data.get("message", "فشل في جلب رصيد المحفظة")}
        except Exception as e:
            logger.error(f"خطأ في جلب رصيد المحفظة: {str(e)}")
            return {"success": False, "message": f"حدث خطأ غير متوقع: {str(e)}"}
        

        # =============================================
# دوال مساعدة
# =============================================
def generate_random_phone():
    return ''.join(random.choices(string.digits, k=8))

def generate_random_email():
    name = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"{name}@gmail.com"

def get_main_keyboard():
    """إرجاع لوحة المفاتيح الرئيسية بشكل موحد"""
    buttons = [
        [Config.MAIN_SITE_NAME],
        ["⬇️ الشحن في البوت", "⬆️ السحب من البوت"],
        ["💰 الرصيد", "🤑 دعوة الأصدقاء"],
        ["📜 الشروط والأحكام", "📩 التواصل مع الدعم"]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_admin_keyboard():
    """إرجاع لوحة مفاتيح الأدمن الرئيسية (زرين بجانب بعض)"""
    buttons = [
        ["🔧 عمليات المستخدمين", "💰 التدفقات المالية"],
        ["🎁 الهدايا والعروض", "📢 بث رسالة جماعية"],
        ["🛠 تفعيل/تعطيل الصيانة", "🛠 حالة الصيانة"],
        ["📊 نسبة الإحالات", "📡 إعدادات القنوات"]
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# =============================================
# إدارة قاعدة البيانات
# =============================================
class DatabaseManager:
    def __init__(self, db_name='bot.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if hasattr(self, 'conn'):
            self.conn.close()

    def get_commission_rate_db(self):
     """جلب نسبة الإحالات من قاعدة البيانات"""
     return self.get_float_setting('commission_rate', 0.02)

    def set_commission_rate_db(self, rate):
     """تحديث نسبة الإحالات في قاعدة البيانات"""
     return self.set_setting('commission_rate', str(rate))    

    # دوال إعدادات القنوات
    def get_channel_setting(self, key, default):
     """جلب إعداد قناة من قاعدة البيانات"""
     return self.get_setting(key, default)

    def set_channel_setting(self, key, value):
     """تحديث إعداد قناة في قاعدة البيانات"""
     return self.set_setting(key, value)

    def get_main_channel(self):
     """جلب قناة البوت الرئيسية"""
     return self.get_setting('main_channel', Config.CHANNEL_USERNAME)

    def set_main_channel(self, channel):
     """تحديث قناة البوت الرئيسية"""
     return self.set_setting('main_channel', channel)

    def get_notification_channel(self):
     """جلب قناة الإشعارات"""
     return self.get_setting('notification_channel', Config.NOTIFICATION_GROUP_USERNAME)

    def set_notification_channel(self, channel):
     """تحديث قناة الإشعارات"""
     return self.set_setting('notification_channel', channel)

    def get_reports_channel(self):
     """جلب قناة التقارير"""
     return self.get_setting('reports_channel', Config.REPORTS_CHANNEL_USERNAME)

    def set_reports_channel(self, channel):
     """تحديث قناة التقارير"""
     return self.set_setting('reports_channel', channel)

    def get_errors_channel(self):
     """جلب قناة الأخطاء"""
     return self.get_setting('errors_channel', Config.ERRORS_CHANNEL_USERNAME)

    def set_errors_channel(self, channel):
     """تحديث قناة الأخطاء"""
     return self.set_setting('errors_channel', channel)   
    
    # =============================================
# دوال الإعدادات العامة
# =============================================
    def get_setting(self, key: str, default: str = None) -> str:
     """الحصول على قيمة إعداد من قاعدة البيانات"""
     try:
        cursor = self.conn.execute('SELECT setting_value FROM settings WHERE setting_key = ?', (key,))
        row = cursor.fetchone()
        return row['setting_value'] if row else default
     except Exception as e:
        logger.error(f"خطأ في جلب الإعداد {key}: {e}")
        return default

    def set_setting(self, key: str, value: str):
     """تحديث قيمة إعداد في قاعدة البيانات"""
     try:
        self.conn.execute('''
        INSERT OR REPLACE INTO settings (setting_key, setting_value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, value))
        self.conn.commit()
        return True
     except Exception as e:
        logger.error(f"خطأ في تحديث الإعداد {key}: {e}")
        return False

    def get_float_setting(self, key: str, default: float = 0) -> float:
     """الحصول على إعداد رقمي (float)"""
     value = self.get_setting(key)
     try:
        return float(value) if value else default
     except (ValueError, TypeError):
        return default

    def get_int_setting(self, key: str, default: int = 0) -> int:
     """الحصول على إعداد رقمي (int)"""
     value = self.get_setting(key)
     try:
        return int(value) if value else default
     except (ValueError, TypeError):
        return default



    def create_tables(self):
        with self.conn:
            # جدول المستخدمين
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                telegram_username TEXT,
                bot_username TEXT UNIQUE,
                bot_balance REAL DEFAULT 0,
                wayxbet_username TEXT UNIQUE,
                wayxbet_password TEXT,
                wayxbet_player_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_banned BOOLEAN DEFAULT 0,
                last_voucher_redemption TIMESTAMP
            )''')

            # جدول طلبات السحب
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                method TEXT,
                amount REAL,
                commission REAL,
                total_amount REAL,
                phone TEXT,
                account TEXT,
                usdt_address TEXT,
                usdt_network TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                message_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            # جدول المحافظ
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                currency TEXT DEFAULT 'SYP',
                balance REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            # جدول الإداريين
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER UNIQUE,
                permissions TEXT DEFAULT 'full',
                maintenance_message TEXT,
                seritel_cash_code TEXT,
                sham_cash_account TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')

            # جدول عمليات الشحن
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                method TEXT,
                amount REAL,
                transaction_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            # جدول الإحالات
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users (id),
                FOREIGN KEY (referred_id) REFERENCES users (id)
            )''')

            # جدول العمولات
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS commissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referral_id INTEGER,
                amount REAL,
                source_user_id INTEGER,
                deposit_amount REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referral_id) REFERENCES referrals (id),
                FOREIGN KEY (source_user_id) REFERENCES users (id)
            )''')

            # جدول البونص
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS bonuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                bonus_type TEXT,
                method TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            # جدول أكواد الهدايا
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                amount REAL,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                used_by INTEGER,
                used_at TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users (id),
                FOREIGN KEY (used_by) REFERENCES users (id)
            )''')

            # جدول أكواد البرومو (متعددة الاستخدام)
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                amount REAL,
                max_uses INTEGER,
                current_uses INTEGER DEFAULT 0,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users (id)
            )''')

            # جدول استخدامات أكواد البرومو
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS promo_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id INTEGER,
                user_id INTEGER,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(promo_id, user_id),
                FOREIGN KEY (promo_id) REFERENCES promo_codes (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            # جدول طلبات الشحن
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                method TEXT,
                amount REAL,
                transaction_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                message_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            # جدول طرق الشحن والسحب
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS payment_methods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method_name TEXT,
                method_type TEXT,
                is_enabled BOOLEAN DEFAULT 1,
                commission_percentage REAL DEFAULT 0,
                UNIQUE(method_name, method_type)
            )''')

            # جدول البونص الفردي والجماعي
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS bonus_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method_name TEXT,
                bonus_percentage REAL,
                bonus_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')

            # جداول WayXBet
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS wayxbet_deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                player_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS wayxbet_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                player_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )''')

            # جدول الإهداءات
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS gifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                receiver_id INTEGER,
                amount REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users (id),
                FOREIGN KEY (receiver_id) REFERENCES users (id)
            )''')

                     # في دالة create_tables، تأكد من وجود هذا الجدول
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')

# وأضف الإعدادات الافتراضية
        default_settings = [
    # ... الإعدادات الموجودة ...
               ('commission_rate', '0.02'),
               ('main_channel', Config.CHANNEL_USERNAME),
               ('notification_channel', Config.NOTIFICATION_GROUP_USERNAME),
               ('reports_channel', Config.REPORTS_CHANNEL_USERNAME),
               ('errors_channel', Config.ERRORS_CHANNEL_USERNAME),
]

        for key, value in default_settings:
              self.conn.execute('''
              INSERT OR IGNORE INTO settings (setting_key, setting_value)
              VALUES (?, ?)
              ''', (key, value))

            # إضافة الأدمن إذا لم يكن موجوداً
        for admin_id in Config.ADMIN_IDS:
                self.conn.execute('INSERT OR IGNORE INTO admin_settings (admin_id) VALUES (?)', (admin_id,))

            # إضافة طرق الدفع الافتراضية
        methods = [
                ('سيريتيل كاش', 'deposit', 0),
                ('شام كاش', 'deposit', 0),
                ('USDT', 'deposit', 0),
                ('سيريتيل كاش', 'withdraw', Config.SERITEL_WITHDRAW_COMMISSION * 100),
                ('شام كاش', 'withdraw', Config.SHAM_WITHDRAW_COMMISSION * 100),
                ('USDT', 'withdraw', Config.USDT_WITHDRAW_COMMISSION * 100)
            ]
        for method_name, method_type, commission in methods:
                self.conn.execute('''
                INSERT OR IGNORE INTO payment_methods (method_name, method_type, is_enabled, commission_percentage)
                VALUES (?, ?, 1, ?)
                ''', (method_name, method_type, commission))

    # =============================================
    # دوال المستخدمين
    # =============================================
    def add_user(self, telegram_id, telegram_username, referrer_id=None):
        """إضافة مستخدم جديد"""
        bot_username = self.generate_unique_username(telegram_username)
        
        with self.conn:
            self.conn.execute('''
            INSERT OR IGNORE INTO users (telegram_id, telegram_username, bot_username)
            VALUES (?, ?, ?)
            ''', (telegram_id, telegram_username, bot_username))
            
            cursor = self.conn.execute('SELECT id FROM users WHERE telegram_id = ?', (telegram_id,))
            user_row = cursor.fetchone()
            
            if user_row:
                user_id = user_row['id']
                
                # إنشاء محفظة للمستخدم
                self.conn.execute('INSERT OR IGNORE INTO wallets (user_id) VALUES (?)', (user_id,))
                
                # تسجيل الإحالة إذا وجدت
                if referrer_id and str(referrer_id) != str(telegram_id):
                    referrer = self.get_user_by_telegram_id(int(referrer_id))
                    if referrer and referrer['id'] != user_id:
                        self.conn.execute('''
                        INSERT OR IGNORE INTO referrals (referrer_id, referred_id)
                        VALUES (?, ?)
                        ''', (referrer['id'], user_id))
                
                return user_id
        return None

    def generate_unique_username(self, telegram_username=None):
        """إنشاء اسم مستخدم فريد يعتمد على اسم المستخدم في تيليجرام"""
        if telegram_username:
            base = telegram_username.replace('@', '').strip()
        else:
            base = ''.join(random.choices(string.ascii_letters, k=4))
        
        # تنظيف الاسم الأساسي
        base = ''.join(c for c in base if c.isalnum() or c == '_')
        if len(base) < 3:
            base = ''.join(random.choices(string.ascii_letters, k=4))
        
        # محاولة استخدام الاسم الأساسي أولاً
        cursor = self.conn.execute('SELECT 1 FROM users WHERE LOWER(bot_username) = LOWER(?)', (base,))
        if not cursor.fetchone():
            return base
        
        # إضافة أرقام عشوائية
        for _ in range(20):
            suffix = ''.join(random.choices(string.digits, k=random.randint(2, 4)))
            username = f"{base}{suffix}"
            if len(username) <= 16:
                cursor = self.conn.execute('SELECT 1 FROM users WHERE LOWER(bot_username) = LOWER(?)', (username,))
                if not cursor.fetchone():
                    return username
        
        # اسم عشوائي كامل كحل أخير
        while True:
            length = random.randint(5, 8)
            characters = string.ascii_letters + string.digits
            username = ''.join(random.choice(characters) for _ in range(length))
            cursor = self.conn.execute('SELECT 1 FROM users WHERE LOWER(bot_username) = LOWER(?)', (username,))
            if not cursor.fetchone():
                return username

    def update_wayxbet_account(self, telegram_id, wayxbet_username, wayxbet_password, wayxbet_player_id):
        with self.conn:
            cursor = self.conn.execute('''
            UPDATE users 
            SET wayxbet_username = ?, wayxbet_password = ?, wayxbet_player_id = ?
            WHERE telegram_id = ?
            ''', (wayxbet_username, wayxbet_password, wayxbet_player_id, telegram_id))
            return cursor.rowcount > 0

    def link_wayxbet_account(self, bot_username, player_id):
        """ربط حساب WayXBet بمستخدم البوت"""
        with self.conn:
            cursor = self.conn.execute('''
            UPDATE users 
            SET wayxbet_player_id = ?
            WHERE LOWER(bot_username) = LOWER(?)
            ''', (player_id, bot_username))
            return cursor.rowcount > 0

    def get_user(self, telegram_id):
        cursor = self.conn.execute('''
        SELECT u.*, w.balance AS wallet_balance 
        FROM users u
        LEFT JOIN wallets w ON u.id = w.user_id
        WHERE u.telegram_id = ?
        ''', (telegram_id,))
        return cursor.fetchone()

    def get_user_by_telegram_id(self, telegram_id):
        cursor = self.conn.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        return cursor.fetchone()

    def get_user_by_username(self, username):
        username = username.replace('@', '').strip()
        cursor = self.conn.execute('''
        SELECT u.*, w.balance AS wallet_balance 
        FROM users u
        LEFT JOIN wallets w ON u.id = w.user_id
        WHERE LOWER(u.bot_username) = LOWER(?) OR LOWER(u.telegram_username) = LOWER(?)
        ''', (username, username))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id):
        cursor = self.conn.execute('''
        SELECT u.*, w.balance AS wallet_balance 
        FROM users u
        LEFT JOIN wallets w ON u.id = w.user_id
        WHERE u.id = ?
        ''', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def is_admin(self, telegram_id):
        cursor = self.conn.execute('SELECT 1 FROM admin_settings WHERE admin_id = ?', (telegram_id,))
        return cursor.fetchone() is not None

    def update_wallet_balance(self, user_id, amount):
        with self.conn:
            self.conn.execute('UPDATE wallets SET balance = balance + ? WHERE user_id = ?', (amount, user_id))

    def delete_user(self, bot_username):
        """حذف مستخدم وفك ارتباطه"""
        username = bot_username.replace('@', '').strip()
        with self.conn:
            user = self.get_user_by_username(username)
            if not user:
                return False, "لم يتم العثور على المستخدم"
            
            # فك الارتباط مع الموقع
            self.conn.execute('UPDATE users SET wayxbet_player_id = NULL, wayxbet_username = NULL WHERE id = ?', (user['id'],))
            
            return True, f"تم حذف المستخدم @{user['bot_username']} وفك ارتباطه بالموقع"

    def ban_user(self, username):
        username = username.replace('@', '').strip()
        with self.conn:
            cursor = self.conn.execute('''
            UPDATE users SET is_banned = 1
            WHERE LOWER(bot_username) = LOWER(?) OR LOWER(telegram_username) = LOWER(?)
            ''', (username, username))
            return cursor.rowcount > 0

    def unban_user(self, username):
        username = username.replace('@', '').strip()
        with self.conn:
            cursor = self.conn.execute('''
            UPDATE users SET is_banned = 0
            WHERE LOWER(bot_username) = LOWER(?) OR LOWER(telegram_username) = LOWER(?)
            ''', (username, username))
            return cursor.rowcount > 0

    # =============================================
    # دوال الصيانة والإعدادات
    # =============================================
    def set_maintenance_message(self, message):
        try:
            self.conn.execute('''
            UPDATE admin_settings SET maintenance_message = ?
            WHERE admin_id IN (SELECT admin_id FROM admin_settings LIMIT 1)
            ''', (message if message and message.strip() else None,))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error setting maintenance message: {e}")

    def get_maintenance_message(self):
        try:
            cursor = self.conn.execute('SELECT maintenance_message FROM admin_settings LIMIT 1')
            row = cursor.fetchone()
            return row['maintenance_message'] if row and row['maintenance_message'] and row['maintenance_message'].strip() else None
        except Exception as e:
            logger.error(f"Error getting maintenance message: {e}")
            return None

    # =============================================
    # دوال العمولات والإحالات
    # =============================================
    def add_commission(self, referrer_id, amount, source_user_id):
        """إضافة عمولة للمُحيل"""
        commission = amount * Config.COMMISSION_RATE
        with self.conn:
            self.conn.execute('UPDATE wallets SET balance = balance + ? WHERE user_id = ?', (commission, referrer_id))
            cursor = self.conn.execute('SELECT id FROM referrals WHERE referrer_id = ? AND referred_id = ?', (referrer_id, source_user_id))
            referral = cursor.fetchone()
            if referral:
                self.conn.execute('INSERT INTO commissions (referral_id, amount, source_user_id, deposit_amount) VALUES (?, ?, ?, ?)',
                                (referral['id'], commission, source_user_id, amount))
        return commission

    def get_referrals(self, referrer_id):
        cursor = self.conn.execute('''
        SELECT r.*, u.bot_username, u.telegram_username, u.created_at,
               (SELECT COALESCE(SUM(c.amount), 0) FROM commissions c WHERE c.referral_id = r.id) as total_commission
        FROM referrals r
        JOIN users u ON r.referred_id = u.id
        WHERE r.referrer_id = ?
        ''', (referrer_id,))
        return cursor.fetchall()

    def get_referrals_count(self, referrer_id):
        cursor = self.conn.execute('SELECT COUNT(*) AS count FROM referrals WHERE referrer_id = ?', (referrer_id,))
        row = cursor.fetchone()
        return row['count'] if row else 0

    def get_commissions(self, referrer_id):
        cursor = self.conn.execute('''
        SELECT COALESCE(SUM(c.amount), 0) AS total 
        FROM commissions c
        JOIN referrals r ON c.referral_id = r.id
        WHERE r.referrer_id = ?
        ''', (referrer_id,))
        row = cursor.fetchone()
        return row['total'] if row else 0

    def get_referrer_for_user(self, user_id):
        """جلب المُحيل للمستخدم"""
        cursor = self.conn.execute('SELECT referrer_id FROM referrals WHERE referred_id = ?', (user_id,))
        row = cursor.fetchone()
        return row['referrer_id'] if row else None

    # =============================================
    # دوال الإحصائيات والأرصدة
    # =============================================
    def get_total_accounts(self):
        cursor = self.conn.execute('SELECT COUNT(*) AS total FROM users')
        row = cursor.fetchone()
        return row['total'] if row else 0

    def get_total_balance(self):
        cursor = self.conn.execute('''
        SELECT COALESCE(SUM(w.balance), 0) AS total 
        FROM wallets w
        JOIN users u ON w.user_id = u.id
        ''')
        row = cursor.fetchone()
        return row['total'] if row else 0

    def get_top_balances(self, limit=10):
        cursor = self.conn.execute('''
        SELECT u.bot_username, u.telegram_username, w.balance
        FROM wallets w
        JOIN users u ON w.user_id = u.id
        ORDER BY w.balance DESC
        LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

    # =============================================
    # دوال السجلات
    # =============================================
    def get_user_history(self, username, days=None):
     """جلب سجل المستخدم مع إمكانية تحديد عدد الأيام"""
     user = self.get_user_by_username(username)
     if not user:
        return None

     user_id = user['id']
    
    # عدد المتغيرات لكل جدول هو 2 (user_id + date_filter)
     if days:
        # كل استعلام يحتاج 2 من المتغيرات، لدينا 6 استعلامات = 12 متغير
        params = [user_id, f'-{days} days'] * 6
        date_filter = "AND created_at >= datetime('now', ?)"
     else:
        params = [user_id] * 6
        date_filter = ""
    
     try:
        cursor = self.conn.execute(f'''
        SELECT 'ايداع' as type, amount, method, created_at 
        FROM deposits WHERE user_id = ? {date_filter}
        UNION ALL
        SELECT 'سحب' as type, amount, method, created_at 
        FROM withdrawals WHERE user_id = ? {date_filter}
        UNION ALL
        SELECT 'تعبئة موقع' as type, amount, 'WAYXBET' as method, created_at 
        FROM wayxbet_deposits WHERE user_id = ? {date_filter}
        UNION ALL
        SELECT 'سحب من موقع' as type, amount, 'WAYXBET' as method, created_at 
        FROM wayxbet_withdrawals WHERE user_id = ? {date_filter}
        UNION ALL
        SELECT 'اهداء' as type, amount, 'GIFT' as method, created_at 
        FROM gifts WHERE sender_id = ? {date_filter}
        UNION ALL
        SELECT 'استلام هدية' as type, amount, 'GIFT' as method, created_at 
        FROM gifts WHERE receiver_id = ? {date_filter}
        ORDER BY created_at DESC
        ''', params)
        return cursor.fetchall()
     except sqlite3.OperationalError as e:
        logger.error(f"خطأ في استعلام السجل: {e}")
        return []

    # =============================================
    # دوال طرق الدفع
    # =============================================
    def get_payment_methods(self, method_type):
        cursor = self.conn.execute('SELECT id, method_name, is_enabled, commission_percentage FROM payment_methods WHERE method_type = ?', (method_type,))
        return cursor.fetchall()

    def toggle_payment_method(self, method_id):
        with self.conn:
            self.conn.execute('UPDATE payment_methods SET is_enabled = NOT is_enabled WHERE id = ?', (method_id,))
            cursor = self.conn.execute('SELECT method_name, is_enabled FROM payment_methods WHERE id = ?', (method_id,))
            return cursor.fetchone()

    def toggle_all_payment_methods(self, method_type, enable):
        with self.conn:
            self.conn.execute('UPDATE payment_methods SET is_enabled = ? WHERE method_type = ?', (1 if enable else 0, method_type))

    def get_enabled_payment_methods(self, method_type):
        cursor = self.conn.execute('SELECT method_name FROM payment_methods WHERE method_type = ? AND is_enabled = 1', (method_type,))
        return [row['method_name'] for row in cursor.fetchall()]

    def is_payment_method_enabled(self, method_name, method_type):
        cursor = self.conn.execute('SELECT is_enabled FROM payment_methods WHERE method_name = ? AND method_type = ?', (method_name, method_type))
        row = cursor.fetchone()
        return row and row['is_enabled'] == 1

    def get_method_commission(self, method_name, method_type):
        cursor = self.conn.execute('SELECT commission_percentage FROM payment_methods WHERE method_name = ? AND method_type = ?', (method_name, method_type))
        row = cursor.fetchone()
        return row['commission_percentage'] if row else 0

    def update_method_commission(self, method_name, method_type, commission):
        with self.conn:
            self.conn.execute('UPDATE payment_methods SET commission_percentage = ? WHERE method_name = ? AND method_type = ?',
                            (commission, method_name, method_type))

    # =============================================
    # دوال البونص
    # =============================================
    def add_bonus(self, user_id, amount, bonus_type='manual', method=None):
        with self.conn:
            self.conn.execute('UPDATE wallets SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
            self.conn.execute('INSERT INTO bonuses (user_id, amount, bonus_type, method) VALUES (?, ?, ?, ?)',
                            (user_id, amount, bonus_type, method))

    def get_bonus_settings(self, method_name=None):
     """جلب إعدادات البونص"""
     try:
        if method_name:
            cursor = self.conn.execute(
                'SELECT * FROM bonus_settings WHERE method_name = ?', 
                (method_name,)
            )
        else:
            cursor = self.conn.execute('SELECT * FROM bonus_settings')
        return cursor.fetchall()
     except sqlite3.ProgrammingError as e:
        logger.error(f"خطأ في get_bonus_settings: {e}")
        return []

    def add_bonus_setting(self, method_name, bonus_percentage, bonus_type):
        with self.conn:
            self.conn.execute('DELETE FROM bonus_settings WHERE method_name = ? AND bonus_type = ?', (method_name, bonus_type))
            self.conn.execute('INSERT INTO bonus_settings (method_name, bonus_percentage, bonus_type) VALUES (?, ?, ?)',
                            (method_name, bonus_percentage, bonus_type))

    def get_deposit_bonus(self, method_name):
        """الحصول على نسبة البونص لطريقة شحن محددة"""
        cursor = self.conn.execute('SELECT bonus_percentage FROM bonus_settings WHERE method_name = ? AND bonus_type = ?', 
                                 (method_name, 'collective'))
        row = cursor.fetchone()
        return row['bonus_percentage'] if row else 0

    # =============================================
    # دوال الكواد والهدايا
    # =============================================
    def create_voucher(self, code, amount, created_by=None, expires_days=30):
        expires_at = datetime.now() + timedelta(days=expires_days)
        with self.conn:
            cursor = self.conn.execute('SELECT 1 FROM vouchers WHERE code = ?', (code,))
            if cursor.fetchone():
                return False
            self.conn.execute('INSERT INTO vouchers (code, amount, created_by, expires_at) VALUES (?, ?, ?, ?)',
                            (code, amount, created_by, expires_at))
            return True

    def redeem_voucher(self, code, user_id):
        """استبدال كود هدية"""
        with self.conn:
            # التحقق من الفاصل الزمني (15 دقيقة)
            cursor = self.conn.execute('SELECT last_voucher_redemption FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            if row and row['last_voucher_redemption']:
                last_redemption = datetime.strptime(row['last_voucher_redemption'], '%Y-%m-%d %H:%M:%S')
                if (datetime.now() - last_redemption) < timedelta(minutes=15):
                    return {"success": False, "message": "يجب الانتظار 15 دقيقة بين عمليات الاستبدال"}

            # استخدام UPDATE مع WHERE لتجنب مشاكل التزامن
            cursor = self.conn.execute('''
            UPDATE vouchers 
            SET used_by = ?, used_at = ? 
            WHERE code = ? AND used_by IS NULL AND expires_at > ?
            ''', (user_id, datetime.now(), code, datetime.now()))

            if cursor.rowcount == 0:
                cursor = self.conn.execute('SELECT * FROM vouchers WHERE code = ?', (code,))
                voucher = cursor.fetchone()
                if not voucher:
                    return {"success": False, "message": "الكود غير موجود"}
                if voucher['used_by'] is not None:
                    return {"success": False, "message": "الكود مستخدم مسبقاً"}
                if voucher['expires_at'] and datetime.strptime(voucher['expires_at'], '%Y-%m-%d %H:%M:%S') < datetime.now():
                    return {"success": False, "message": "الكود منتهي الصلاحية"}

            cursor = self.conn.execute('SELECT * FROM vouchers WHERE code = ?', (code,))
            voucher = cursor.fetchone()

            # إضافة الرصيد
            self.conn.execute('UPDATE wallets SET balance = balance + ? WHERE user_id = ?', (voucher['amount'], user_id))
            self.conn.execute('UPDATE users SET last_voucher_redemption = ? WHERE id = ?',
                            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id))

            return {"success": True, "amount": voucher['amount']}

    def create_promo_code(self, code, amount, max_uses, created_by=None, expires_days=30):
        expires_at = datetime.now() + timedelta(days=expires_days)
        with self.conn:
            cursor = self.conn.execute('SELECT 1 FROM promo_codes WHERE code = ?', (code,))
            if cursor.fetchone():
                return False
            self.conn.execute('INSERT INTO promo_codes (code, amount, max_uses, created_by, expires_at) VALUES (?, ?, ?, ?, ?)',
                            (code, amount, max_uses, created_by, expires_at))
            return True

    def redeem_promo_code(self, code, user_id):
        """استبدال كود برومو (يمكن لكل مستخدم استخدامه مرة واحدة)"""
        with self.conn:
            cursor = self.conn.execute('SELECT * FROM promo_codes WHERE code = ? AND expires_at > ? AND current_uses < max_uses',
                                     (code, datetime.now()))
            promo = cursor.fetchone()
            if not promo:
                return {"success": False, "message": "الكود غير موجود أو منتهي الصلاحية أو تم استنفاذ استخداماته"}

            # التحقق من أن المستخدم لم يستخدم الكود مسبقاً
            cursor = self.conn.execute('SELECT 1 FROM promo_uses WHERE promo_id = ? AND user_id = ?', (promo['id'], user_id))
            if cursor.fetchone():
                return {"success": False, "message": "لقد استخدمت هذا الكود مسبقاً"}

            # تسجيل الاستخدام
            self.conn.execute('INSERT INTO promo_uses (promo_id, user_id) VALUES (?, ?)', (promo['id'], user_id))
            self.conn.execute('UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = ?', (promo['id'],))

            # إضافة الرصيد
            self.conn.execute('UPDATE wallets SET balance = balance + ? WHERE user_id = ?', (promo['amount'], user_id))

            return {"success": True, "amount": promo['amount']}

    # =============================================
    # دوال الشحن والسحب
    # =============================================
    def add_deposit_request(self, user_id, method, amount, transaction_id, status='pending'):
        with self.conn:
            cursor = self.conn.execute('''
            INSERT INTO deposit_requests (user_id, method, amount, transaction_id, status)
            VALUES (?, ?, ?, ?, ?)
            ''', (user_id, method, amount, transaction_id, status))
            return cursor.lastrowid

    def update_deposit_request(self, deposit_id, status, message_id=None):
        with self.conn:
            if message_id:
                self.conn.execute('UPDATE deposit_requests SET status = ?, message_id = ? WHERE id = ?', (status, message_id, deposit_id))
            else:
                self.conn.execute('UPDATE deposit_requests SET status = ? WHERE id = ?', (status, deposit_id))

    def get_deposit_request(self, deposit_id):
        cursor = self.conn.execute('SELECT * FROM deposit_requests WHERE id = ?', (deposit_id,))
        return cursor.fetchone()

    def add_withdrawal_request(self, user_id, method, amount, commission, total_amount, phone=None, account=None, usdt_address=None, usdt_network=None):
        with self.conn:
            cursor = self.conn.execute('''
            INSERT INTO withdrawals (user_id, method, amount, commission, total_amount, phone, account, usdt_address, usdt_network, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ''', (user_id, method, amount, commission, total_amount, phone, account, usdt_address, usdt_network))
            return cursor.lastrowid

    def record_wayxbet_transaction(self, user_id, amount, player_id, transaction_type):
        """تسجيل معاملة WayXBet"""
        with self.conn:
            if transaction_type == 'deposit':
                self.conn.execute('INSERT INTO wayxbet_deposits (user_id, amount, player_id) VALUES (?, ?, ?)', 
                                (user_id, amount, player_id))
            else:
                self.conn.execute('INSERT INTO wayxbet_withdrawals (user_id, amount, player_id) VALUES (?, ?, ?)', 
                                (user_id, amount, player_id))

    def record_gift(self, sender_id, receiver_id, amount):
        with self.conn:
            self.conn.execute('INSERT INTO gifts (sender_id, receiver_id, amount) VALUES (?, ?, ?)',
                            (sender_id, receiver_id, amount))

    # =============================================
    # دوال Settings
    # =============================================
    def get_seritel_cash_code(self):
        cursor = self.conn.execute('SELECT seritel_cash_code FROM admin_settings LIMIT 1')
        row = cursor.fetchone()
        return row['seritel_cash_code'] if row and row['seritel_cash_code'] else "123456789012"

    def set_seritel_cash_code(self, code):
        with self.conn:
            self.conn.execute('UPDATE admin_settings SET seritel_cash_code = ?', (code,))
            self.conn.commit()

    def get_sham_cash_account(self):
        cursor = self.conn.execute('SELECT sham_cash_account FROM admin_settings LIMIT 1')
        row = cursor.fetchone()
        return row['sham_cash_account'] if row and row['sham_cash_account'] else "1111111111"

    def set_sham_cash_account(self, account):
        with self.conn:
            self.conn.execute('UPDATE admin_settings SET sham_cash_account = ?', (account,))
            self.conn.commit()

    def get_total_commissions(self):
        cursor = self.conn.execute('SELECT COALESCE(SUM(amount), 0) AS total FROM commissions')
        row = cursor.fetchone()
        return row['total'] if row else 0

    def get_total_bonuses(self):
        cursor = self.conn.execute('SELECT COALESCE(SUM(amount), 0) AS total FROM bonuses')
        row = cursor.fetchone()
        return row['total'] if row else 0

    # =============================================
    # دوال التقارير
    # =============================================
    def get_daily_deposits_summary(self):
        """ملخص عمليات الشحن لآخر 24 ساعة"""
        cursor = self.conn.execute('''
        SELECT method, COUNT(*) as count, COALESCE(SUM(amount), 0) as total
        FROM deposit_requests
        WHERE status = 'approved' AND created_at >= datetime('now', '-1 day')
        GROUP BY method
        ''')
        return cursor.fetchall()

    def get_daily_withdrawals_summary(self):
        """ملخص عمليات السحب لآخر 24 ساعة"""
        cursor = self.conn.execute('''
        SELECT method, COUNT(*) as count, COALESCE(SUM(amount), 0) as total
        FROM withdrawals
        WHERE status = 'approved' AND created_at >= datetime('now', '-1 day')
        GROUP BY method
        ''')
        return cursor.fetchall()

    def get_daily_wayxbet_summary(self):
        """ملخص عمليات التعبئة والسحب من الموقع"""
        deposits = self.conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total FROM wayxbet_deposits 
        WHERE created_at >= datetime('now', '-1 day')
        ''').fetchone()
        
        withdrawals = self.conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total FROM wayxbet_withdrawals 
        WHERE created_at >= datetime('now', '-1 day')
        ''').fetchone()
        
        return {
            'deposits': deposits['total'] if deposits else 0,
            'withdrawals': withdrawals['total'] if withdrawals else 0
        }
    

    # =============================================
# ديكورات التحقق
# =============================================
def check_subscription(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            
            # رسائل الصيانة لا تمنع الأدمن
            with DatabaseManager() as db:
                if db.is_admin(user_id):
                    return await func(update, context)
                
                # فحص الحظر
                user_data = db.get_user(user_id)
                if user_data and user_data['is_banned']:
                    if update.message:
                        await update.message.reply_text("⛔️ حسابك محظور من استخدام البوت. الرجاء التواصل مع الدعم.")
                    elif update.callback_query:
                        await update.callback_query.answer("⛔️ حسابك محظور", show_alert=True)
                    return ConversationHandler.END
                
                # فحص الصيانة - تؤثر فقط على زر EagleBet
                maintenance_msg = db.get_maintenance_message()
                if maintenance_msg:
                    # نتحقق إذا كان المستخدم يحاول استخدام وظائف EagleBet
                    if update.message and update.message.text == Config.MAIN_SITE_NAME:
                        await update.message.reply_text(maintenance_msg)
                        return ConversationHandler.END
                    elif update.callback_query and update.callback_query.data == "eaglebet_menu":
                        await update.callback_query.answer(maintenance_msg, show_alert=True)
                        return ConversationHandler.END
                
        except Exception as e:
            logger.error(f"خطأ في التحقق من الاشتراك: {e}")
            if update.message:
                await update.message.reply_text("⚠️ حدث خطأ أثناء التحقق. الرجاء المحاولة مرة أخرى.")
            return ConversationHandler.END

        return await func(update, context)
    return wrapper

# =============================================
# معالجات الأوامر الأساسية
# =============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # استخراج معرف المُحيل من الرابط العميق
    referrer_id = None
    if context.args and len(context.args) > 0:
        try:
            referrer_id = int(context.args[0])
            context.user_data['pending_referrer'] = referrer_id
        except ValueError:
            pass

    with DatabaseManager() as db:
        # الأدمن يذهب مباشرة للوحة التحكم
        if db.is_admin(user.id):
            await show_admin_panel(update, context)
            return
        
        # مستخدم جديد أو عادي
        existing_user = db.get_user(user.id)
        if existing_user:
            # مستخدم موجود - إظهار القائمة الرئيسية مباشرة
            await update.message.reply_text(
                f"👤 مرحباً @{existing_user['bot_username']}\n💰 رصيدك: {existing_user['wallet_balance']} ل.س",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
        
        # مستخدم جديد - طلب الاشتراك
        terms_msg = f"""
🟥 شروط واحكام استخدام البوت:

🟥 أنت المسؤول الوحيد عن أموالك، دورنا يقتصر على الوساطة بينك وبين الموقع، مع ضمان إيداع وسحب أموالك بكفاءة وموثوقية.

🟥 لا يجوز للاعب إيداع وسحب الأرصدة بهدف التبديل بين وسائل الدفع.

🟥 إنشاء أكثر من حساب يؤدي إلى حظر جميع الحسابات وتجميد الأرصدة.

🟥 أي محاولات للغش أو إنشاء حسابات متعددة ستؤدي إلى تجميد حسابك فوراً.

يُعدّ انضمامك للقناة والاستمرار في استخدام البوت بمثابة الموافقة على هذه الشروط.
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ الموافقة والانضمام إلينا", url=f"https://t.me/{Config.CHANNEL_USERNAME.replace('@', '')}")],
            [InlineKeyboardButton("✅ التحقق من الاشتراك", callback_data="check_subscription")]
        ])
        
        await context.bot.send_message(
            chat_id=user.id,
            text=terms_msg,
            reply_markup=keyboard
        )

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = query.from_user.id
        channel_username = Config.CHANNEL_USERNAME
        
        member = await context.bot.get_chat_member(channel_username, user_id)
        
        if member.status in ['member', 'administrator', 'creator']:
            with DatabaseManager() as db:
                existing_user = db.get_user(user_id)
                if not existing_user:
                    referrer_id = context.user_data.get('pending_referrer')
                    db.add_user(user_id, query.from_user.username, referrer_id)
                    if 'pending_referrer' in context.user_data:
                        del context.user_data['pending_referrer']
                
                user_data = db.get_user(user_id)
                
            await query.edit_message_text("✅ اشتراكك مؤكد! يمكنك الآن استخدام جميع خدمات البوت.")
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"👤 مرحباً @{user_data['bot_username']}\n💰 رصيدك: {user_data['wallet_balance']} ل.س\n\nاختر أحد الخيارات من القائمة:",
                reply_markup=get_main_keyboard()
            )
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ الموافقة والانضمام إلينا", url=f"https://t.me/{channel_username.replace('@', '')}")],
                [InlineKeyboardButton("✅ التحقق من الاشتراك", callback_data="check_subscription")]
            ])
            await query.edit_message_text(
                "⚠️ يجب الاشتراك في القناة أولاً",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"خطأ في التحقق من الاشتراك: {e}")
        await query.edit_message_text("⚠️ حدث خطأ. الرجاء المحاولة مرة أخرى.")

@check_subscription
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القائمة الرئيسية"""
    user = update.effective_user
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        balance = user_data['wallet_balance'] if user_data else 0
        username = user_data['bot_username'] if user_data else user.username or str(user.id)
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            f"👤 @{username}\n💰 الرصيد: {balance} ل.س\n\nاختر أحد الخيارات:",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            f"👤 @{username}\n💰 الرصيد: {balance} ل.س\n\nاختر أحد الخيارات:",
            reply_markup=get_main_keyboard()
        )

async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة الأدمن الرئيسية"""
    context.user_data.clear()
    context.user_data['admin_panel'] = True
    
    # إضافة الزرين الجديدين في القائمة
    buttons = [
        ["🔧 عمليات المستخدمين", "💰 التدفقات المالية"],
        ["🎁 الهدايا والعروض", "📢 بث رسالة جماعية"],
        ["🛠 تفعيل/تعطيل الصيانة", "🛠 حالة الصيانة"],
        ["📊 نسبة الإحالات", "📡 إعدادات القنوات"]  # الزرين الجديدين
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    
    if update.callback_query:
        await update.callback_query.message.reply_text(
            "👨‍💻 لوحة تحكم الأدمن - اختر الإجراء المطلوب:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "👨‍💻 لوحة تحكم الأدمن - اختر الإجراء المطلوب:",
            reply_markup=reply_markup
        )
    return AdminConversationState.ADMIN_MAIN

# =============================================
# معالجات إنشاء حساب WayXBet
# =============================================
@check_subscription
async def handle_wayxbet_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if user_data and user_data['wayxbet_username']:
            await update.message.reply_text("⚠️ لديك حساب EagleBet بالفعل!")
            return ConversationHandler.END
        
        await update.message.reply_text(
            "📝 الرجاء إرسال اسم المستخدم المطلوب لـ EagleBet:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء العملية"]], resize_keyboard=True)
        )
        return WayXBetConversationState.GET_WAYXBET_USERNAME

@check_subscription
async def get_wayxbet_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    
    if username == "❌ إلغاء العملية":
        return await cancel_wayxbet_register(update, context)
    
    if not (4 <= len(username) <= 16) or not username.isalnum():
        await update.message.reply_text("❌ اسم المستخدم غير صالح. يجب أن يكون بين 4-16 حرفاً وأرقام فقط.")
        return WayXBetConversationState.GET_WAYXBET_USERNAME
    
    with DatabaseManager() as db:
        if db.conn.execute('SELECT 1 FROM users WHERE wayxbet_username = ?', (username,)).fetchone():
            await update.message.reply_text("❌ اسم المستخدم هذا محجوز بالفعل. الرجاء اختيار اسم آخر.")
            return WayXBetConversationState.GET_WAYXBET_USERNAME
        
        context.user_data['wayxbet_username'] = username
        await update.message.reply_text(
            "🔐 الرجاء إرسال كلمة المرور المطلوبة:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء العملية"]], resize_keyboard=True)
        )
        return WayXBetConversationState.GET_WAYXBET_PASSWORD

@check_subscription
async def get_wayxbet_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    password = update.message.text.strip()
    
    if password == "❌ إلغاء العملية":
        return await cancel_wayxbet_register(update, context)
    
    if len(password) < 5:
        await update.message.reply_text("❌ كلمة المرور يجب أن تكون 5 أحرف على الأقل.")
        return WayXBetConversationState.GET_WAYXBET_PASSWORD
    
    username = context.user_data['wayxbet_username']
    processing_msg = await update.message.reply_text("⏳ جاري إنشاء حسابك في EagleBet...")
    
    phone = generate_random_phone()
    email = generate_random_email()
    
    try:
        async with WayXBetPlayerRegistrar() as registrar:
            player_data = PlayerRegistration(username=username, password=password, phone=phone, email=email)
            result = await registrar.register_player(player_data)
            
            if result['success']:
                player_id = result.get('player_id', 'غير معروف')
                
                with DatabaseManager() as db:
                    if db.update_wayxbet_account(user.id, username, password, player_id):
                        await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
                        
                        success_msg = f"""
✅ تم إنشاء حساب EagleBet بنجاح

يمكنك الاستعلام عن رصيد حسابك على الموقع عن طريق الضغط على زر "معلومات الحساب 💲"
يجب تغيير كلمة مرور حسابك من خلال الموقع لحماية حسابك.

⚽️ معرف اللاعب: {player_id}
"""
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("🌐 الذهاب إلى موقع EagleBet", url="https://www.eaglebet99.com")],
                        ])
                        
                        await update.message.reply_text(success_msg, reply_markup=keyboard)
                        await show_main_menu(update, context)
                    else:
                        await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
                        await update.message.reply_text("❌ فشل في تحديث قاعدة البيانات")
            else:
                await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
                await update.message.reply_text(
                    f"❌ فشل إنشاء الحساب: {result['message']}\n\nالرجاء المحاولة مرة أخرى.",
                    reply_markup=get_main_keyboard()
                )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"خطأ في إنشاء الحساب: {e}")
        await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
        await update.message.reply_text("❌ حدث خطأ غير متوقع. الرجاء المحاولة لاحقاً.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

async def cancel_wayxbet_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ تم إلغاء عملية إنشاء الحساب.", reply_markup=get_main_keyboard())
    return ConversationHandler.END



# =============================================
# معالج نسبة الإحالات
# =============================================
async def admin_commission_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض وتغيير نسبة الإحالات"""
    with DatabaseManager() as db:
        current_rate = db.get_commission_rate_db()
        
    await update.message.reply_text(
        f"📊 **نسبة الإحالات الحالية:** `{current_rate * 100:.1f}%`\n\n"
        f"📌 **العمولة:** يحصل المُحيل على {current_rate * 100:.1f}% من كل عملية شحن يقوم بها المُحال.\n\n"
        f"💰 **مثال:** إذا قام المُحال بشحن 1000 ل.س، يحصل المُحيل على {current_rate * 100:.1f} ل.س.\n\n"
        f"✏️ **لتغيير النسبة:** أرسل النسبة الجديدة (مثال: 5 تعني 5%)",
        reply_markup=ReplyKeyboardMarkup([["🔙 رجوع"]], resize_keyboard=True),
        parse_mode='Markdown'
    )
    return AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE

async def admin_handle_commission_rate_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تغيير نسبة الإحالات"""
    value = update.message.text.strip()
    
    if value == "🔙 رجوع":
        return await show_admin_panel(update, context)
    
    try:
        percent = float(value)
        if percent < 0 or percent > 100:
            await update.message.reply_text("❌ النسبة يجب أن تكون بين 0 و 100")
            return AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE
        
        rate = percent / 100  # تحويل من نسبة مئوية إلى رقم عشري
        
        with DatabaseManager() as db:
            db.set_commission_rate_db(rate)
            # تحديث Config أيضاً
            Config.COMMISSION_RATE = rate
        
        await update.message.reply_text(
            f"✅ **تم تغيير نسبة الإحالات بنجاح**\n\n"
            f"📊 النسبة الجديدة: `{percent:.1f}%`\n"
            f"💰 العمولة: يحصل المُحيل على {percent:.1f}% من كل عملية شحن.",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح (مثال: 5 يعني 5%)")
        return AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE
    
    return await show_admin_panel(update, context)

# =============================================
# معالج إعدادات القنوات
# =============================================
async def admin_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة إعدادات القنوات"""
    with DatabaseManager() as db:
        main_channel = db.get_main_channel()
        notification_channel = db.get_notification_channel()
        reports_channel = db.get_reports_channel()
        errors_channel = db.get_errors_channel()
    
    buttons = [
        [f"📢 قناة البوت: {main_channel[:15]}..."],
        [f"🔔 قناة الإشعارات: {notification_channel[:15]}..."],
        [f"📊 قناة التقارير: {reports_channel[:15]}..."],
        [f"⚠️ قناة الأخطاء: {errors_channel[:15]}..."],
        ["🔙 رجوع"]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text(
        "📡 **إعدادات القنوات**\n\n"
        "اختر القناة التي تريد تغييرها:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return "CHANNELS_MENU"

async def admin_change_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار القناة المراد تغييرها"""
    choice = update.message.text.strip()
    
    if choice == "🔙 رجوع":
        return await show_admin_panel(update, context)
    
    # تحديد أي قناة تم اختيارها
    if "قناة البوت" in choice:
        context.user_data['channel_type'] = 'main'
        await update.message.reply_text(
            f"📢 **تغيير قناة البوت الرئيسية**\n\n"
            f"القناة الحالية: {Config.CHANNEL_USERNAME}\n\n"
            f"✏️ أرسل معرف القناة الجديد (مع @):\n"
            f"مثال: `@my_channel`",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
            parse_mode='Markdown'
        )
    elif "قناة الإشعارات" in choice:
        context.user_data['channel_type'] = 'notification'
        await update.message.reply_text(
            f"🔔 **تغيير قناة الإشعارات**\n\n"
            f"القناة الحالية: {Config.NOTIFICATION_GROUP_USERNAME}\n\n"
            f"✏️ أرسل معرف القناة الجديد (مع @):\n"
            f"مثال: `@notifications_channel`",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
            parse_mode='Markdown'
        )
    elif "قناة التقارير" in choice:
        context.user_data['channel_type'] = 'reports'
        await update.message.reply_text(
            f"📊 **تغيير قناة التقارير**\n\n"
            f"القناة الحالية: {Config.REPORTS_CHANNEL_USERNAME}\n\n"
            f"✏️ أرسل معرف القناة الجديد (مع @):\n"
            f"مثال: `@reports_channel`",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
            parse_mode='Markdown'
        )
    elif "قناة الأخطاء" in choice:
        context.user_data['channel_type'] = 'errors'
        await update.message.reply_text(
            f"⚠️ **تغيير قناة الأخطاء**\n\n"
            f"القناة الحالية: {Config.ERRORS_CHANNEL_USERNAME}\n\n"
            f"✏️ أرسل معرف القناة الجديد (مع @):\n"
            f"مثال: `@errors_channel`",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
            parse_mode='Markdown'
        )
    else:
        return await admin_channels_menu(update, context)
    
    return "CHANGE_CHANNEL"

async def admin_save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حفظ القناة الجديدة"""
    new_channel = update.message.text.strip()
    
    if new_channel == "❌ إلغاء":
        return await admin_channels_menu(update, context)
    
    # التأكد من أن القناة تبدأ بـ @
    if not new_channel.startswith('@'):
        new_channel = '@' + new_channel
    
    channel_type = context.user_data.get('channel_type')
    
    with DatabaseManager() as db:
        if channel_type == 'main':
            db.set_main_channel(new_channel)
            Config.CHANNEL_USERNAME = new_channel
            await update.message.reply_text(f"✅ **تم تغيير قناة البوت الرئيسية إلى:** {new_channel}")
        elif channel_type == 'notification':
            db.set_notification_channel(new_channel)
            Config.NOTIFICATION_GROUP_USERNAME = new_channel
            await update.message.reply_text(f"✅ **تم تغيير قناة الإشعارات إلى:** {new_channel}")
        elif channel_type == 'reports':
            db.set_reports_channel(new_channel)
            Config.REPORTS_CHANNEL_USERNAME = new_channel
            await update.message.reply_text(f"✅ **تم تغيير قناة التقارير إلى:** {new_channel}")
        elif channel_type == 'errors':
            db.set_errors_channel(new_channel)
            Config.ERRORS_CHANNEL_USERNAME = new_channel
            await update.message.reply_text(f"✅ **تم تغيير قناة الأخطاء إلى:** {new_channel}")
    
    return await admin_channels_menu(update, context)

# =============================================
# معالجات الرصيد والإهداء
# =============================================
@check_subscription
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("⚠️ ليس لديك حساب. استخدم /start للبدء.")
            return
        
        buttons = [
            ["🎁 استبدال كود هدية", "🎁 استبدال كود برومو"],
            ["🎁 إهداء رصيد", "🏠 القائمة الرئيسية"]
        ]
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        await update.message.reply_text(
            f"💰 رصيدك الحالي في البوت: {user_data['wallet_balance']:,.2f} ل.س",
            reply_markup=reply_markup
        )

@check_subscription
async def show_account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("⚠️ ليس لديك حساب. استخدم /start للبدء.")
            return
        
        wayxbet_balance = "غير معروف"
        if user_data['wayxbet_player_id']:
            try:
                async with WayXBetPlayerRegistrar() as registrar:
                    balance_result = await registrar.get_player_balance(user_data['wayxbet_player_id'])
                    if balance_result['success']:
                        wayxbet_balance = f"{balance_result['balance']:,.2f} {balance_result['currency']}"
            except Exception as e:
                logger.error(f"خطأ في جلب رصيد WayXBet: {e}")
        
        msg = f"""
🌐 اسم حسابك على الموقع: {user_data['wayxbet_username'] or 'غير معروف'}
🌐 رصيدك على الموقع: {wayxbet_balance}

🤖 اسم حسابك على البوت: @{user_data['bot_username']}
🤖 رصيدك على البوت: {user_data['wallet_balance']:,.2f} ل.س

⚽️ معرف اللاعب: {user_data['wayxbet_player_id'] or 'غير معروف'}
        """
        await update.message.reply_text(msg)

@check_subscription
async def invite_friends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("⚠️ ليس لديك حساب. استخدم /start للبدء.")
            return
        
        referrals_count = db.get_referrals_count(user_data['id'])
        total_commissions = db.get_commissions(user_data['id'])
        
        text = f"""
👥 نظام دعوة الأصدقاء EagleBet

استثمر الفرصة لتحقيق دخل مستمر عبر دعوة أصدقائك!
أكسب عمولة ثابتة {Config.COMMISSION_RATE*100}% عن كل عملية شحن يقوم بها أي لاعب ينضم من خلال رابط الدعوة الخاص بك.

🤖 سيقوم البوت بإعلامك تلقائياً عند انضمام أي شخص عن طريقك.

● عدد الإحالات الحالية: {referrals_count}
● إجمالي أرباحك حتى الآن: {total_commissions:,.2f} ل.س 💰
● رابط الدعوة الخاص بك: https://t.me/{Config.BOT_USERNAME}?start={user.id}
        """
        await update.message.reply_text(text, disable_web_page_preview=True)

@check_subscription
async def show_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    terms_msg = """
🟥 شروط واحكام استخدام البوت:

🟥 أنت المسؤول الوحيد عن أموالك، دورنا يقتصر على الوساطة بينك وبين الموقع.

🟥 لا يجوز للاعب إيداع وسحب الأرصدة بهدف التبديل بين وسائل الدفع.

🟥 إنشاء أكثر من حساب يؤدي إلى حظر جميع الحسابات وتجميد الأرصدة.

🟥 أي محاولات للغش أو إنشاء حسابات متعددة ستؤدي إلى تجميد حسابك فوراً.

يُعدّ انضمامك للقناة والاستمرار في استخدام البوت بمثابة الموافقة على هذه الشروط.
"""
    await update.message.reply_text(terms_msg)

@check_subscription
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"📞 للتواصل مع الدعم الفني، الرجاء مراسلة: @{Config.ADMIN_USERNAME}")

@check_subscription
async def handle_wayxbet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("⚠️ ليس لديك حساب. استخدم /start للبدء.")
            return
        
        if not user_data['wayxbet_username']:
            warning_msg = f"""
⚠️ تحذير مهم:

أي بوت لموقع {Config.MAIN_SITE_NAME} يطلب منك شحن رصيدك أولاً قبل إنشاء حساب لك على الموقع هو حتماً محتال!

تأكد أولاً أن البوت وكيل رسمي وقادر على إنشاء الحسابات، ثم قم بتسجيل الدخول للحساب والتحقق من ذلك.

#استلم_حسابك_وبعدا_اشحنو
"""
            buttons = [["📝 إنشاء حساب"], ["↩️ عودة"]]
            reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
            await update.message.reply_text(warning_msg, reply_markup=reply_markup)
        else:
            buttons = [["⬇️ السحب من حسابي", "⬆️ التعبئة في حسابي"], ["ℹ️ معلومات الحساب", "↩️ عودة"]]
            reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
            await update.message.reply_text("اختر احد الخيارات", reply_markup=reply_markup)

async def force_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم إعادة تعيين البوت بنجاح ✅", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية بنجاح ✅", reply_markup=get_main_keyboard())
    return ConversationHandler.END




                # =============================================
# معالجات الشحن
# =============================================
@check_subscription
async def handle_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        enabled_methods = db.get_enabled_payment_methods('deposit')
        if not enabled_methods:
            await update.message.reply_text("⛔️ جميع طرق الشحن متوقفة حالياً.")
            return ConversationHandler.END
        
        buttons = [
            ["💰 سيريتيل كاش"],
            ["💳 شام كاش (ليرة سورية)", "💵 شام كاش (دولار)"],
            ["🏠 القائمة الرئيسية"]
        ]
        
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        await update.message.reply_text("اختر طريقة الشحن:", reply_markup=reply_markup)
        return DepositConversationState.DEPOSIT_METHOD

@check_subscription
async def handle_seritel_cash_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        if not db.is_payment_method_enabled('سيريتيل كاش', 'deposit'):
            await update.message.reply_text("⛔️ خدمة الشحن عن طريق سيريتيل كاش متوقفة حالياً.")
            return DepositConversationState.DEPOSIT_METHOD
        seritel_code = db.get_seritel_cash_code()
    
    context.user_data['deposit_method'] = 'سيريتيل كاش'
    context.user_data['deposit_step'] = 'waiting_transaction'
    context.user_data['seritel_cash_code'] = seritel_code
    
    caption = f"""💳 **الشحن عن طريق سيريتيل كاش**

📌 **كود التاجر:** `{seritel_code}`

📝 **خطوات الشحن:**
1️⃣ قم بنسخ الكود أعلاه
2️⃣ قم بعملية تحويل المبلغ إلى الكود المذكور عبر تطبيق سيريتيل كاش
3️⃣ بعد الانتهاء، قم بإرسال **رقم العملية** (12 رقم)

✅ سيتم التحقق من العملية تلقائياً وإضافة الرصيد.

⚠️ **ملاحظة:** لا يمكن استخدام رقم العملية أكثر من مرة!

📱 **الرجاء إرسال رقم العملية:**
"""
    await update.message.reply_text(caption, parse_mode='Markdown', 
    reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True))
    return DepositConversationState.SERITEL_CASH_TRANSACTION

@check_subscription
async def handle_seritel_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    
    if user_input == "❌ إلغاء":
        context.user_data.clear()
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    transaction_id = ''.join(filter(str.isdigit, user_input))
    if not transaction_id or len(transaction_id) != 12:
        await update.message.reply_text("❌ رقم العملية غير صالح. يجب أن يتكون من 12 رقم فقط.\nالرجاء المحاولة مرة أخرى:")
        return DepositConversationState.SERITEL_CASH_TRANSACTION
    
    # التحقق من قاعدة البيانات (بخفاء)
    with DatabaseManager() as db:
        cursor = db.conn.execute('''
            SELECT id, status FROM deposit_requests 
            WHERE transaction_id = ? AND method = 'سيريتيل كاش'
        ''', (transaction_id,))
        existing = cursor.fetchone()
        
        if existing:
            await update.message.reply_text(
                "❌ **رقم العملية هذا مستخدم مسبقاً!**\n\n"
                "لا يمكن استخدام نفس رقم العملية لأكثر من عملية شحن.\n\n"
                "الرجاء التأكد من رقم العملية والمحاولة مرة أخرى:",
                parse_mode='Markdown'
            )
            return DepositConversationState.SERITEL_CASH_TRANSACTION
        
        context.user_data['seritel_transaction_id'] = transaction_id
        
        await update.message.reply_text(
            "💰 **الرجاء إدخال المبلغ الذي قمت بتحويله:**\n\n"
            "📝 مثال: 50000\n\n"
            "⚠️ تأكد من إدخال المبلغ الصحيح.",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
            parse_mode='Markdown'
        )
        return DepositConversationState.SERITEL_CASH_AMOUNT
    
@check_subscription
async def handle_seritel_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        context.user_data.clear()
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        user_amount = float(amount_text)
        if user_amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر:\nالرجاء إدخال مبلغ صحيح:")
            return DepositConversationState.SERITEL_CASH_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً:\nالرجاء إدخال مبلغ صحيح:")
        return DepositConversationState.SERITEL_CASH_AMOUNT
    
    context.user_data['seritel_amount'] = user_amount
    
    # طلب الكود
    await update.message.reply_text(
        "🔢 **الرجاء إدخال الكود الذي قمت بالتحويل إليه:**\n\n"
        "📌 هذا هو نفس الكود الذي أرسله البوت لك في بداية العملية.\n\n"
        "⚠️ تأكد من إدخال الكود الصحيح (أرقام فقط):",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
        parse_mode='Markdown'
    )
    # IMPORTANT: ارجع الحالة الصحيحة
    return DepositConversationState.SERITEL_CASH_CODE

@check_subscription
async def handle_seritel_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cash_code = update.message.text.strip()
    
    if cash_code == "❌ إلغاء":
        context.user_data.clear()
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    # تنظيف الكود (أرقام فقط)
    cash_code = ''.join(filter(str.isdigit, cash_code))
    
    transaction_id = context.user_data.get('seritel_transaction_id')
    user_amount = context.user_data.get('seritel_amount')
    
    if not transaction_id or not user_amount:
        await update.message.reply_text("❌ انتهت الجلسة. الرجاء البدء من جديد.")
        return ConversationHandler.END
    
    processing_msg = await update.message.reply_text("⏳ جاري التحقق من العملية...")
    
    api_client = SyriaAPIClient(api_key=Config.API_SYRIA_KEY)
    try:
        result = await api_client.verify_seritel_transaction(cash_code, transaction_id)
    finally:
        await api_client.close()
    
    await context.bot.delete_message(chat_id=update.effective_user.id, message_id=processing_msg.message_id)
    
    if not result.get('success'):
        await update.message.reply_text(
            f"❌ **فشل التحقق من العملية!**\n\n"
            f"السبب: {result.get('error', 'خطأ غير معروف')}\n\n"
            f"الرجاء المحاولة مرة أخرى.",
            parse_mode='Markdown'
        )
        return DepositConversationState.SERITEL_CASH_TRANSACTION
    
    if not result.get('found'):
        await update.message.reply_text(
            "❌ **لم يتم العثور على العملية في نظام سيريتيل!**\n\n"
            "الرجاء التأكد من:\n"
            "• صحة رقم العملية (12 رقم)\n"
            "• صحة الكود الذي تم التحويل إليه\n"
            "• انتظار بضع دقائق بعد التحويل\n\n"
            "🔄 الرجاء المحاولة مرة أخرى:",
            parse_mode='Markdown'
        )
        return DepositConversationState.SERITEL_CASH_TRANSACTION
    
    api_amount = result.get('amount', 0)
    
    if abs(user_amount - api_amount) > 1:
        await update.message.reply_text(
            f"⚠️ **عدم تطابق المبلغ!**\n\n"
            f"💰 المبلغ الذي أدخلته: **{user_amount:,.0f} ل.س**\n"
            f"💰 المبلغ الفعلي في العملية: **{api_amount:,.0f} ل.س**\n\n"
            f"الرجاء المحاولة مرة أخرى.",
            parse_mode='Markdown'
        )
        return DepositConversationState.SERITEL_CASH_TRANSACTION
    
    await process_seritel_deposit(update, context, api_amount, transaction_id, cash_code)
    return ConversationHandler.END


@check_subscription
async def handle_sham_cash_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار العملة لشام كاش"""
    choice = update.message.text.strip()
    
    with DatabaseManager() as db:
        if not db.is_payment_method_enabled('شام كاش', 'deposit'):
            await update.message.reply_text("⛔️ خدمة الشحن عن طريق شام كاش متوقفة حالياً.")
            return DepositConversationState.DEPOSIT_METHOD
        
        if "ليرة" in choice:
            context.user_data['sham_currency'] = 'SYP'
            usd_rate = Config.USD_EXCHANGE_RATE
            await update.message.reply_text(
                f"💳 **الشحن عن طريق شام كاش (ليرة سورية)**\n\n"
                f"📌 **حساب شام كاش:** `{db.get_sham_cash_account()}`\n\n"
                f"📝 **خطوات الشحن:**\n"
                f"1️⃣ قم بتحويل المبلغ إلى الحساب أعلاه (بالليرة السورية)\n"
                f"2️⃣ بعد الانتهاء، أرسل **رقم العملية**\n\n"
                f"✅ سيتم التحقق من العملية تلقائياً وإضافة الرصيد.\n\n"
                f"⚠️ **ملاحظة:** لا يمكن استخدام رقم العملية أكثر من مرة!\n\n"
                f"📱 **الرجاء إرسال رقم العملية:**",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
            )
        elif "دولار" in choice:
            context.user_data['sham_currency'] = 'USD'
            usd_rate = Config.USD_EXCHANGE_RATE
            await update.message.reply_text(
                f"💵 **الشحن عن طريق شام كاش (دولار أمريكي)**\n\n"
                f"📌 **حساب شام كاش:** `{db.get_sham_cash_account()}`\n"
                f"💱 **سعر الصرف:** 1 دولار = {usd_rate:,} ل.س\n\n"
                f"📝 **خطوات الشحن:**\n"
                f"1️⃣ قم بتحويل المبلغ بالدولار إلى الحساب أعلاه\n"
                f"2️⃣ بعد الانتهاء، أرسل **رقم العملية**\n\n"
                f"✅ سيتم التحقق من العملية تلقائياً وإضافة الرصيد.\n\n"
                f"⚠️ **ملاحظة:** لا يمكن استخدام رقم العملية أكثر من مرة!\n\n"
                f"📱 **الرجاء إرسال رقم العملية:**",
                parse_mode='Markdown',
                reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
            )
        else:
            return DepositConversationState.DEPOSIT_METHOD
    
    context.user_data['deposit_method'] = 'شام كاش'
    return DepositConversationState.SHAM_CASH_TRANSACTION

@check_subscription
async def handle_sham_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    
    if user_input == "❌ إلغاء":
        context.user_data.clear()
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    transaction_id = user_input.strip()
    if not transaction_id or len(transaction_id) < 3:
        await update.message.reply_text("❌ رقم العملية غير صالح. الرجاء إدخال رقم صحيح:")
        return DepositConversationState.SHAM_CASH_TRANSACTION
    
    # التحقق من قاعدة البيانات (بخفاء)
    with DatabaseManager() as db:
        cursor = db.conn.execute('''
            SELECT id, status FROM deposit_requests 
            WHERE transaction_id = ? AND method = 'شام كاش'
        ''', (transaction_id,))
        existing = cursor.fetchone()
        
        if existing:
            await update.message.reply_text(
                "❌ **رقم العملية هذا مستخدم مسبقاً!**\n\n"
                "لا يمكن استخدام نفس رقم العملية لأكثر من عملية شحن.\n\n"
                "الرجاء التأكد من رقم العملية والمحاولة مرة أخرى:",
                parse_mode='Markdown'
            )
            return DepositConversationState.SHAM_CASH_TRANSACTION
        
        context.user_data['sham_transaction_id'] = transaction_id
        
        # طلب المبلغ
        currency = context.user_data.get('sham_currency', 'SYP')
        currency_text = "بالدولار" if currency == 'USD' else "بالليرة السورية"
        
        await update.message.reply_text(
            f"💰 **الرجاء إدخال المبلغ الذي قمت بتحويله {currency_text}:**\n\n"
            f"📝 مثال: {'100' if currency == 'USD' else '50000'}\n\n"
            f"⚠️ تأكد من إدخال المبلغ الصحيح لأنه سيتم التحقق منه تلقائياً.",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
            parse_mode='Markdown'
        )
        return DepositConversationState.SHAM_CASH_AMOUNT
    
@check_subscription
async def handle_sham_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        context.user_data.clear()
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        user_amount = float(amount_text)
        if user_amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر.\nالرجاء إدخال مبلغ صحيح:")
            return DepositConversationState.SHAM_CASH_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً.\nالرجاء إدخال مبلغ صحيح:")
        return DepositConversationState.SHAM_CASH_AMOUNT
    
    transaction_id = context.user_data.get('sham_transaction_id')
    currency = context.user_data.get('sham_currency', 'SYP')
    
    if not transaction_id:
        await update.message.reply_text("❌ انتهت الجلسة. الرجاء البدء من جديد.")
        return ConversationHandler.END
    
    # التحقق من API
    processing_msg = await update.message.reply_text("⏳ جاري التحقق من العملية...")
    
    api_client = SyriaAPIClient(api_key=Config.API_SYRIA_KEY)
    try:
        with DatabaseManager() as db:
            account_address = db.get_sham_cash_account()
            result = await api_client.verify_sham_transaction(account_address, transaction_id)
    finally:
        await api_client.close()
    
    await context.bot.delete_message(chat_id=update.effective_user.id, message_id=processing_msg.message_id)
    
    if not result.get('success'):
        await update.message.reply_text(
            f"❌ **فشل التحقق من العملية!**\n\n"
            f"السبب: {result.get('error', 'خطأ غير معروف')}\n\n"
            f"الرجاء المحاولة مرة أخرى.",
            parse_mode='Markdown'
        )
        return DepositConversationState.SHAM_CASH_TRANSACTION
    
    if not result.get('found'):
        await update.message.reply_text(
            "❌ **لم يتم العثور على العملية في نظام شام كاش!**\n\n"
            "الرجاء التأكد من:\n"
            "• صحة رقم العملية\n"
            "• أنك قمت بالتحويل إلى الحساب الصحيح\n"
            "• انتظار بضع دقائق بعد التحويل\n\n"
            "🔄 الرجاء المحاولة مرة أخرى:",
            parse_mode='Markdown'
        )
        return DepositConversationState.SHAM_CASH_TRANSACTION
    
    # العملية موجودة في API
    api_amount = result.get('amount', 0)
    api_currency = result.get('currency', 'SYP')
    
    # التحقق من تطابق العملة
    if api_currency != currency:
        await update.message.reply_text(
            f"❌ **عدم تطابق العملة!**\n\n"
            f"العملة التي اخترتها: {currency}\n"
            f"العملة الفعلية: {api_currency}\n\n"
            f"الرجاء البدء من جديد واختيار العملة الصحيحة.",
            parse_mode='Markdown'
        )
        return DepositConversationState.DEPOSIT_METHOD
    
    # تحويل المبلغ إذا كان دولار
    if currency == 'USD':
        compare_amount = user_amount
        compare_api = api_amount
    else:
        compare_amount = user_amount
        compare_api = api_amount
    
    # التحقق من تطابق المبلغ
    if abs(compare_amount - compare_api) > (0.01 if currency == 'USD' else 1):
        display_user = f"{compare_amount} دولار" if currency == 'USD' else f"{compare_amount:,.0f} ل.س"
        display_api = f"{compare_api} دولار" if currency == 'USD' else f"{compare_api:,.0f} ل.س"
        
        await update.message.reply_text(
            f"⚠️ **عدم تطابق المبلغ!**\n\n"
            f"💰 المبلغ الذي أدخلته: **{display_user}**\n"
            f"💰 المبلغ الفعلي في العملية: **{display_api}**\n\n"
            f"الرجاء المحاولة مرة أخرى والتأكد من إدخال المبلغ الصحيح.",
            parse_mode='Markdown'
        )
        return DepositConversationState.SHAM_CASH_TRANSACTION
    
    # حساب المبلغ النهائي بالليرة السورية
    if currency == 'USD':
        final_amount = user_amount * Config.USD_EXCHANGE_RATE
    else:
        final_amount = user_amount
    
    await process_sham_deposit(update, context, final_amount, transaction_id, currency)
    return ConversationHandler.END

async def process_sham_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE, amount_syp: float, transaction_id: str, currency: str):
    """معالجة قبول عملية إيداع شام كاش"""
    user = update.effective_user
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return
        
        # التحقق مرة أخيرة من عدم استخدام العملية
        cursor = db.conn.execute('''
            SELECT 1 FROM deposit_requests 
            WHERE transaction_id = ? AND method = 'شام كاش'
        ''', (transaction_id,))
        if cursor.fetchone():
            await update.message.reply_text("❌ رقم العملية هذا مستخدم مسبقاً!")
            return
        
        # إضافة طلب الشحن
        deposit_id = db.add_deposit_request(user_data['id'], 'شام كاش', amount_syp, transaction_id)
        
        # البحث عن البونص الجماعي
        bonus_percentage = db.get_deposit_bonus('شام كاش')
        bonus_amount = amount_syp * (bonus_percentage / 100)
        total_amount = amount_syp + bonus_amount
        
        # تحديث رصيد المستخدم
        db.update_wallet_balance(user_data['id'], total_amount)
        db.update_deposit_request(deposit_id, 'approved')
        
        # منح عمولة للمُحيل
        referrer_id = db.get_referrer_for_user(user_data['id'])
        if referrer_id:
            commission = amount_syp * Config.COMMISSION_RATE
            db.update_wallet_balance(referrer_id, commission)
            try:
                referrer = db.get_user_by_id(referrer_id)
                if referrer:
                    await context.bot.send_message(
                        chat_id=referrer['telegram_id'],
                        text=f"💰 تمت إضافة عمولة إحالة بقيمة {commission:,.2f} ل.س إلى رصيدك"
                    )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار العمولة: {e}")
        
        bonus_msg = f"\n🎁 بونص {bonus_percentage}%: +{bonus_amount:,.2f} ل.س" if bonus_percentage > 0 else ""
        
        # إعداد نص العرض حسب العملة
        if currency == 'USD':
            usd_amount = amount_syp / Config.USD_EXCHANGE_RATE
            display_amount = f"{usd_amount:.2f} دولار ({amount_syp:,.0f} ل.س)"
        else:
            display_amount = f"{amount_syp:,.0f} ل.س"
        
        # إشعار للمستخدم
        await update.message.reply_text(
            f"✅ **تم شحن حسابك بنجاح!**\n\n"
            f"💰 المبلغ: {display_amount}{bonus_msg}\n"
            f"💳 وسيلة الشحن: شام كاش\n"
            f"🔢 رقم العملية: {transaction_id}",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard()
        )
        
        # إشعار لمجموعة الإشعارات (بالصيغة المطلوبة)
        if currency == 'USD':
            usd_amount = amount_syp / Config.USD_EXCHANGE_RATE
            notification_text = (
                f"🟢 **المستخدم** @{user_data['bot_username']}\n"
                f"شحن **{usd_amount:.1f} دولار** بقيمة **{amount_syp:,.0f} ل.س**\n"
                f"من شام كاش برقم عملية `{transaction_id}`"
            )
        else:
            notification_text = (
                f"🟢 **المستخدم** @{user_data['bot_username']}\n"
                f"شحن **{amount_syp:,.0f} ليرة** من شام كاش برقم عملية `{transaction_id}`"
            )
        
        try:
            await context.bot.send_message(
                chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                text=notification_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمجموعة: {e}")
@check_subscription
async def handle_usdt_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        if not db.is_payment_method_enabled('USDT', 'deposit'):
            await update.message.reply_text("⛔️ خدمة الشحن عن طريق USDT متوقفة حالياً.")
            return DepositConversationState.DEPOSIT_METHOD
    
    caption = f"""
📌 عناوين USDT الخاصة بالبوت:

BEP20: `{Config.USDT_BEP20_ADDRESS}`
TRC20: `{Config.USDT_TRC20_ADDRESS}`

سعر الصرف: 1 USDT = {Config.USD_EXCHANGE_RATE:,} ل.س

الرجاء إرسال المبلغ الذي قمت بشحنه (بالدولار):
"""
    await update.message.reply_text(caption, reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True), parse_mode='Markdown')
    return DepositConversationState.USDT_AMOUNT




async def process_seritel_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float, transaction_id: str):
    """معالجة قبول عملية إيداع سيريتيل كاش"""
    user = update.effective_user
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return
        
        # التحقق مرة أخيرة من عدم استخدام العملية
        cursor = db.conn.execute('''
            SELECT 1 FROM deposit_requests 
            WHERE transaction_id = ? AND method = 'سيريتيل كاش'
        ''', (transaction_id,))
        if cursor.fetchone():
            await update.message.reply_text("❌ رقم العملية هذا مستخدم مسبقاً!")
            return
        
        # إضافة طلب الشحن
        deposit_id = db.add_deposit_request(user_data['id'], 'سيريتيل كاش', amount, transaction_id)
        
        # البحث عن البونص الجماعي
        bonus_percentage = db.get_deposit_bonus('سيريتيل كاش')
        bonus_amount = amount * (bonus_percentage / 100)
        total_amount = amount + bonus_amount
        
        # تحديث رصيد المستخدم
        db.update_wallet_balance(user_data['id'], total_amount)
        db.update_deposit_request(deposit_id, 'approved')
        
        # منح عمولة للمُحيل
        referrer_id = db.get_referrer_for_user(user_data['id'])
        if referrer_id:
            commission = amount * Config.COMMISSION_RATE
            db.update_wallet_balance(referrer_id, commission)
            try:
                referrer = db.get_user_by_id(referrer_id)
                if referrer:
                    await context.bot.send_message(
                        chat_id=referrer['telegram_id'],
                        text=f"💰 تمت إضافة عمولة إحالة بقيمة {commission:,.2f} ل.س إلى رصيدك"
                    )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار العمولة: {e}")
        
        bonus_msg = f"\n🎁 بونص {bonus_percentage}%: +{bonus_amount:,.2f} ل.س" if bonus_percentage > 0 else ""
        
        # إشعار للمستخدم
        await update.message.reply_text(
            f"✅ **تم شحن حسابك بنجاح!**\n\n"
            f"💰 المبلغ: {amount:,.0f} ل.س{bonus_msg}\n"
            f"💳 وسيلة الشحن: سيريتيل كاش\n"
            f"🔢 رقم العملية: {transaction_id}\n"
            f"📞 إلى الكود: {db.get_seritel_cash_code()}",
            parse_mode='Markdown',
            reply_markup=get_main_keyboard()
        )
        
        # إشعار لمجموعة الإشعارات
        notification_text = (
            f"🟢 **قبلت عملية شحن سيريتيل كاش**\n"
            f"👤 المستخدم: @{user_data['bot_username']}\n"
            f"💰 المبلغ: **{amount:,.0f} ل.س**\n"
            f"🔢 رقم العملية: `{transaction_id}`\n"
            f"📞 إلى الكود: `{db.get_seritel_cash_code()}`"
        )
        
        try:
            await context.bot.send_message(
                chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                text=notification_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمجموعة: {e}")

@check_subscription
async def handle_usdt_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txid = update.message.text.strip()
    
    if txid == "❌ إلغاء":
        return await cancel_operation(update, context)
    
    usdt_amount = context.user_data.get('usdt_amount')
    user = update.effective_user
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return ConversationHandler.END
        
        amount_syp = usdt_amount * Config.USD_EXCHANGE_RATE
        
        deposit_id = db.add_deposit_request(user_data['id'], 'USDT', amount_syp, txid)
        
        await update.message.reply_text(
            "⏳ طلبك قيد المعالجة، يرجى الانتظار...",
            reply_markup=get_main_keyboard()
        )
        
        notification_text = (
            f"💎 طلب شحن USDT جديد\n"
            f"👤 المستخدم: @{user_data['bot_username']}\n"
            f"💳 الطريقة: USDT\n"
            f"💰 المبلغ: {usdt_amount} USDT ({amount_syp:,.0f} ل.س)\n"
            f"🔢 TXID: {txid}\n"
            f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول", callback_data=f"approve_deposit_{deposit_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"reject_deposit_{deposit_id}")]
        ])
        
        try:
            message = await context.bot.send_message(
                chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                text=notification_text,
                reply_markup=keyboard
            )
            db.update_deposit_request(deposit_id, 'pending', message.message_id)
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمجموعة: {e}")
    
    return ConversationHandler.END

async def handle_deposit_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split('_')
    action = parts[0]
    deposit_id = int(parts[-1])
    
    with DatabaseManager() as db:
        # التحقق من صلاحيات المستخدم
        admin_user = db.get_user(query.from_user.id)
        if not admin_user or not db.is_admin(query.from_user.id):
            await query.answer("❌ ليس لديك صلاحية الموافقة على هذه العملية", show_alert=True)
            return
        
        deposit_request = db.get_deposit_request(deposit_id)
        if not deposit_request:
            await query.edit_message_text("❌ لم يتم العثور على طلب الشحن.")
            return
        
        if deposit_request['status'] != 'pending':
            await query.answer("تم معالجة هذا الطلب مسبقاً", show_alert=True)
            return
        
        cursor = db.conn.execute('SELECT * FROM users WHERE id = ?', (deposit_request['user_id'],))
        user = cursor.fetchone()
        
        if action == 'approve':
            # البحث عن البونص الجماعي
            bonus_percentage = db.get_deposit_bonus(deposit_request['method'])
            bonus_amount = deposit_request['amount'] * (bonus_percentage / 100)
            total_amount = deposit_request['amount'] + bonus_amount
            
            # تحديث رصيد المستخدم
            db.update_wallet_balance(user['id'], total_amount)
            db.update_deposit_request(deposit_id, 'approved')
            
            # منح عمولة للمُحيل
            referrer_id = db.get_referrer_for_user(user['id'])
            if referrer_id:
                commission = db.add_commission(referrer_id, deposit_request['amount'], user['id'])
                try:
                    referrer = db.get_user_by_id(referrer_id)
                    if referrer:
                        await context.bot.send_message(
                            chat_id=referrer['telegram_id'],
                            text=f"💰 تمت إضافة عمولة إحالة بقيمة {commission:,.2f} ل.س إلى رصيدك"
                        )
                except Exception as e:
                    logger.error(f"فشل إرسال إشعار العمولة: {e}")
            
            bonus_msg = f"\n🎁 بونص {bonus_percentage}%: +{bonus_amount:,.2f} ل.س" if bonus_percentage > 0 else ""
            
            try:
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=f"✅ تم شحن حسابك بنجاح\n💰 المبلغ: {deposit_request['amount']:,.0f} ل.س{bonus_msg}\n💳 وسيلة الشحن: {deposit_request['method']}\n🔢 رقم العملية: {deposit_request['transaction_id']}"
                )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار للمستخدم: {e}")
            
            approval_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_text = (
                f"✅ وافق حساب الدعم عالطلب\n"
                f"👤 المستخدم: @{user['bot_username']}\n"
                f"💰 المبلغ: {deposit_request['amount']:,.0f} ل.س{bonus_msg}\n"
                f"🔢 رقم العملية: {deposit_request['transaction_id']}\n"
                f"⏰ تمت الموافقة: {approval_time}"
            )
            await query.edit_message_text(text=new_text, reply_markup=None)
            
        elif action == 'reject':
            db.update_deposit_request(deposit_id, 'rejected')
            
            try:
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=f"❌ تم رفض عملية الشحن\n💰 المبلغ: {deposit_request['amount']:,.0f} ل.س\n💳 وسيلة الشحن: {deposit_request['method']}\n🔢 رقم العملية: {deposit_request['transaction_id']}\n\n📝 رد الدعم:\nهذه العملية غير موجودة، قم بالتأكد جيداً من صحة المعلومات المدخلة."
                )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار للمستخدم: {e}")
            
            rejection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_text = (
                f"❌ رفض حساب الدعم الطلب\n"
                f"👤 المستخدم: @{user['bot_username']}\n"
                f"💰 المبلغ: {deposit_request['amount']:,.0f} ل.س\n"
                f"🔢 رقم العملية: {deposit_request['transaction_id']}\n"
                f"⏰ تم الرفض: {rejection_time}"
            )
            await query.edit_message_text(text=new_text, reply_markup=None)

@check_subscription
async def handle_usdt_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال مبلغ USDT من قبل المستخدم"""
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        return await cancel_operation(update, context)
    
    try:
        usdt_amount = float(amount_text)
        if usdt_amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر.")
            return DepositConversationState.USDT_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً.")
        return DepositConversationState.USDT_AMOUNT
    
    context.user_data['usdt_amount'] = usdt_amount
    
    # حساب المبلغ بالليرة السورية
    syp_amount = usdt_amount * Config.USD_EXCHANGE_RATE
    
    await update.message.reply_text(
        f"💰 **ملخص عملية الشحن USDT:**\n\n"
        f"💵 المبلغ: **{usdt_amount} USDT**\n"
        f"💱 سعر الصرف: 1 USDT = {Config.USD_EXCHANGE_RATE:,} ل.س\n"
        f"🇸🇾 يعادل: **{syp_amount:,.0f} ل.س**\n\n"
        f"🔢 الرجاء إرسال TXID (معرف المعاملة) الخاص بعملية الشحن:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True),
        parse_mode='Markdown'
    )
    return DepositConversationState.USDT_TRANSACTION


# =============================================
# معالجات السحب - الدالة الرئيسية
# =============================================
@check_subscription
async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض طرق السحب المتاحة"""
    with DatabaseManager() as db:
        enabled_methods = db.get_enabled_payment_methods('withdraw')
        if not enabled_methods:
            await update.message.reply_text("⛔️ جميع طرق السحب متوقفة حالياً.")
            return ConversationHandler.END
        
        buttons = [
            ["سيريتيل كاش", "شام كاش"],
            ["USDT", "🏠 القائمة الرئيسية"]
        ]
        
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        await update.message.reply_text("اختر طريقة السحب:", reply_markup=reply_markup)
        return WithdrawConversationState.WITHDRAW_METHOD
    

    # =============================================
# معالجات السحب - سيريتيل كاش
# =============================================
@check_subscription
async def handle_seritel_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        if not db.is_payment_method_enabled('سيريتيل كاش', 'withdraw'):
            await update.message.reply_text("⛔️ خدمة السحب عن طريق سيريتيل كاش متوقفة حالياً.")
            return WithdrawConversationState.WITHDRAW_METHOD
        
        commission = db.get_method_commission('سيريتيل كاش', 'withdraw')
    
    await update.message.reply_text(
        f"📱 السحب عن طريق سيرتيل كاش\n"
        f"● العمولة: {commission}%\n"
        f"● الحد الادنى: {Config.SERITEL_MIN_WITHDRAW:,} ل.س\n\n"
        f"📱 الرجاء إرسال رقم الهاتف المراد التحويل إليه:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WithdrawConversationState.WITHDRAW_SERITEL_PHONE


@check_subscription
async def handle_seritel_withdraw_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    
    if phone == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    if not phone.isdigit() or len(phone) < 10:
        await update.message.reply_text("❌ رقم الهاتف غير صالح. يجب أن يكون 10 أرقام على الأقل.")
        return WithdrawConversationState.WITHDRAW_SERITEL_PHONE
    
    context.user_data['withdraw_phone'] = phone
    
    with DatabaseManager() as db:
        commission = db.get_method_commission('سيريتيل كاش', 'withdraw')
    
    await update.message.reply_text(
        f"💰 الرجاء إدخال المبلغ المراد سحبه (الحد الأدنى: {Config.SERITEL_MIN_WITHDRAW:,} ل.س):\n"
        f"علماً أنه سيتم خصم عمولة {commission}% من المبلغ",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WithdrawConversationState.WITHDRAW_SERITEL_AMOUNT


@check_subscription
async def handle_seritel_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        withdraw_amount = float(amount_text)
        if withdraw_amount < Config.SERITEL_MIN_WITHDRAW:
            await update.message.reply_text(f"❌ الحد الأدنى للسحب هو {Config.SERITEL_MIN_WITHDRAW:,} ل.س")
            return WithdrawConversationState.WITHDRAW_SERITEL_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً")
        return WithdrawConversationState.WITHDRAW_SERITEL_AMOUNT
    
    user = update.effective_user
    phone = context.user_data['withdraw_phone']
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        commission_pct = db.get_method_commission('سيريتيل كاش', 'withdraw')
        commission = withdraw_amount * (commission_pct / 100)
        total_deduct = withdraw_amount
        receive_amount = withdraw_amount - commission
        
        if user_data['wallet_balance'] < total_deduct:
            await update.message.reply_text(
                f"❌ رصيدك غير كافي.\n"
                f"المبلغ المطلوب (مع العمولة): {total_deduct:,.2f} ل.س\n"
                f"رصيدك الحالي: {user_data['wallet_balance']:,.2f} ل.س"
            )
            return await show_main_menu(update, context)
        
        context.user_data['withdraw_amount'] = withdraw_amount
        context.user_data['withdraw_commission'] = commission
        context.user_data['withdraw_total'] = total_deduct
        context.user_data['withdraw_receive'] = receive_amount
        
        buttons = [["✅ تأكيد", "❌ إلغاء"]]
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        
        await update.message.reply_text(
            f"💸 تأكيد عملية السحب:\n\n"
            f"📱 الطريقة: سيريتيل كاش\n"
            f"📞 رقم الهاتف: {phone}\n"
            f"💰 المبلغ المطلوب: {withdraw_amount:,.2f} ل.س\n"
            f"📊 العمولة ({commission_pct}%): {commission:,.2f} ل.س\n"
            f"💵 المبلغ المستلم: {receive_amount:,.2f} ل.س\n\n"
            f"سيقوم البوت بإرسال المبلغ خلال 24 ساعة.\n"
            f"تأكيد عملية السحب؟",
            reply_markup=reply_markup
        )
        return WithdrawConversationState.WITHDRAW_SERITEL_CONFIRM


@check_subscription
async def handle_seritel_withdraw_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    user = update.effective_user
    
    if choice != "✅ تأكيد":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        amount = context.user_data['withdraw_amount']
        commission = context.user_data['withdraw_commission']
        total = context.user_data['withdraw_total']
        receive = context.user_data['withdraw_receive']
        phone = context.user_data['withdraw_phone']
        
        # خصم المبلغ + العمولة من الرصيد
        db.update_wallet_balance(user_data['id'], -total)
        
        # تسجيل طلب السحب
        withdraw_id = db.add_withdrawal_request(
            user_data['id'], 'سيريتيل كاش', amount, commission, total, phone=phone
        )
        
        await update.message.reply_text(
            "✅ تم إرسال طلب السحب إلى الدعم. سيتم إعلامك فور إتمام العملية.",
            reply_markup=get_main_keyboard()
        )
        
        notification_text = (
            f"🟡 طلب سحب جديد\n"
            f"👤 المستخدم: @{user_data['bot_username']}\n"
            f"📱 الطريقة: سيريتيل كاش\n"
            f"📞 رقم الهاتف: {phone}\n"
            f"💰 المبلغ: {amount:,.2f} ل.س\n"
            f"📊 العمولة: {commission:,.2f} ل.س\n"
            f"💵 المستلم: {receive:,.2f} ل.س\n"
            f"⏰ الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول", callback_data=f"approve_withdraw_{withdraw_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"reject_withdraw_{withdraw_id}")]
        ])
        
        try:
            message = await context.bot.send_message(
                chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                text=notification_text,
                reply_markup=keyboard
            )
            db.conn.execute('UPDATE withdrawals SET message_id = ? WHERE id = ?', (message.message_id, withdraw_id))
            db.conn.commit()
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمجموعة: {e}")
    
    return ConversationHandler.END


# =============================================
# معالجات السحب - شام كاش
# =============================================
@check_subscription
async def handle_sham_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        if not db.is_payment_method_enabled('شام كاش', 'withdraw'):
            await update.message.reply_text("⛔️ خدمة السحب عن طريق شام كاش متوقفة حالياً.")
            return WithdrawConversationState.WITHDRAW_METHOD
        commission = db.get_method_commission('شام كاش', 'withdraw')
    
    await update.message.reply_text(
        f"🏦 السحب عن طريق شام كاش\n"
        f"● العمولة: {commission}%\n"
        f"● الحد الادنى: {Config.SHAM_MIN_WITHDRAW:,} ل.س\n\n"
        f"📱 الرجاء إرسال رقم حساب شام كاش:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WithdrawConversationState.WITHDRAW_SHAM_ACCOUNT


@check_subscription
async def handle_sham_withdraw_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account = update.message.text.strip()
    
    if account == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    if not account.isdigit():
        await update.message.reply_text("❌ رقم الحساب غير صالح.")
        return WithdrawConversationState.WITHDRAW_SHAM_ACCOUNT
    
    context.user_data['withdraw_account'] = account
    
    with DatabaseManager() as db:
        commission = db.get_method_commission('شام كاش', 'withdraw')
    
    await update.message.reply_text(
        f"💰 الرجاء إدخال المبلغ المراد سحبه (الحد الأدنى: {Config.SHAM_MIN_WITHDRAW:,} ل.س):\n"
        f"علماً أنه سيتم خصم عمولة {commission}% من المبلغ",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WithdrawConversationState.WITHDRAW_SHAM_AMOUNT


@check_subscription
async def handle_sham_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        withdraw_amount = float(amount_text)
        if withdraw_amount < Config.SHAM_MIN_WITHDRAW:
            await update.message.reply_text(f"❌ الحد الأدنى للسحب هو {Config.SHAM_MIN_WITHDRAW:,} ل.س")
            return WithdrawConversationState.WITHDRAW_SHAM_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً")
        return WithdrawConversationState.WITHDRAW_SHAM_AMOUNT
    
    user = update.effective_user
    account = context.user_data['withdraw_account']
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        commission_pct = db.get_method_commission('شام كاش', 'withdraw')
        commission = withdraw_amount * (commission_pct / 100)
        total_deduct = withdraw_amount
        receive_amount = withdraw_amount - commission
        
        if user_data['wallet_balance'] < total_deduct:
            await update.message.reply_text(
                f"❌ رصيدك غير كافي.\n"
                f"المبلغ المطلوب: {total_deduct:,.2f} ل.س\n"
                f"رصيدك الحالي: {user_data['wallet_balance']:,.2f} ل.س"
            )
            return await show_main_menu(update, context)
        
        context.user_data['withdraw_amount'] = withdraw_amount
        context.user_data['withdraw_commission'] = commission
        context.user_data['withdraw_total'] = total_deduct
        context.user_data['withdraw_receive'] = receive_amount
        
        buttons = [["✅ تأكيد", "❌ إلغاء"]]
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        
        await update.message.reply_text(
            f"💸 تأكيد عملية السحب:\n\n"
            f"🏦 الطريقة: شام كاش\n"
            f"📞 رقم الحساب: {account}\n"
            f"💰 المبلغ المطلوب: {withdraw_amount:,.2f} ل.س\n"
            f"📊 العمولة ({commission_pct}%): {commission:,.2f} ل.س\n"
            f"💵 المبلغ المستلم: {receive_amount:,.2f} ل.س\n\n"
            f"تأكيد عملية السحب؟",
            reply_markup=reply_markup
        )
        return WithdrawConversationState.WITHDRAW_SHAM_CONFIRM


@check_subscription
async def handle_sham_withdraw_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    user = update.effective_user
    
    if choice != "✅ تأكيد":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        amount = context.user_data['withdraw_amount']
        commission = context.user_data['withdraw_commission']
        total = context.user_data['withdraw_total']
        receive = context.user_data['withdraw_receive']
        account = context.user_data['withdraw_account']
        
        db.update_wallet_balance(user_data['id'], -total)
        
        withdraw_id = db.add_withdrawal_request(
            user_data['id'], 'شام كاش', amount, commission, total, account=account
        )
        
        await update.message.reply_text(
            "✅ تم إرسال طلب السحب إلى الدعم. سيتم إعلامك فور إتمام العملية.",
            reply_markup=get_main_keyboard()
        )
        
        notification_text = (
            f"🟡 طلب سحب جديد\n"
            f"👤 المستخدم: @{user_data['bot_username']}\n"
            f"🏦 الطريقة: شام كاش\n"
            f"📞 الحساب: {account}\n"
            f"💰 المبلغ: {amount:,.2f} ل.س\n"
            f"📊 العمولة: {commission:,.2f} ل.س\n"
            f"💵 المستلم: {receive:,.2f} ل.س"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول", callback_data=f"approve_withdraw_{withdraw_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"reject_withdraw_{withdraw_id}")]
        ])
        
        try:
            message = await context.bot.send_message(
                chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                text=notification_text,
                reply_markup=keyboard
            )
            db.conn.execute('UPDATE withdrawals SET message_id = ? WHERE id = ?', (message.message_id, withdraw_id))
            db.conn.commit()
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمجموعة: {e}")
    
    return ConversationHandler.END


# =============================================
# معالجات السحب - USDT
# =============================================
@check_subscription
async def handle_usdt_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        if not db.is_payment_method_enabled('USDT', 'withdraw'):
            await update.message.reply_text("⛔️ خدمة السحب عن طريق USDT متوقفة حالياً.")
            return WithdrawConversationState.WITHDRAW_METHOD
        commission = db.get_method_commission('USDT', 'withdraw')
    
    await update.message.reply_text(
        f"💎 السحب عن طريق USDT\n"
        f"● العمولة: {commission}%\n"
        f"● الحد الادنى: {Config.USDT_MIN_WITHDRAW} USDT\n"
        f"● سعر الصرف: 1 USDT = {Config.USD_EXCHANGE_RATE:,} ل.س\n\n"
        f"📝 الرجاء إرسال عنوان USDT الخاص بك:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WithdrawConversationState.WITHDRAW_USDT_ADDRESS


@check_subscription
async def handle_usdt_withdraw_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    
    if address == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    if len(address) < 10:
        await update.message.reply_text("❌ عنوان USDT غير صالح.")
        return WithdrawConversationState.WITHDRAW_USDT_ADDRESS
    
    context.user_data['withdraw_address'] = address
    
    buttons = [["BEP20", "TRC20"], ["❌ إلغاء"]]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("🌐 اختر شبكة USDT:", reply_markup=reply_markup)
    return WithdrawConversationState.WITHDRAW_USDT_NETWORK


@check_subscription
async def handle_usdt_withdraw_network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    network = update.message.text.strip().upper()
    
    if network == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    if network not in ["BEP20", "TRC20"]:
        await update.message.reply_text("❌ شبكة غير صالحة. اختر BEP20 أو TRC20.")
        return WithdrawConversationState.WITHDRAW_USDT_NETWORK
    
    context.user_data['withdraw_network'] = network
    
    with DatabaseManager() as db:
        commission = db.get_method_commission('USDT', 'withdraw')
    
    await update.message.reply_text(
        f"💰 الرجاء إدخال المبلغ المراد سحبه (بالدولار USDT):\n"
        f"الحد الأدنى: {Config.USDT_MIN_WITHDRAW} USDT\n"
        f"سيتم خصم عمولة {commission}%",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WithdrawConversationState.WITHDRAW_USDT_AMOUNT


@check_subscription
async def handle_usdt_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        usdt_amount = float(amount_text)
        if usdt_amount < Config.USDT_MIN_WITHDRAW:
            await update.message.reply_text(f"❌ الحد الأدنى للسحب هو {Config.USDT_MIN_WITHDRAW} USDT")
            return WithdrawConversationState.WITHDRAW_USDT_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً")
        return WithdrawConversationState.WITHDRAW_USDT_AMOUNT
    
    user = update.effective_user
    address = context.user_data['withdraw_address']
    network = context.user_data['withdraw_network']
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        commission_pct = db.get_method_commission('USDT', 'withdraw')
        sy_amount = usdt_amount * Config.USD_EXCHANGE_RATE
        commission = sy_amount * (commission_pct / 100)
        total_deduct = sy_amount
        receive_usdt = usdt_amount * (1 - commission_pct / 100)
        
        if user_data['wallet_balance'] < total_deduct:
            await update.message.reply_text(
                f"❌ رصيدك غير كافي.\n"
                f"المبلغ المطلوب: {total_deduct:,.2f} ل.س\n"
                f"رصيدك الحالي: {user_data['wallet_balance']:,.2f} ل.س"
            )
            return await show_main_menu(update, context)
        
        context.user_data['withdraw_amount'] = usdt_amount
        context.user_data['withdraw_commission'] = commission
        context.user_data['withdraw_total'] = total_deduct
        context.user_data['withdraw_receive'] = receive_usdt
        
        buttons = [["✅ تأكيد", "❌ إلغاء"]]
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        
        await update.message.reply_text(
            f"💸 تأكيد عملية السحب:\n\n"
            f"💎 الطريقة: USDT ({network})\n"
            f"📝 العنوان: {address}\n"
            f"💰 المبلغ المطلوب: {usdt_amount} USDT ({sy_amount:,.2f} ل.س)\n"
            f"📊 العمولة ({commission_pct}%): {commission:,.2f} ل.س\n"
            f"💵 المبلغ المستلم: {receive_usdt:.4f} USDT\n\n"
            f"تأكيد عملية السحب؟",
            reply_markup=reply_markup
        )
        return WithdrawConversationState.WITHDRAW_USDT_CONFIRM


@check_subscription
async def handle_usdt_withdraw_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    user = update.effective_user
    
    if choice != "✅ تأكيد":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        usdt_amount = context.user_data['withdraw_amount']
        commission = context.user_data['withdraw_commission']
        total = context.user_data['withdraw_total']
        receive = context.user_data['withdraw_receive']
        address = context.user_data['withdraw_address']
        network = context.user_data['withdraw_network']
        
        db.update_wallet_balance(user_data['id'], -total)
        
        withdraw_id = db.add_withdrawal_request(
            user_data['id'], 'USDT', usdt_amount, commission, total,
            usdt_address=address, usdt_network=network
        )
        
        await update.message.reply_text(
            "✅ تم إرسال طلب السحب إلى الدعم. سيتم إعلامك فور إتمام العملية.",
            reply_markup=get_main_keyboard()
        )
        
        notification_text = (
            f"💎 طلب سحب USDT جديد\n"
            f"👤 المستخدم: @{user_data['bot_username']}\n"
            f"💎 الطريقة: USDT ({network})\n"
            f"📝 العنوان: {address}\n"
            f"💰 المبلغ: {usdt_amount} USDT\n"
            f"📊 العمولة: {commission:,.2f} ل.س\n"
            f"💵 المستلم: {receive:.4f} USDT"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول", callback_data=f"approve_withdraw_{withdraw_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"reject_withdraw_{withdraw_id}")]
        ])
        
        try:
            message = await context.bot.send_message(
                chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                text=notification_text,
                reply_markup=keyboard
            )
            db.conn.execute('UPDATE withdrawals SET message_id = ? WHERE id = ?', (message.message_id, withdraw_id))
            db.conn.commit()
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمجموعة: {e}")
    
    return ConversationHandler.END
    



            # =============================================
# معالجات WayXBet (تعبئة وسحب)
# =============================================
@check_subscription
async def handle_wayxbet_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 أدخل المبلغ المطلوب شحنه في حسابك EagleBet:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WayXBetTransferConversationState.WAYXBET_DEPOSIT_AMOUNT

@check_subscription
async def handle_wayxbet_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        amount = float(amount_text)
        if amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر.")
            return WayXBetTransferConversationState.WAYXBET_DEPOSIT_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً.")
        return WayXBetTransferConversationState.WAYXBET_DEPOSIT_AMOUNT
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        if user_data['wallet_balance'] < amount:
            await update.message.reply_text(
                f"❌ رصيدك في البوت غير كافي.\nرصيدك: {user_data['wallet_balance']:,.2f} ل.س"
            )
            return WayXBetTransferConversationState.WAYXBET_DEPOSIT_AMOUNT
        
        player_id = user_data['wayxbet_player_id']
        if not player_id:
            await update.message.reply_text("❌ ليس لديك حساب EagleBet. قم بإنشاء حساب أولاً.")
            return await show_main_menu(update, context)
        
        processing_msg = await update.message.reply_text("⏳ جاري معالجة طلبك...")
        
        try:
            async with WayXBetPlayerRegistrar() as registrar:
                result = await registrar.deposit_to_player(player_id, amount)
                
                if result['success']:
                    db.update_wallet_balance(user_data['id'], -amount)
                    db.record_wayxbet_transaction(user_data['id'], amount, player_id, 'deposit')
                    
                    await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
                    
                    new_balance = user_data['wallet_balance'] - amount
                    await update.message.reply_text(
                        f"✅ تم شحن {amount:,.2f} ل.س إلى حسابك EagleBet بنجاح.\n"
                        f"💰 رصيدك الجديد في البوت: {new_balance:,.2f} ل.س"
                    )
                    
                    # إشعار للمجموعة
                    try:
                        await context.bot.send_message(
                            chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                            text=f"◽️ قام @{user_data['bot_username']} بالتعبئة في حسابه EagleBet بمبلغ {amount:,.2f} ل.س"
                        )
                    except:
                        pass
                else:
                    await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
                    await update.message.reply_text(f"❌ فشل في الشحن: {result['message']}")
                    
                    # إشعار خطأ للقناة المخصصة
                    try:
                        await context.bot.send_message(
                            chat_id=Config.ERRORS_CHANNEL_USERNAME,
                            text=f"❌ خطأ تعبئة EagleBet\n👤 @{user_data['bot_username']}\n💰 {amount:,.2f} ل.س\n📝 {result['message']}"
                        )
                    except:
                        pass
        except Exception as e:
            logger.error(f"خطأ في عملية الشحن: {e}")
            await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
            await update.message.reply_text("❌ حدث خطأ أثناء عملية الشحن.")
            
            try:
                await context.bot.send_message(
                    chat_id=Config.ERRORS_CHANNEL_USERNAME,
                    text=f"❌ خطأ تقني تعبئة EagleBet\n👤 @{user_data['bot_username']}\n💰 {amount:,.2f} ل.س\n📝 {str(e)}"
                )
            except:
                pass
    
    await show_main_menu(update, context)
    return ConversationHandler.END

@check_subscription
async def handle_wayxbet_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 أدخل المبلغ المطلوب سحبه من حسابك EagleBet:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return WayXBetTransferConversationState.WAYXBET_WITHDRAW_AMOUNT

@check_subscription
async def handle_wayxbet_withdraw_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        amount = float(amount_text)
        if amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر.")
            return WayXBetTransferConversationState.WAYXBET_WITHDRAW_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً.")
        return WayXBetTransferConversationState.WAYXBET_WITHDRAW_AMOUNT
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if not user_data:
            await update.message.reply_text("❌ لم يتم العثور على حسابك.")
            return await show_main_menu(update, context)
        
        player_id = user_data['wayxbet_player_id']
        if not player_id:
            await update.message.reply_text("❌ ليس لديك حساب EagleBet.")
            return await show_main_menu(update, context)
        
        processing_msg = await update.message.reply_text("⏳ جاري معالجة طلبك...")
        
        try:
            async with WayXBetPlayerRegistrar() as registrar:
                result = await registrar.withdraw_from_player(player_id, amount)
                
                if result['success']:
                    db.update_wallet_balance(user_data['id'], amount)
                    db.record_wayxbet_transaction(user_data['id'], amount, player_id, 'withdraw')
                    
                    await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
                    
                    new_balance = user_data['wallet_balance'] + amount
                    await update.message.reply_text(
                        f"✅ تم سحب {amount:,.2f} ل.س من حسابك EagleBet بنجاح.\n"
                        f"💰 رصيدك الجديد في البوت: {new_balance:,.2f} ل.س"
                    )
                    
                    try:
                        await context.bot.send_message(
                            chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                            text=f"◼️ قام @{user_data['bot_username']} بسحب من حسابه EagleBet بمبلغ {amount:,.2f} ل.س"
                        )
                    except:
                        pass
                else:
                    await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
                    await update.message.reply_text(f"❌ فشل في السحب: {result['message']}")
                    
                    try:
                        await context.bot.send_message(
                            chat_id=Config.ERRORS_CHANNEL_USERNAME,
                            text=f"❌ خطأ سحب EagleBet\n👤 @{user_data['bot_username']}\n💰 {amount:,.2f} ل.س\n📝 {result['message']}"
                        )
                    except:
                        pass
        except Exception as e:
            logger.error(f"خطأ في عملية السحب: {e}")
            await context.bot.delete_message(chat_id=user.id, message_id=processing_msg.message_id)
            await update.message.reply_text("❌ حدث خطأ أثناء عملية السحب.")
            
            try:
                await context.bot.send_message(
                    chat_id=Config.ERRORS_CHANNEL_USERNAME,
                    text=f"❌ خطأ تقني سحب EagleBet\n👤 @{user_data['bot_username']}\n💰 {amount:,.2f} ل.س\n📝 {str(e)}"
                )
            except:
                pass
    
    await show_main_menu(update, context)
    return ConversationHandler.END

# =============================================
# معالجات الأكواد والهدايا
# =============================================
@check_subscription
async def handle_voucher_redemption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎁 الرجاء إدخال كود الهدية:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return VoucherConversationState.ENTER_VOUCHER_CODE

@check_subscription
async def process_voucher_redemption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    voucher_code = update.message.text.strip().upper()
    
    if voucher_code == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        result = db.redeem_voucher(voucher_code, user_data['id'] if user_data else user.id)
        
        if result['success']:
            await update.message.reply_text(
                f"✅ تم استبدال الكود بنجاح! تم إضافة {result['amount']:,.2f} ل.س إلى رصيدك",
                reply_markup=get_main_keyboard()
            )
            try:
                await context.bot.send_message(
                    chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                    text=f"🎁 قام @{user_data['bot_username'] if user_data else user.username} باستبدال كود هدية: {voucher_code}\n💰 المبلغ: {result['amount']:,.2f} ل.س"
                )
            except:
                pass
        else:
            await update.message.reply_text(f"❌ {result['message']}", reply_markup=get_main_keyboard())
    
    return ConversationHandler.END

@check_subscription
async def handle_promo_redemption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎫 الرجاء إدخال كود البرومو:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return VoucherConversationState.ENTER_VOUCHER_CODE

@check_subscription
async def process_promo_redemption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    promo_code = update.message.text.strip().upper()
    
    if promo_code == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        result = db.redeem_promo_code(promo_code, user_data['id'] if user_data else user.id)
        
        if result['success']:
            await update.message.reply_text(
                f"✅ تم استبدال كود البرومو بنجاح! تم إضافة {result['amount']:,.2f} ل.س إلى رصيدك",
                reply_markup=get_main_keyboard()
            )
            try:
                await context.bot.send_message(
                    chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                    text=f"🎫 قام @{user_data['bot_username'] if user_data else user.username} باستبدال كود برومو: {promo_code}\n💰 المبلغ: {result['amount']:,.2f} ل.س"
                )
            except:
                pass
        else:
            await update.message.reply_text(f"❌ {result['message']}", reply_markup=get_main_keyboard())
    
    return ConversationHandler.END

# =============================================
# معالج الإهداء
# =============================================
@check_subscription
async def handle_gift_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 الرجاء إدخال اسم المستخدم الذي تريد إهداءه الرصيد:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return GiftBalanceConversationState.ENTER_RECEIVER

@check_subscription
async def process_gift_receiver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    receiver_username = update.message.text.strip()
    
    if receiver_username == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    with DatabaseManager() as db:
        receiver = db.get_user_by_username(receiver_username)
        if not receiver:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم. الرجاء التأكد من اسم المستخدم")
            return GiftBalanceConversationState.ENTER_RECEIVER
        
        sender = db.get_user(update.effective_user.id)
        if receiver['id'] == sender['id']:
            await update.message.reply_text("❌ لا يمكنك إهداء الرصيد لنفسك")
            return GiftBalanceConversationState.ENTER_RECEIVER
        
        context.user_data['gift_receiver'] = {'id': receiver['id'], 'username': receiver['bot_username']}
        await update.message.reply_text(
            "💰 الرجاء إدخال المبلغ المراد إهداؤه:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return GiftBalanceConversationState.ENTER_AMOUNT

@check_subscription
async def process_gift_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    
    if amount_text == "❌ إلغاء":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    try:
        amount = float(amount_text)
        if amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر")
            return GiftBalanceConversationState.ENTER_AMOUNT
        
        user = update.effective_user
        with DatabaseManager() as db:
            user_data = db.get_user(user.id)
            if user_data['wallet_balance'] < amount:
                await update.message.reply_text(
                    f"❌ رصيدك غير كافي. رصيدك: {user_data['wallet_balance']:,.2f} ل.س"
                )
                return GiftBalanceConversationState.ENTER_AMOUNT
            
            context.user_data['gift_amount'] = amount
            
            buttons = [["✅ تأكيد", "❌ إلغاء"]]
            reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
            receiver_username = context.user_data['gift_receiver']['username']
            
            await update.message.reply_text(
                f"⚠️ تأكيد الإهداء:\n"
                f"👤 المستلم: @{receiver_username}\n"
                f"💰 المبلغ: {amount:,.2f} ل.س\n\n"
                f"هل أنت متأكد من الإهداء؟",
                reply_markup=reply_markup
            )
            return GiftBalanceConversationState.CONFIRM_GIFT
            
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً")
        return GiftBalanceConversationState.ENTER_AMOUNT

@check_subscription
async def confirm_gift_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    user = update.effective_user
    
    if choice != "✅ تأكيد":
        await show_main_menu(update, context)
        return ConversationHandler.END
    
    with DatabaseManager() as db:
        user_data = db.get_user(user.id)
        if user_data['wallet_balance'] < context.user_data['gift_amount']:
            await update.message.reply_text("❌ رصيدك غير كافي", reply_markup=get_main_keyboard())
            return ConversationHandler.END
        
        amount = context.user_data['gift_amount']
        receiver = context.user_data['gift_receiver']
        
        # تنفيذ التحويل
        db.update_wallet_balance(user_data['id'], -amount)
        db.update_wallet_balance(receiver['id'], amount)
        db.record_gift(user_data['id'], receiver['id'], amount)
        
        # إشعار المستلم
        try:
            receiver_data = db.get_user_by_id(receiver['id'])
            if receiver_data:
                await context.bot.send_message(
                    chat_id=receiver_data['telegram_id'],
                    text=f"🎁 لقد تلقيت هدية من @{user_data['bot_username']}\n💰 المبلغ: {amount:,.2f} ل.س"
                )
        except Exception as e:
            logger.error(f"فشل إرسال إشعار للمستلم: {e}")
        
        # إشعار للإدارة
        try:
            await context.bot.send_message(
                chat_id=Config.NOTIFICATION_GROUP_USERNAME,
                text=f"🎁 قام @{user_data['bot_username']} بإهداء {amount:,.2f} ل.س إلى @{receiver['username']}"
            )
        except:
            pass
        
        await update.message.reply_text(
            f"✅ تم إهداء {amount:,.2f} ل.س بنجاح إلى @{receiver['username']}",
            reply_markup=get_main_keyboard()
        )
    
    return ConversationHandler.END

    # =============================================
# معالجات الأدمن - القوائم الرئيسية
# =============================================
async def check_maintenance_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        if not db.is_admin(update.effective_user.id):
            return
        status = db.get_maintenance_message()
        status_text = "مفعّلة" if status else "معطّلة"
        message = f"🛠 حالة الصيانة الحالية: {status_text}"
        if status:
            message += f"\n📄 الرسالة: {status}"
        await update.message.reply_text(message)

# =============================================
# قائمة التدفقات المالية
# =============================================
async def admin_finance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        ["📥 الشحن", "📤 السحب"],
        ["💰 معرفة رصيد محفظة الموقع", "💰 عرض اجمالي الحسابات"],
        ["💱 تغيير سعر الدولار", "💎 تغيير عناوين USDT"],
        ["🏧 تغيير كود سيريتيل", "🏧 تغيير حساب شام كاش"],
        ["🔙 رجوع"]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("💰 قائمة التدفقات المالية - اختر الإجراء:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_FINANCE

# === قائمة الشحن ===
async def admin_deposit_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        methods = db.get_payment_methods('deposit')
    
    buttons = [
        ["⛔️ ايقاف الشحن كاملاً", "✅ تشغيل الشحن كاملاً"],
        ["✅ سيريتيل كاش", "✅ شام كاش"],
        ["✅ USDT", "🎁 بونص الشحن"],
        ["🔙 رجوع"]
    ]
    
    context.user_data['deposit_methods'] = methods
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("📥 إعدادات الشحن:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_DEPOSIT_OPS

async def admin_toggle_all_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    enable = "تشغيل" in update.message.text
    with DatabaseManager() as db:
        db.toggle_all_payment_methods('deposit', enable)
        status = "تشغيل" if enable else "إيقاف"
        await update.message.reply_text(f"✅ تم {status} جميع طرق الشحن")
    return await admin_deposit_ops(update, context)

async def admin_toggle_deposit_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "🔙 رجوع":
        return await admin_finance_menu(update, context)
    if choice == "🎁 بونص الشحن":
        return await admin_bonus_menu(update, context)
    
    methods = context.user_data.get('deposit_methods', [])
    for method in methods:
        if choice.endswith(method['method_name']) or choice.startswith(("✅", "⛔️")) and method['method_name'] in choice:
            with DatabaseManager() as db:
                result = db.toggle_payment_method(method['id'])
                if result:
                    status = "تم تفعيل" if result['is_enabled'] else "تم تعطيل"
                    await update.message.reply_text(f"✅ {status} طريقة {result['method_name']} بنجاح")
            break
    
    return await admin_deposit_ops(update, context)

# === قائمة السحب ===
async def admin_withdraw_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        methods = db.get_payment_methods('withdraw')
    
    buttons = [
        ["⛔️ ايقاف السحب كاملاً", "✅ تشغيل السحب كاملاً"],
        ["✅ سيريتيل كاش", "✅ شام كاش"],
        ["✅ USDT", "📊 تغيير عمولة السحب"],
        ["🔙 رجوع"]
    ]
    
    context.user_data['withdraw_methods'] = methods
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("📤 إعدادات السحب:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_WITHDRAW_OPS

async def admin_toggle_all_withdrawals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    enable = "تشغيل" in update.message.text
    with DatabaseManager() as db:
        db.toggle_all_payment_methods('withdraw', enable)
        status = "تشغيل" if enable else "إيقاف"
        await update.message.reply_text(f"✅ تم {status} جميع طرق السحب")
    return await admin_withdraw_ops(update, context)

async def admin_toggle_withdraw_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "🔙 رجوع":
        return await admin_finance_menu(update, context)
    if choice == "📊 تغيير عمولة السحب":
        return await admin_change_commission_menu(update, context)
    
    methods = context.user_data.get('withdraw_methods', [])
    for method in methods:
        if choice.endswith(method['method_name']) or (method['method_name'] in choice):
            with DatabaseManager() as db:
                result = db.toggle_payment_method(method['id'])
                if result:
                    status = "تم تفعيل" if result['is_enabled'] else "تم تعطيل"
                    await update.message.reply_text(f"✅ {status} طريقة {result['method_name']} بنجاح")
            break
    
    return await admin_withdraw_ops(update, context)

# === تغيير عمولة السحب ===
async def admin_change_commission_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        methods = db.get_payment_methods('withdraw')
    
    buttons = [
        ["سيريتيل كاش (5%)", "شام كاش (10%)"],
        ["USDT (10%)", "🔙 رجوع"]
    ]
    
    context.user_data['commission_methods'] = methods
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("اختر طريقة السحب لتغيير عمولتها:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_CHANGE_COMMISSION

async def admin_handle_change_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "🔙 رجوع":
        return await admin_withdraw_ops(update, context)
    
    methods = context.user_data.get('commission_methods', [])
    for method in methods:
        if method['method_name'] in choice:
            context.user_data['change_commission_method'] = method['method_name']
            await update.message.reply_text(
                f"📊 الطريقة: {method['method_name']}\n"
                f"النسبة الحالية: {method['commission_percentage']}%\n\n"
                f"الرجاء إرسال النسبة الجديدة (مثال: 5 تعني 5%):",
                reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
            )
            return AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE
    
    return await admin_withdraw_ops(update, context)

async def admin_finish_change_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    if value == "❌ إلغاء":
        return await admin_change_commission_menu(update, context)
    
    try:
        commission = float(value)
        if commission < 0 or commission > 100:
            await update.message.reply_text("❌ النسبة يجب أن تكون بين 0 و 100")
            return AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE
        
        method_name = context.user_data.get('change_commission_method')
        with DatabaseManager() as db:
            db.update_method_commission(method_name, 'withdraw', commission)
            if method_name == 'سيريتيل كاش':
                Config.save_setting('SERITEL_WITHDRAW_COMMISSION', commission)
            elif method_name == 'شام كاش':
                Config.save_setting('SHAM_WITHDRAW_COMMISSION', commission)
            elif method_name == 'USDT':
                Config.save_setting('USDT_WITHDRAW_COMMISSION', commission)
            
            await update.message.reply_text(f"✅ تم تغيير عمولة {method_name} إلى {commission}%")
            await update.message.reply_text(f"✅ تم تغيير عمولة {method_name} إلى {commission}%")
        
        return await admin_change_commission_menu(update, context)
    except ValueError:
        await update.message.reply_text("❌ النسبة يجب أن تكون رقماً")
        return AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE

# === البونص ===
async def admin_bonus_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        enabled_methods = db.get_enabled_payment_methods('deposit')
        
        if not enabled_methods:
            await update.message.reply_text("⛔️ لا توجد طرق شحن مفعلة")
            return await admin_deposit_ops(update, context)
    
    buttons = [
        ["سيريتيل كاش (بونص 0%)", "شام كاش (بونص 0%)"],
        ["USDT (بونص 0%)", "🔙 رجوع"]
    ]
    
    context.user_data['bonus_methods'] = enabled_methods
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("🎁 اختر طريقة الشحن لإضافة/تعديل البونص:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_BONUS_METHOD

async def admin_handle_bonus_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "🔙 رجوع":
        return await admin_deposit_ops(update, context)
    
    methods = context.user_data.get('bonus_methods', [])
    for method in methods:
        if method in choice:
            context.user_data['bonus_selected_method'] = method
            await update.message.reply_text(
                f"💯 الطريقة: {method}\n"
                f"الرجاء إرسال نسبة البونص (مثال: 5 يعني 5%):",
                reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
            )
            return AdminConversationState.ADMIN_BONUS_PERCENT
    
    return await admin_bonus_menu(update, context)

async def admin_handle_bonus_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    if value == "❌ إلغاء":
        return await admin_bonus_menu(update, context)
    
    try:
        percent = float(value)
        if percent < 0:
            await update.message.reply_text("❌ النسبة يجب أن تكون 0 أو أكبر")
            return AdminConversationState.ADMIN_BONUS_PERCENT
        
        method = context.user_data.get('bonus_selected_method')
        with DatabaseManager() as db:
            db.add_bonus_setting(method, percent, 'collective')
            await update.message.reply_text(f"✅ تم إضافة بونص {percent}% لطريقة {method}")
        
        return await admin_bonus_menu(update, context)
    except ValueError:
        await update.message.reply_text("❌ النسبة يجب أن تكون رقماً")
        return AdminConversationState.ADMIN_BONUS_PERCENT

# === رصيد المحفظة والإحصائيات ===
async def admin_view_wallet_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    processing_msg = await update.message.reply_text("⏳ جاري جلب رصيد المحفظة...")
    
    try:
        async with WayXBetPlayerRegistrar() as registrar:
            result = await registrar.get_agent_balance()
            await context.bot.delete_message(chat_id=update.effective_user.id, message_id=processing_msg.message_id)
            
            if result['success']:
                await update.message.reply_text(f"💰 رصيد محفظة الوكيل: {result['balance']:,.2f}")
            else:
                await update.message.reply_text(f"❌ فشل في جلب رصيد المحفظة: {result['message']}")
    except Exception as e:
        logger.error(f"خطأ في جلب رصيد المحفظة: {e}")
        await context.bot.delete_message(chat_id=update.effective_user.id, message_id=processing_msg.message_id)
        await update.message.reply_text("❌ حدث خطأ في الاتصال بالموقع")
    
    return AdminConversationState.ADMIN_FINANCE

async def admin_view_total_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        total_accounts = db.get_total_accounts()
        total_balance = db.get_total_balance()
        top_balances = db.get_top_balances(10)
        
        msg = f"👥 إجمالي الحسابات: {total_accounts}\n"
        msg += f"💰 إجمالي الأرصدة: {total_balance:,.2f} ل.س\n\n"
        msg += "🏆 أعلى 10 أرصدة:\n"
        for i, user in enumerate(top_balances, 1):
            tg = f" (@{user['telegram_username']})" if user['telegram_username'] else ""
            msg += f"{i}. {user['bot_username']}{tg}: {user['balance']:,.2f} ل.س\n"
        
        await update.message.reply_text(msg)
    return AdminConversationState.ADMIN_FINANCE

# === تغيير سعر الدولار وعناوين USDT ===
async def admin_change_usd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💱 سعر الصرف الحالي: 1 USDT = {Config.USD_EXCHANGE_RATE:,} ل.س\n\n"
        f"الرجاء إرسال سعر الصرف الجديد:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_CHANGE_USD_RATE

async def admin_handle_change_usd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    if value == "❌ إلغاء":
        return await admin_finance_menu(update, context)
    
    try:
        rate = float(value)
        if rate <= 0:
            await update.message.reply_text("❌ سعر الصرف يجب أن يكون أكبر من الصفر")
            return AdminConversationState.ADMIN_CHANGE_USD_RATE
        
        # تحديث المتغير (مؤقتاً في الذاكرة)
        Config.save_setting('USD_EXCHANGE_RATE', rate)
        await update.message.reply_text(
            f"✅ تم تغيير سعر الصرف إلى: 1 USDT = {rate:,} ل.س\n"
            f"⚠️ ملاحظة: سيتم تطبيق السعر الجديد على المعاملات القادمة فقط."
        )
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون رقماً")
        return AdminConversationState.ADMIN_CHANGE_USD_RATE
    
    return await admin_finance_menu(update, context)

async def admin_change_usdt_addresses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        ["💎 BEP20", "💎 TRC20"],
        ["🔙 رجوع"]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("💎 اختر الشبكة لتغيير العنوان:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_CHANGE_USDT_BEP20

async def admin_handle_change_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "🔙 رجوع":
        return await admin_finance_menu(update, context)
    
    if "BEP20" in choice:
        context.user_data['usdt_network'] = 'BEP20'
        await update.message.reply_text(
            f"العنوان الحالي: {Config.USDT_BEP20_ADDRESS}\n\nالرجاء إرسال عنوان BEP20 الجديد:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_CHANGE_USDT_BEP20
    elif "TRC20" in choice:
        context.user_data['usdt_network'] = 'TRC20'
        await update.message.reply_text(
            f"العنوان الحالي: {Config.USDT_TRC20_ADDRESS}\n\nالرجاء إرسال عنوان TRC20 الجديد:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_CHANGE_USDT_TRC20
    
    return await admin_finance_menu(update, context)

async def admin_save_usdt_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if address == "❌ إلغاء":
        return await admin_change_usdt_addresses(update, context)
    
    network = context.user_data.get('usdt_network')
    if network == 'BEP20':
        Config.save_setting('USDT_BEP20_ADDRESS', address)
    elif network == 'TRC20':
        Config.save_setting('USDT_TRC20_ADDRESS', address)
    
    await update.message.reply_text(f"✅ تم تحديث عنوان {network}")
    return await admin_change_usdt_addresses(update, context)

# === تغيير كود سيريتيل وحساب شام ===
async def admin_change_seritel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        current_code = db.get_seritel_cash_code()
        await update.message.reply_text(
            f"الكود الحالي: {current_code}\n\nقم بإدخال كود الكاش الجديد:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_CHANGE_SERITEL

async def admin_handle_change_seritel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_code = update.message.text.strip()
    if new_code == "❌ إلغاء":
        return await admin_finance_menu(update, context)
    
    context.user_data['new_seritel_code'] = new_code
    await update.message.reply_text(
        f"هل تريد تغيير كود الكاش إلى:\n{new_code}؟",
        reply_markup=ReplyKeyboardMarkup([["✅ تأكيد", "❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_CHANGE_SERITEL_CONFIRM

async def admin_confirm_change_seritel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice != "✅ تأكيد":
        return await admin_finance_menu(update, context)
    
    new_code = context.user_data.get('new_seritel_code')
    with DatabaseManager() as db:
        db.set_seritel_cash_code(new_code)
        Config.save_setting('SERITEL_CASH_CODE', new_code)
        await update.message.reply_text(f"✅ تم تغيير كود الكاش إلى: {new_code}")
    
    return await admin_finance_menu(update, context)

async def admin_change_sham(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        current_account = db.get_sham_cash_account()
        await update.message.reply_text(
            f"الحساب الحالي: {current_account}\n\nقم بإدخال حساب شام كاش الجديد:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_CHANGE_SHAM

async def admin_handle_change_sham(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_account = update.message.text.strip()
    if new_account == "❌ إلغاء":
        return await admin_finance_menu(update, context)
    
    context.user_data['new_sham_account'] = new_account
    await update.message.reply_text(
        f"هل تريد تغيير حساب شام كاش إلى:\n{new_account}؟",
        reply_markup=ReplyKeyboardMarkup([["✅ تأكيد", "❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_CHANGE_SHAM_CONFIRM

async def admin_confirm_change_sham(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice != "✅ تأكيد":
        return await admin_finance_menu(update, context)
    
    new_account = context.user_data.get('new_sham_account')
    with DatabaseManager() as db:
        db.set_sham_cash_account(new_account)
        Config.save_setting('SHAM_CASH_ACCOUNT', new_account)
        await update.message.reply_text(f"✅ تم تغيير حساب شام كاش إلى: {new_account}")
    
    return await admin_finance_menu(update, context)

    # =============================================
# قائمة عمليات المستخدمين
# =============================================
async def admin_user_ops_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        ["💰 تعديل رصيد مستخدم", "📜 كشف سجل لاعب"],
        ["🗑 حذف حساب لاعب", "🔗 ربط حساب لاعب"],
        ["👥 الإحالات", "🚫 حظر مستخدم"],
        ["📩 توجيه رسالة مخصصة", "📢 بث رسالة جماعية"],
        ["🔙 رجوع"]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("👤 قائمة عمليات المستخدمين - اختر الإجراء:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_USER_OPS

# === تعديل رصيد مستخدم ===
async def admin_edit_user_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 الرجاء إرسال اسم المستخدم على البوت (مع أو بدون @):",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_EDIT_BALANCE_USER

async def admin_handle_edit_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if user:
            context.user_data['edit_user'] = {
                'id': user['id'],
                'username': user['bot_username'],
                'current_balance': user.get('wallet_balance', 0)
            }
            await update.message.reply_text(
                f"👤 معلومات المستخدم:\n"
                f"الاسم: @{user['bot_username']}\n"
                f"الرصيد الحالي: {user.get('wallet_balance', 0):,.2f} ل.س\n\n"
                f"💰 الرجاء إرسال الرصيد الجديد:",
                reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
            )
            return AdminConversationState.ADMIN_EDIT_BALANCE_AMOUNT
        else:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم. تأكد من كتابة اسم المستخدم بشكل صحيح.")
            return AdminConversationState.ADMIN_EDIT_BALANCE_USER

async def admin_finish_edit_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if amount_text == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    try:
        new_balance = float(amount_text)
        if new_balance < 0:
            await update.message.reply_text("❌ الرصيد لا يمكن أن يكون سالباً")
            return AdminConversationState.ADMIN_EDIT_BALANCE_AMOUNT
        
        user_data = context.user_data.get('edit_user')
        if not user_data:
            await update.message.reply_text("❌ انتهت الجلسة، يرجى البدء من جديد")
            return await admin_user_ops_menu(update, context)
        
        with DatabaseManager() as db:
            difference = new_balance - user_data['current_balance']
            db.update_wallet_balance(user_data['id'], difference)
            
            await update.message.reply_text(
                f"✅ تم تحديث رصيد @{user_data['username']} بنجاح\n"
                f"الرصيد السابق: {user_data['current_balance']:,.2f} ل.س\n"
                f"الرصيد الجديد: {new_balance:,.2f} ل.س\n"
                f"التغيير: {'+' if difference >= 0 else ''}{difference:,.2f} ل.س"
            )
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً")
        return AdminConversationState.ADMIN_EDIT_BALANCE_AMOUNT
    
    return await admin_user_ops_menu(update, context)

# === كشف سجل لاعب ===
async def admin_user_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 الرجاء إرسال اسم المستخدم للكشف عن سجله:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_USER_HISTORY_USER

async def admin_handle_user_history_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if not user:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم")
            return await admin_user_ops_menu(update, context)
        
        context.user_data['history_user'] = {
            'id': user['id'],
            'username': user['bot_username'],
            'raw_user': user
        }
        
        await update.message.reply_text(
            f"📅 الرجاء إرسال عدد الأيام المطلوب الكشف عنها (مثال: 5):",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_USER_HISTORY_DAYS

async def admin_handle_user_history_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days_text = update.message.text.strip()
    if days_text == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    try:
        days = int(days_text)
        if days <= 0:
            await update.message.reply_text("❌ عدد الأيام يجب أن يكون أكبر من الصفر")
            return AdminConversationState.ADMIN_USER_HISTORY_DAYS
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون رقماً")
        return AdminConversationState.ADMIN_USER_HISTORY_DAYS
    
    user_info = context.user_data.get('history_user')
    user = user_info['raw_user']
    
    # إرسال معلومات المستخدم
    await update.message.reply_text(
        f"📋 معلومات المستخدم:\n"
        f"👤 اسم البوت: @{user['bot_username']}\n"
        f"📱 معرف تيليجرام: {user['telegram_id']}\n"
        f"💰 رصيد البوت: {user.get('wallet_balance', 0):,.2f} ل.س\n"
        f"🌐 اسم الموقع: {user['wayxbet_username'] or 'لا يوجد'}\n"
        f"⚽️ معرف اللاعب: {user['wayxbet_player_id'] or 'لا يوجد'}\n"
        f"📅 تاريخ التسجيل: {user['created_at']}"
    )
    
    # جلب السجل
    with DatabaseManager() as db:
        history = db.get_user_history(user['bot_username'], days)
        
        if history:
            # تقسيم السجل إلى رسائل منفصلة (كل 15 سجل)
            chunk_size = 15
            for i in range(0, len(history), chunk_size):
                chunk = history[i:i+chunk_size]
                msg = f"📜 سجل {user['bot_username']} - الجزء {i//chunk_size + 1}:\n\n"
                for record in chunk:
                    msg += f"• [{record['type']}] {record['amount']:,.2f} - {record['method']} - {record['created_at']}\n"
                await update.message.reply_text(msg)
        else:
            await update.message.reply_text("📭 لا يوجد سجل للمستخدم في الفترة المحددة")
    
    return await admin_user_ops_menu(update, context)

# === حذف حساب لاعب ===
async def admin_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🗑 الرجاء إرسال اسم المستخدم على البوت الذي تريد حذفه:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_DELETE_USER_CONFIRM

async def admin_handle_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if not user:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم")
            return await admin_user_ops_menu(update, context)
        
        context.user_data['delete_user'] = {
            'username': user['bot_username'],
            'balance': user.get('wallet_balance', 0),
            'wayxbet_username': user['wayxbet_username'] or 'لا يوجد',
            'wayxbet_player_id': user['wayxbet_player_id'] or 'لا يوجد'
        }
        
        # جلب رصيد الموقع
        wayxbet_balance = "غير معروف"
        if user['wayxbet_player_id']:
            try:
                async with WayXBetPlayerRegistrar() as registrar:
                    result = await registrar.get_player_balance(user['wayxbet_player_id'])
                    if result['success']:
                        wayxbet_balance = f"{result['balance']:,.2f} {result['currency']}"
            except:
                pass
        
        await update.message.reply_text(
            f"⚠️ تأكيد حذف المستخدم:\n\n"
            f"👤 اسم البوت: @{user['bot_username']}\n"
            f"💰 رصيد البوت: {user.get('wallet_balance', 0):,.2f} ل.س\n"
            f"🌐 اسم الموقع: {user['wayxbet_username'] or 'لا يوجد'}\n"
            f"💰 رصيد الموقع: {wayxbet_balance}\n"
            f"⚽️ معرف اللاعب: {user['wayxbet_player_id'] or 'لا يوجد'}\n\n"
            f"❗️ سيتم فك ارتباط الحساب بالموقع فقط (لن يتم حذف الحساب من الموقع)\n\n"
            f"هل أنت متأكد؟",
            reply_markup=ReplyKeyboardMarkup([["✅ تأكيد الحذف", "❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_DELETE_USER_CONFIRM

async def admin_confirm_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice != "✅ تأكيد الحذف":
        return await admin_user_ops_menu(update, context)
    
    user_info = context.user_data.get('delete_user')
    if not user_info:
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        success, message = db.delete_user(user_info['username'])
        await update.message.reply_text(f"{'✅' if success else '❌'} {message}")
    
    return await admin_user_ops_menu(update, context)

# === ربط حساب لاعب ===
async def admin_link_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔗 الرجاء إرسال اسم المستخدم على البوت:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_LINK_ACCOUNT_USER

async def admin_handle_link_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if not user:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم")
            return await admin_user_ops_menu(update, context)
        
        context.user_data['link_user'] = {
            'id': user['id'],
            'username': user['bot_username'],
            'telegram_id': user['telegram_id']
        }
        
        await update.message.reply_text(
            f"👤 المستخدم: @{user['bot_username']}\n"
            f"⚽️ المعرف الحالي: {user['wayxbet_player_id'] or 'لا يوجد'}\n\n"
            f"الرجاء إرسال معرف اللاعب الجديد على الموقع:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_LINK_ACCOUNT_ID

async def admin_handle_link_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player_id = update.message.text.strip()
    if player_id == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    if not player_id.isdigit():
        await update.message.reply_text("❌ معرف اللاعب يجب أن يكون رقماً")
        return AdminConversationState.ADMIN_LINK_ACCOUNT_ID
    
    context.user_data['link_player_id'] = player_id
    
    # جلب معلومات اللاعب من الموقع
    processing_msg = await update.message.reply_text("⏳ جاري جلب معلومات اللاعب...")
    
    try:
        async with WayXBetPlayerRegistrar() as registrar:
            player_info = await registrar.get_player_info_by_id(player_id)
            
            await context.bot.delete_message(chat_id=update.effective_user.id, message_id=processing_msg.message_id)
            
            if player_info:
                context.user_data['link_player_info'] = player_info
                
                await update.message.reply_text(
                    f"🔍 تم العثور على اللاعب:\n"
                    f"👤 الاسم: {player_info.get('username', 'غير معروف')}\n"
                    f"⚽️ المعرف: {player_id}\n"
                    f"📱 الهاتف: {player_info.get('phoneNumber', 'غير معروف')}\n\n"
                    f"هل تريد ربط هذا الحساب مع @{context.user_data['link_user']['username']}؟",
                    reply_markup=ReplyKeyboardMarkup([["✅ تأكيد الربط", "❌ إلغاء"]], resize_keyboard=True)
                )
                return AdminConversationState.ADMIN_LINK_ACCOUNT_CONFIRM
            else:
                await update.message.reply_text("❌ لم يتم العثور على اللاعب بهذا المعرف. هل تريد المتابعة بالربط على أي حال؟",
                    reply_markup=ReplyKeyboardMarkup([["✅ متابعة", "❌ إلغاء"]], resize_keyboard=True))
                return AdminConversationState.ADMIN_LINK_ACCOUNT_CONFIRM
    except Exception as e:
        logger.error(f"خطأ في جلب معلومات اللاعب: {e}")
        await context.bot.delete_message(chat_id=update.effective_user.id, message_id=processing_msg.message_id)
        await update.message.reply_text("❌ حدث خطأ في الاتصال بالموقع. حاول مرة أخرى.")
        return await admin_user_ops_menu(update, context)

async def admin_confirm_link_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice not in ["✅ تأكيد الربط", "✅ متابعة"]:
        return await admin_user_ops_menu(update, context)
    
    player_id = context.user_data.get('link_player_id')
    user_info = context.user_data.get('link_user')
    
    with DatabaseManager() as db:
        success = db.link_wayxbet_account(user_info['username'], player_id)
        if success:
            player_info = context.user_data.get('link_player_info', {})
            wayxbet_username = player_info.get('username', 'غير معروف') if player_info else 'غير معروف'
            
            # تحديث اسم المستخدم على الموقع إذا كان متوفراً
            if wayxbet_username != 'غير معروف':
                db.conn.execute('UPDATE users SET wayxbet_username = ? WHERE id = ?', (wayxbet_username, user_info['id']))
                db.conn.commit()
            
            await update.message.reply_text(
                f"✅ تم ربط الحساب بنجاح\n"
                f"👤 المستخدم: @{user_info['username']}\n"
                f"🌐 حساب الموقع: {wayxbet_username}\n"
                f"⚽️ معرف اللاعب: {player_id}"
            )
        else:
            await update.message.reply_text("❌ فشل في ربط الحساب")
    
    return await admin_user_ops_menu(update, context)

# === الإحالات ===
async def admin_referrals_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👥 الرجاء إرسال اسم المستخدم للكشف عن إحالاته:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_REFERRALS_USER

async def admin_handle_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if not user:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم")
            return await admin_user_ops_menu(update, context)
        
        referrals = db.get_referrals(user['id'])
        total_commission = db.get_commissions(user['id'])
        
        msg = f"👥 تقرير إحالات @{user['bot_username']}:\n\n"
        msg += f"📊 إجمالي الإحالات: {len(referrals)}\n"
        msg += f"💰 إجمالي الأرباح: {total_commission:,.2f} ل.س\n\n"
        
        if referrals:
            msg += "📋 قائمة الإحالات:\n"
            for i, ref in enumerate(referrals, 1):
                msg += f"{i}. @{ref['bot_username']}"
                if ref['telegram_username']:
                    msg += f" (tg: @{ref['telegram_username']})"
                msg += f"\n   📅 تاريخ التسجيل: {ref['created_at']}"
                msg += f"\n   💰 عمولة: {ref['total_commission']:,.2f} ل.س\n"
        else:
            msg += "لا توجد إحالات حتى الآن"
        
        await update.message.reply_text(msg)
    
    return await admin_user_ops_menu(update, context)

# === حظر مستخدم ===
async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚫 الرجاء إرسال اسم المستخدم (مع أو بدون @):",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_BAN_USER

async def admin_handle_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if user:
            context.user_data['ban_target'] = {
                'id': user['id'],
                'username': user['bot_username'],
                'telegram_id': user['telegram_id'],
                'is_banned': user.get('is_banned', 0)
            }
            
            if user.get('is_banned', 0):
                buttons = [["✅ إلغاء الحظر"], ["❌ إلغاء"]]
                status_text = "محظور حالياً"
            else:
                buttons = [["⛔️ حظر المستخدم"], ["❌ إلغاء"]]
                status_text = "غير محظور"
            
            await update.message.reply_text(
                f"🚫 معلومات المستخدم:\n"
                f"👤 الاسم: @{user['bot_username']}\n"
                f"📊 الحالة: {status_text}\n\n"
                f"اختر الإجراء المطلوب:",
                reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
            )
            return AdminConversationState.ADMIN_BAN_USER
        else:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم")
            return await admin_user_ops_menu(update, context)

async def admin_finish_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = update.message.text.strip()
    target = context.user_data.get('ban_target')
    
    if not target:
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        if action == "⛔️ حظر المستخدم":
            db.ban_user(target['username'])
            await update.message.reply_text(f"✅ تم حظر المستخدم @{target['username']} بنجاح")
            try:
                await context.bot.send_message(
                    chat_id=target['telegram_id'],
                    text="⚠️ تم حظر حسابك في البوت. الرجاء التواصل مع الدعم لمزيد من المعلومات."
                )
            except:
                pass
        
        elif action == "✅ إلغاء الحظر":
            db.unban_user(target['username'])
            await update.message.reply_text(f"✅ تم إلغاء حظر المستخدم @{target['username']} بنجاح")
            try:
                await context.bot.send_message(
                    chat_id=target['telegram_id'],
                    text="🎉 تم إلغاء حظر حسابك في البوت. يمكنك الآن استخدام البوت بشكل طبيعي."
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ إجراء غير معروف")
    
    return await admin_user_ops_menu(update, context)

# === توجيه رسالة مخصصة ===
async def admin_send_custom_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 الرجاء إرسال اسم المستخدم:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_SEND_MESSAGE_USER

async def admin_handle_custom_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    if username == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if not user:
            await update.message.reply_text("❌ لم يتم العثور على المستخدم")
            return await admin_user_ops_menu(update, context)
        
        context.user_data['custom_message_user'] = {
            'telegram_id': user['telegram_id'],
            'username': user['bot_username']
        }
        
        await update.message.reply_text(
            f"📩 الرجاء إرسال الرسالة المراد توجيهها إلى @{user['bot_username']}:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_SEND_MESSAGE_TEXT

async def admin_finish_custom_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text.strip()
    if message == "❌ إلغاء":
        return await admin_user_ops_menu(update, context)
    
    user_info = context.user_data.get('custom_message_user')
    if not user_info:
        return await admin_user_ops_menu(update, context)
    
    try:
        await context.bot.send_message(
            chat_id=user_info['telegram_id'],
            text=f"📬 رسالة من الإدارة:\n\n{message}"
        )
        await update.message.reply_text(f"✅ تم إرسال الرسالة بنجاح إلى @{user_info['username']}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إرسال الرسالة: {str(e)}")
    
    return await admin_user_ops_menu(update, context)

    # =============================================
# قائمة الهدايا والعروض
# =============================================
async def admin_gifts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        ["🎁 انشاء اكواد هدايا", "🎫 انشاء كود برومو"],
        ["🔙 رجوع"]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await update.message.reply_text("🎁 قائمة الهدايا والعروض - اختر الإجراء:", reply_markup=reply_markup)
    return AdminConversationState.ADMIN_GIFTS

# === انشاء أكواد هدايا ===
async def admin_create_voucher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 الرجاء إرسال مبلغ كود الهدية:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_CREATE_VOUCHER_AMOUNT

async def admin_handle_voucher_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if amount_text == "❌ إلغاء":
        return await admin_gifts_menu(update, context)
    
    try:
        amount = float(amount_text)
        if amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر")
            return AdminConversationState.ADMIN_CREATE_VOUCHER_AMOUNT
        
        context.user_data['voucher_amount'] = amount
        await update.message.reply_text(
            "🔢 الرجاء إرسال عدد الأكواد المراد إنشاؤها:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_CREATE_VOUCHER_COUNT
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً")
        return AdminConversationState.ADMIN_CREATE_VOUCHER_AMOUNT

async def admin_finish_create_vouchers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count_text = update.message.text.strip()
    if count_text == "❌ إلغاء":
        return await admin_gifts_menu(update, context)
    
    try:
        count = int(count_text)
        if count <= 0:
            await update.message.reply_text("❌ يجب أن يكون العدد أكبر من الصفر.")
            return AdminConversationState.ADMIN_CREATE_VOUCHER_COUNT
        if count > 100:
            await update.message.reply_text("❌ الحد الأقصى 100 كود في المرة الواحدة.")
            return AdminConversationState.ADMIN_CREATE_VOUCHER_COUNT
        
        amount = context.user_data['voucher_amount']
        with DatabaseManager() as db:
            codes = []
            for _ in range(count):
                while True:
                    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                    if db.create_voucher(code, amount, created_by=update.effective_user.id):
                        codes.append(code)
                        break
            
            codes_msg = "\n".join(codes)
            await update.message.reply_text(
                f"✅ تم إنشاء {count} كود هدية:\n\n"
                f"💰 المبلغ: {amount:,.2f} ل.س\n"
                f"📋 الأكواد:\n{codes_msg}"
            )
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون العدد رقماً صحيحاً")
        return AdminConversationState.ADMIN_CREATE_VOUCHER_COUNT
    
    return await admin_gifts_menu(update, context)

# === انشاء كود برومو ===
async def admin_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 الرجاء إرسال مبلغ كود البرومو:",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_CREATE_PROMO_AMOUNT

async def admin_handle_promo_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if amount_text == "❌ إلغاء":
        return await admin_gifts_menu(update, context)
    
    try:
        amount = float(amount_text)
        if amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من الصفر")
            return AdminConversationState.ADMIN_CREATE_PROMO_AMOUNT
        
        context.user_data['promo_amount'] = amount
        await update.message.reply_text(
            "👥 الرجاء إرسال عدد المستخدمين المسموح لهم باستخدام الكود:",
            reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
        )
        return AdminConversationState.ADMIN_CREATE_PROMO_USES
    except ValueError:
        await update.message.reply_text("❌ المبلغ يجب أن يكون رقماً")
        return AdminConversationState.ADMIN_CREATE_PROMO_AMOUNT

async def admin_finish_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uses_text = update.message.text.strip()
    if uses_text == "❌ إلغاء":
        return await admin_gifts_menu(update, context)
    
    try:
        max_uses = int(uses_text)
        if max_uses <= 0:
            await update.message.reply_text("❌ يجب أن يكون العدد أكبر من الصفر")
            return AdminConversationState.ADMIN_CREATE_PROMO_USES
        
        amount = context.user_data['promo_amount']
        
        # إنشاء كود فريد
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        with DatabaseManager() as db:
            # التأكد من أن الكود غير موجود
            while True:
                cursor = db.conn.execute('SELECT 1 FROM promo_codes WHERE code = ?', (code,))
                if not cursor.fetchone():
                    break
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            
            success = db.create_promo_code(code, amount, max_uses, created_by=update.effective_user.id)
            if success:
                await update.message.reply_text(
                    f"✅ تم إنشاء كود البرومو بنجاح:\n\n"
                    f"🎫 الكود: {code}\n"
                    f"💰 المبلغ: {amount:,.2f} ل.س\n"
                    f"👥 عدد الاستخدامات: {max_uses}\n"
                    f"📝 ملاحظة: كل مستخدم يمكنه استخدام الكود مرة واحدة فقط"
                )
            else:
                await update.message.reply_text("❌ فشل في إنشاء الكود")
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون العدد رقماً صحيحاً")
        return AdminConversationState.ADMIN_CREATE_PROMO_USES
    
    return await admin_gifts_menu(update, context)

# =============================================
# البث الجماعي
# =============================================
async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📢 الرجاء إرسال الرسالة أو الصورة للبث (يمكنك إرسال نص، صورة، فيديو):",
        reply_markup=ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    )
    return AdminConversationState.ADMIN_BROADCAST_MESSAGE

async def admin_handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() == "❌ إلغاء":
        return await show_admin_panel(update, context)
    
    status_msg = await update.message.reply_text("⏳ جاري البث...")
    
    with DatabaseManager() as db:
        cursor = db.conn.execute('SELECT telegram_id FROM users')
        users = cursor.fetchall()
        
        success_count = 0
        fail_count = 0
        
        for user in users:
            try:
                if update.message.text:
                    await context.bot.send_message(chat_id=user['telegram_id'], text=update.message.text)
                elif update.message.photo:
                    photo = update.message.photo[-1].file_id
                    caption = update.message.caption or ""
                    await context.bot.send_photo(chat_id=user['telegram_id'], photo=photo, caption=caption)
                elif update.message.video:
                    video = update.message.video.file_id
                    caption = update.message.caption or ""
                    await context.bot.send_video(chat_id=user['telegram_id'], video=video, caption=caption)
                else:
                    continue
                success_count += 1
                await asyncio.sleep(0.05)  # تجنب حظر الفيضان
            except Exception as e:
                fail_count += 1
                logger.error(f"فشل إرسال الرسالة إلى {user['telegram_id']}: {e}")
        
        await context.bot.delete_message(chat_id=update.effective_user.id, message_id=status_msg.message_id)
        await update.message.reply_text(
            f"✅ تم بث الرسالة بنجاح\n"
            f"📊 عدد المستلمين: {success_count}\n"
            f"❌ فشل: {fail_count}"
        )
    
    return await show_admin_panel(update, context)

# =============================================
# الصيانة
# =============================================
async def admin_toggle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with DatabaseManager() as db:
        current_msg = db.get_maintenance_message()
        if current_msg:
            db.set_maintenance_message(None)
            await update.message.reply_text("✅ تم تعطيل وضع الصيانة")
        else:
            await update.message.reply_text(
                "🛠 الرجاء إرسال رسالة الصيانة (أو استخدم الرسالة الافتراضية):",
                reply_markup=ReplyKeyboardMarkup([["📝 استخدام الافتراضية", "❌ إلغاء"]], resize_keyboard=True)
            )
            return AdminConversationState.ADMIN_MAINTENANCE_TEXT
    return AdminConversationState.ADMIN_MAIN

async def admin_handle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text == "❌ إلغاء":
        return await show_admin_panel(update, context)
    
    if text == "📝 استخدام الافتراضية":
        message = "🔧 البوت في صيانة مؤقتة، خدمة EagleBet غير متاحة حالياً. باقي الخدمات متاحة."
    else:
        message = text
    
    with DatabaseManager() as db:
        db.set_maintenance_message(message)
        await update.message.reply_text(f"✅ تم تفعيل وضع الصيانة بالرسالة:\n\n{message}")
    
    return await show_admin_panel(update, context)

# =============================================
# نظام التقارير اليومية
# =============================================
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    """إرسال تقرير يومي لقناة التقارير"""
    try:
        with DatabaseManager() as db:
            deposits = db.get_daily_deposits_summary()
            withdrawals = db.get_daily_withdrawals_summary()
            wayxbet = db.get_daily_wayxbet_summary()
            
            total_deposits = sum(d['total'] for d in deposits)
            total_withdrawals = sum(w['total'] for w in withdrawals)
            difference = total_deposits - total_withdrawals
            
            report = "📊 التقرير اليومي لعمليات البوت\n\n"
            report += "📥 عمليات الشحن:\n"
            if deposits:
                for d in deposits:
                    report += f"  • {d['method']}: {d['count']} عملية - {d['total']:,.2f} ل.س\n"
            else:
                report += "  • لا توجد عمليات شحن\n"
            
            report += f"\n📤 عمليات السحب:\n"
            if withdrawals:
                for w in withdrawals:
                    report += f"  • {w['method']}: {w['count']} عملية - {w['total']:,.2f} ل.س\n"
            else:
                report += "  • لا توجد عمليات سحب\n"
            
            report += f"\n🌐 عمليات الموقع:\n"
            report += f"  • تعبئة: {wayxbet['deposits']:,.2f} ل.س\n"
            report += f"  • سحب: {wayxbet['withdrawals']:,.2f} ل.س\n"
            
            report += f"\n💰 ملخص:\n"
            report += f"  • إجمالي الشحن: {total_deposits:,.2f} ل.س\n"
            report += f"  • إجمالي السحب: {total_withdrawals:,.2f} ل.س\n"
            report += f"  • الفرق: {difference:,.2f} ل.س\n"
            report += f"\n⏰ تاريخ التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await context.bot.send_message(chat_id=Config.REPORTS_CHANNEL_USERNAME, text=report)
            logger.info("تم إرسال التقرير اليومي بنجاح")
    except Exception as e:
        logger.error(f"خطأ في إرسال التقرير اليومي: {e}")
        try:
            await context.bot.send_message(
                chat_id=Config.ERRORS_CHANNEL_USERNAME,
                text=f"❌ خطأ في إرسال التقرير اليومي: {str(e)}"
            )
        except:
            pass
        # =============================================
# معالجات الموافقة على طلبات السحب (للأدمن)
# =============================================
async def handle_withdraw_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة قبول أو رفض طلبات السحب من قبل الأدمن"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split('_')
    action = parts[0]  # approve أو reject
    withdraw_id = int(parts[-1])
    
    with DatabaseManager() as db:
        # التحقق من صلاحيات المستخدم
        admin_user = db.get_user(query.from_user.id)
        if not admin_user or not db.is_admin(query.from_user.id):
            await query.answer("❌ ليس لديك صلاحية الموافقة على هذه العملية", show_alert=True)
            return
        
        # جلب معلومات طلب السحب
        cursor = db.conn.execute('''
        SELECT w.*, u.telegram_id, u.bot_username 
        FROM withdrawals w
        JOIN users u ON w.user_id = u.id
        WHERE w.id = ?
        ''', (withdraw_id,))
        withdraw = cursor.fetchone()
        
        if not withdraw:
            await query.edit_message_text("❌ لم يتم العثور على طلب السحب.")
            return
        
        if withdraw['status'] != 'pending':
            await query.answer("تم معالجة هذا الطلب مسبقاً", show_alert=True)
            return
        
        if action == 'approve':
            # تحديث حالة الطلب إلى مقبول
            db.conn.execute('UPDATE withdrawals SET status = ?, processed_at = ? WHERE id = ?', 
                          ('approved', datetime.now(), withdraw_id))
            db.conn.commit()
            
            # إرسال إشعار للمستخدم
            try:
                method_text = withdraw['method']
                detail = ""
                if method_text == 'سيريتيل كاش':
                    detail = f"📞 الرقم: {withdraw['phone']}"
                elif method_text == 'شام كاش':
                    detail = f"📞 الحساب: {withdraw['account']}"
                elif method_text == 'USDT':
                    detail = f"📝 العنوان: {withdraw['usdt_address']}\n🌐 الشبكة: {withdraw['usdt_network']}"
                
                await context.bot.send_message(
                    chat_id=withdraw['telegram_id'],
                    text=f"✅ تم قبول طلب السحب وإرسال المبلغ بنجاح.\n"
                         f"💰 المبلغ: {withdraw['amount']:,.2f}\n"
                         f"{detail}"
                )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار للمستخدم: {e}")
            
            # تحديث رسالة المجموعة
            approval_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_text = (
                f"✅ وافق حساب الدعم على الطلب\n"
                f"👤 المستخدم: @{withdraw['bot_username']}\n"
                f"💰 المبلغ: {withdraw['amount']:,.2f}\n"
                f"⏰ تمت الموافقة: {approval_time}"
            )
            await query.edit_message_text(text=new_text, reply_markup=None)
            
        elif action == 'reject':
            # إرجاع المبلغ كاملاً (مع العمولة) للمستخدم
            refund_amount = withdraw['total_amount']
            db.update_wallet_balance(withdraw['user_id'], refund_amount)
            
            # تحديث حالة الطلب إلى مرفوض
            db.conn.execute('UPDATE withdrawals SET status = ?, processed_at = ? WHERE id = ?', 
                          ('rejected', datetime.now(), withdraw_id))
            db.conn.commit()
            
            # إرسال إشعار للمستخدم
            try:
                await context.bot.send_message(
                    chat_id=withdraw['telegram_id'],
                    text=f"❌ تم رفض طلب السحب وإرجاع المبلغ ({refund_amount:,.2f} ل.س) إلى رصيدك.\n"
                         f"📝 الرجاء التواصل مع الدعم للمزيد من المعلومات."
                )
            except Exception as e:
                logger.error(f"فشل إرسال إشعار للمستخدم: {e}")
            
            # تحديث رسالة المجموعة
            rejection_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_text = (
                f"❌ رفض حساب الدعم الطلب\n"
                f"👤 المستخدم: @{withdraw['bot_username']}\n"
                f"💰 المبلغ: {withdraw['amount']:,.2f}\n"
                f"⏰ تم الرفض: {rejection_time}"
            )
            await query.edit_message_text(text=new_text, reply_markup=None)

# =============================================
# معالج تحويل رسالة المستخدم للكشف عن سجلاته
# =============================================
async def handle_forwarded_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عندما يقوم الأدمن بتحويل رسالة المستخدم، يقوم البوت بإرسال كشف كامل عن سجلات المستخدم"""
    
    # التأكد أن المستخدم أدمن
    with DatabaseManager() as db:
        if not db.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ هذا الأمر مخصص للأدمن فقط.")
            return
    
    message = update.message
    
    # طباعة معلومات Debug لمعرفة هيكل الرسالة
    logger.info(f"Message object: {message}")
    logger.info(f"Message keys: {dir(message)}")
    
    # محاولة الحصول على معلومات المستخدم المحول بجميع الطرق الممكنة
    user_id = None
    user_name = None
    
    # الطريقة 1: استخدام forward_from
    if hasattr(message, 'forward_from') and message.forward_from:
        user_id = message.forward_from.id
        user_name = message.forward_from.username or f"المستخدم {user_id}"
        logger.info(f"Found via forward_from: {user_id}")
    
    # الطريقة 2: استخدام forward_origin (للمكتبات الجديدة)
    elif hasattr(message, 'forward_origin') and message.forward_origin:
        origin = message.forward_origin
        logger.info(f"Forward origin type: {type(origin)}")
        logger.info(f"Forward origin: {origin}")
        
        if hasattr(origin, 'sender_user') and origin.sender_user:
            user_id = origin.sender_user.id
            user_name = origin.sender_user.username or f"المستخدم {user_id}"
        elif hasattr(origin, 'chat') and origin.chat:
            # تأكد أنه مستخدم وليس قناة
            if origin.chat.type == 'private':
                user_id = origin.chat.id
                user_name = origin.chat.username or f"المستخدم {user_id}"
    
    # الطريقة 3: استخدام forward_from_chat
    elif hasattr(message, 'forward_from_chat') and message.forward_from_chat:
        chat = message.forward_from_chat
        if chat.type == 'private':  # تأكد أنه مستخدم وليس قناة
            user_id = chat.id
            user_name = chat.username or f"المستخدم {user_id}"
        else:
            # قد يكون من قناة أو مجموعة
            await update.message.reply_text(
                "⚠️ الرسالة محولة من قناة أو مجموعة، وليس من مستخدم فردي.\n\n"
                "📌 الرجاء تحويل رسالة من المستخدم نفسه وليس من قناة."
            )
            return
    
    # إذا لم يتم العثور على معلومات
    if not user_id:
        await update.message.reply_text(
            "⚠️ **لم يتم التعرف على المرسل الأصلي للرسالة.**\n\n"
            "📌 **الطريقة الصحيحة:**\n"
            "1️⃣ اذهب إلى المحادثة مع المستخدم\n"
            "2️⃣ اضغط مع الاستمرار على أي رسالة من المستخدم\n"
            "3️⃣ اختر 'تحويل' أو 'Forward'\n"
            "4️⃣ اختر البوت من قائمة الجهات\n"
            "5️⃣ أرسل الرسالة\n\n"
            "💡 **ملاحظة:** يجب أن تكون الرسالة مرسلة من المستخدم نفسه، وليس من قناة أو مجموعة.\n\n"
            "🔄 **بديل:** يمكنك استخدام الأمر `/history @username` للحصول على سجل المستخدم."
        )
        return
    
    # رسالة المعالجة
    processing_msg = await update.message.reply_text(f"⏳ جاري جلب معلومات المستخدم {user_name} ...")
    
    with DatabaseManager() as db:
        # محاولة البحث بالمستخدم بعدة طرق
        user_data = db.get_user(user_id)
        
        # إذا لم نجد بالمستخدم، نحاول البحث باسم المستخدم
        if not user_data and user_name:
            user_data = db.get_user_by_username(user_name)
        
        if not user_data:
            await context.bot.delete_message(
                chat_id=update.effective_user.id, 
                message_id=processing_msg.message_id
            )
            await update.message.reply_text(
                f"❌ **لم يتم العثور على المستخدم** `{user_name}` في قاعدة البيانات.\n\n"
                f"💡 **الأسباب المحتملة:**\n"
                f"• المستخدم لم يبدأ البوت بعد (لم يضغط /start)\n"
                f"• المستخدم ليس لديه حساب في البوت\n\n"
                f"🆔 **معرف المستخدم المحاول:** `{user_id}`\n\n"
                f"📌 **لحل المشكلة:** اطلب من المستخدم الضغط على /start في البوت أولاً.",
                parse_mode='Markdown'
            )
            return
        
        # بناء الكشف الكامل
        response = (
            f"📋 **كشف حساب المستخدم**\n\n"
            f"👤 **المعلومات الأساسية:**\n"
            f"├ 🆔 معرف البوت: @{user_data['bot_username']}\n"
            f"├ 📱 معرف تليجرام: `{user_data['telegram_id']}`\n"
            f"├ 📅 تاريخ التسجيل: {user_data['created_at']}\n"
            f"├ 🚫 الحظر: {'✅ محظور' if user_data['is_banned'] else '❌ غير محظور'}\n"
            f"└ 💰 رصيد البوت: {user_data.get('wallet_balance', 0):,.2f} ل.س\n\n"
            f"🌐 **معلومات حساب الموقع:**\n"
            f"├ 👤 اسم المستخدم: {user_data['wayxbet_username'] or '❌ لا يوجد'}\n"
            f"├ 🆔 معرف اللاعب: {user_data['wayxbet_player_id'] or '❌ لا يوجد'}\n"
            f"└ 💰 رصيد الموقع: "
        )
        
        # جلب رصيد الموقع
        if user_data['wayxbet_player_id']:
            try:
                async with WayXBetPlayerRegistrar() as registrar:
                    balance_result = await registrar.get_player_balance(user_data['wayxbet_player_id'])
                    if balance_result['success']:
                        response += f"{balance_result['balance']:,.2f} {balance_result['currency']}\n"
                    else:
                        response += "❌ تعذر الجلب\n"
            except:
                response += "❌ خطأ في الاتصال\n"
        else:
            response += "❌ لا يوجد حساب\n"
        
        # الإحالات
        referrals = db.get_referrals(user_data['id'])
        total_commission = db.get_commissions(user_data['id'])
        
        response += f"\n👥 **معلومات الإحالات:**\n"
        response += f"├ 📊 عدد الإحالات: {len(referrals)}\n"
        response += f"└ 💰 إجمالي الأرباح: {total_commission:,.2f} ل.س\n"
        
        # آخر العمليات
        history = db.get_user_history(user_data['bot_username'], days=30)
        if history:
            response += f"\n📜 **آخر 5 عمليات:**\n"
            for i, record in enumerate(history[:5], 1):
                emoji = "💰" if record['type'] == 'ايداع' else "💸" if record['type'] == 'سحب' else "🔄"
                response += f"{i}. {emoji} {record['amount']:,.2f} ل.س - {record['method']}\n"
                response += f"   └ 📅 {record['created_at'][:16]}\n"
        
        # رابط الدعوة
        response += f"\n🔗 **رابط الدعوة:**\n"
        response += f"└ `https://t.me/{Config.BOT_USERNAME}?start={user_data['telegram_id']}`"
        
        await context.bot.delete_message(
            chat_id=update.effective_user.id, 
            message_id=processing_msg.message_id
        )
        await update.message.reply_text(response, parse_mode='Markdown')

        # أمر للحصول على سجل مستخدم بالاسم
async def cmd_user_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الأمر: /history @username - عرض سجل كامل للمستخدم"""
    
    with DatabaseManager() as db:
        if not db.is_admin(update.effective_user.id):
            await update.message.reply_text("❌ هذا الأمر مخصص للأدمن فقط.")
            return
    
    if not context.args:
        await update.message.reply_text(
            "📌 **الاستخدام الصحيح:**\n"
            "`/history @username`\n\n"
            "مثال: `/history user123`\n\n"
            "📌 **بديل:** يمكنك تحويل رسالة المستخدم للبوت للحصول على نفس المعلومات.",
            parse_mode='Markdown'
        )
        return
    
    username = context.args[0].replace('@', '')
    
    # رسالة المعالجة
    processing_msg = await update.message.reply_text(f"⏳ جاري جلب معلومات المستخدم @{username} ...")
    
    with DatabaseManager() as db:
        user = db.get_user_by_username(username)
        if not user:
            await context.bot.delete_message(
                chat_id=update.effective_user.id, 
                message_id=processing_msg.message_id
            )
            await update.message.reply_text(f"❌ لم يتم العثور على المستخدم @{username}\n\n💡 تأكد من أن المستخدم قام بـ /start في البوت أولاً.")
            return
        
        # بناء الكشف الكامل
        response = (
            f"📋 **كشف حساب المستخدم**\n\n"
            f"👤 **المعلومات الأساسية:**\n"
            f"├ 🆔 معرف البوت: @{user['bot_username']}\n"
            f"├ 📱 معرف تليجرام: `{user['telegram_id']}`\n"
            f"├ 📅 تاريخ التسجيل: {user['created_at']}\n"
            f"├ 🚫 الحظر: {'✅ محظور' if user['is_banned'] else '❌ غير محظور'}\n"
            f"└ 💰 رصيد البوت: {user.get('wallet_balance', 0):,.2f} ل.س\n\n"
            f"🌐 **معلومات حساب الموقع:**\n"
            f"├ 👤 اسم المستخدم: {user['wayxbet_username'] or '❌ لا يوجد'}\n"
            f"├ 🆔 معرف اللاعب: {user['wayxbet_player_id'] or '❌ لا يوجد'}\n"
            f"└ 💰 رصيد الموقع: "
        )
        
        # جلب رصيد الموقع إذا وجد
        if user['wayxbet_player_id']:
            try:
                async with WayXBetPlayerRegistrar() as registrar:
                    balance_result = await registrar.get_player_balance(user['wayxbet_player_id'])
                    if balance_result['success']:
                        response += f"{balance_result['balance']:,.2f} {balance_result['currency']}\n"
                    else:
                        response += "❌ تعذر الجلب\n"
            except:
                response += "❌ خطأ في الاتصال\n"
        else:
            response += "❌ لا يوجد حساب\n"
        
        # إضافة معلومات الإحالات
        referrals = db.get_referrals(user['id'])
        total_commission = db.get_commissions(user['id'])
        
        response += f"\n👥 **معلومات الإحالات:**\n"
        response += f"├ 📊 عدد الإحالات: {len(referrals)}\n"
        response += f"└ 💰 إجمالي الأرباح: {total_commission:,.2f} ل.س\n"
        
        # جلب آخر العمليات
        history = db.get_user_history(user['bot_username'], days=30)
        if history:
            # حساب إجمالي الشحنات والسحوبات
            total_deposits = 0
            total_withdrawals = 0
            for record in history:
                if record['type'] == 'ايداع':
                    total_deposits += record['amount']
                elif record['type'] == 'سحب':
                    total_withdrawals += record['amount']
            
            response += f"\n📊 **إحصائيات العمليات:**\n"
            response += f"├ 💰 إجمالي الشحنات: {total_deposits:,.2f} ل.س\n"
            response += f"├ 💸 إجمالي السحوبات: {total_withdrawals:,.2f} ل.س\n"
            response += f"└ 📈 صافي الرصيد: {(total_deposits - total_withdrawals):,.2f} ل.س\n"
            
            response += f"\n📜 **آخر 10 عمليات:**\n"
            for i, record in enumerate(history[:10], 1):
                # تحديد الإيموجي حسب نوع العملية
                if record['type'] == 'ايداع':
                    emoji = "💰"
                elif record['type'] == 'سحب':
                    emoji = "💸"
                elif 'موقع' in record['type']:
                    emoji = "🌐"
                else:
                    emoji = "🎁"
                
                response += f"{i}. {emoji} **{record['type']}**\n"
                response += f"   └ 💵 {record['amount']:,.2f} ل.س - {record['method']}\n"
                response += f"   └ 📅 {record['created_at']}\n"
        else:
            response += f"\n📜 **العمليات:**\n"
            response += f"└ لا توجد عمليات مسجلة\n"
        
        # إضافة رابط الدعوة
        response += f"\n🔗 **رابط الدعوة:**\n"
        response += f"└ `https://t.me/{Config.BOT_USERNAME}?start={user['telegram_id']}`\n"
        
        # إضافة معرف المستخدم
        response += f"\n🆔 **معرفات سريعة:**\n"
        response += f"├ 🆔 معرف تليجرام: `{user['telegram_id']}`\n"
        response += f"└ 👤 معرف البوت: `{user['bot_username']}`"
        
        await context.bot.delete_message(
            chat_id=update.effective_user.id, 
            message_id=processing_msg.message_id
        )
        
        # تقسيم الرسالة إذا كانت طويلة جداً
        if len(response) > 4096:
            # تقسيم إلى أجزاء
            part1 = response[:4000]
            part2 = response[4000:8000] if len(response) > 8000 else response[4000:]
            
            await update.message.reply_text(part1, parse_mode='Markdown')
            if len(response) > 4000:
                await update.message.reply_text(part2, parse_mode='Markdown')
        else:
            await update.message.reply_text(response, parse_mode='Markdown')

# =============================================
# دالة بدء التشغيل الرئيسية
# =============================================
def main():
    # التحقق من الإعدادات
    Config.validate()
    Config.load_settings()

    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
     """معالجة الرسائل غير المعروفة"""
    # إذا كان في محادثة نشطة، لا تفعل شيء (المعالج الرئيسي سيتعامل)
     if context.user_data.get('conversation_active'):
        return
    # تجاهل الرسائل غير المعروفة للمستخدمين العاديين
     pass
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message), group=999)
    # === إضافة مهمة التقارير اليومية ===
    job_queue = application.job_queue
    if job_queue:
        # إرسال التقرير كل 24 ساعة
        job_queue.run_repeating(send_daily_report, interval=86400, first=10)
        logger.info("تم جدولة التقارير اليومية")
    
    # === معالج إنشاء حساب WayXBet ===
    wayxbet_register_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 إنشاء حساب$"), handle_wayxbet_register)],
        states={
            WayXBetConversationState.GET_WAYXBET_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_wayxbet_username)
            ],
            WayXBetConversationState.GET_WAYXBET_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_wayxbet_password)
            ]
        },
        fallbacks=[MessageHandler(filters.Regex("^(❌ إلغاء العملية|🏠 القائمة الرئيسية)$"), cancel_operation)],
        conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
    )
    
    # === معالج الشحن ===
    deposit_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^⬇️ الشحن في البوت$"), handle_deposit)],
    states={
        DepositConversationState.DEPOSIT_METHOD: [
            MessageHandler(filters.Regex("^💰 سيريتيل كاش$"), handle_seritel_cash_deposit),
            MessageHandler(filters.Regex(r"^💳 شام كاش \(ليرة سورية\)$"), handle_sham_cash_deposit),
            MessageHandler(filters.Regex(r"^💵 شام كاش \(دولار\)$"), handle_sham_cash_deposit),
            MessageHandler(filters.Regex("^USDT$"), handle_usdt_deposit),
            MessageHandler(filters.Regex("^🏠 القائمة الرئيسية$"), show_main_menu)
        ],
        DepositConversationState.SERITEL_CASH_TRANSACTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_seritel_transaction),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
        ],
        DepositConversationState.SERITEL_CASH_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_seritel_amount),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
        ],
        DepositConversationState.SERITEL_CASH_CODE: [  # ⬅️ أضف هذا القسم
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_seritel_code),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
        ],
        DepositConversationState.SHAM_CASH_TRANSACTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sham_transaction),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
        ],
        DepositConversationState.SHAM_CASH_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sham_amount),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
        ],
        DepositConversationState.USDT_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_usdt_amount),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
        ],
        DepositConversationState.USDT_TRANSACTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_usdt_transaction),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
        ]
    },
    fallbacks=[
        MessageHandler(filters.Regex("^(❌ إلغاء|🏠 القائمة الرئيسية)$"), cancel_operation),
        CommandHandler("cancel", cancel_operation)
    ],
    conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
)
    
    # === معالج السحب ===
    withdraw_handler = ConversationHandler(
     entry_points=[MessageHandler(filters.Regex("^⬆️ السحب من البوت$"), handle_withdraw)],
     states={
        WithdrawConversationState.WITHDRAW_METHOD: [
            MessageHandler(filters.Regex("^سيريتيل كاش$"), handle_seritel_withdraw),
            MessageHandler(filters.Regex("^شام كاش$"), handle_sham_withdraw),
            MessageHandler(filters.Regex("^USDT$"), handle_usdt_withdraw),
            MessageHandler(filters.Regex("^🏠 القائمة الرئيسية$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_SERITEL_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_seritel_withdraw_phone),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_SERITEL_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_seritel_withdraw_amount),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_SERITEL_CONFIRM: [
            MessageHandler(filters.Regex("^✅ تأكيد$"), handle_seritel_withdraw_confirm),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_SHAM_ACCOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sham_withdraw_account),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_SHAM_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sham_withdraw_amount),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_SHAM_CONFIRM: [
            MessageHandler(filters.Regex("^✅ تأكيد$"), handle_sham_withdraw_confirm),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_USDT_ADDRESS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_usdt_withdraw_address),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_USDT_NETWORK: [
            MessageHandler(filters.Regex("^(BEP20|TRC20)$"), handle_usdt_withdraw_network),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_USDT_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_usdt_withdraw_amount),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ],
        WithdrawConversationState.WITHDRAW_USDT_CONFIRM: [
            MessageHandler(filters.Regex("^✅ تأكيد$"), handle_usdt_withdraw_confirm),
            MessageHandler(filters.Regex("^❌ إلغاء$"), show_main_menu)
        ]
    },
     fallbacks=[
        MessageHandler(filters.Regex("^🏠 القائمة الرئيسية$"), show_main_menu),
        MessageHandler(filters.Regex("^(❌ إلغاء)$"), cancel_operation)
    ],
    conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
)
    
 
   
    
    # === معالج التعبئة في WayXBet ===
    wayxbet_deposit_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⬆️ التعبئة في حسابي$"), handle_wayxbet_deposit)],
        states={
            WayXBetTransferConversationState.WAYXBET_DEPOSIT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wayxbet_deposit_amount),
                MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
            ]
        },
        fallbacks=[MessageHandler(filters.Regex("^(❌ إلغاء|🏠 القائمة الرئيسية)$"), cancel_operation)],
        conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
    )
    
    # === معالج السحب من WayXBet ===
    wayxbet_withdraw_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^⬇️ السحب من حسابي$"), handle_wayxbet_withdraw)],
        states={
            WayXBetTransferConversationState.WAYXBET_WITHDRAW_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wayxbet_withdraw_amount),
                MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_operation)
            ]
        },
        fallbacks=[MessageHandler(filters.Regex("^(❌ إلغاء|🏠 القائمة الرئيسية)$"), cancel_operation)],
        conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
    )
    
    # === معالج استبدال كود الهدية ===
    voucher_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎁 استبدال كود هدية$"), handle_voucher_redemption)],
        states={
            VoucherConversationState.ENTER_VOUCHER_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_voucher_redemption)
            ]
        },
        fallbacks=[MessageHandler(filters.Regex("^(❌ إلغاء|🏠 القائمة الرئيسية)$"), cancel_operation)],
        conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
    )
    
    # === معالج استبدال كود البرومو ===
    promo_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎁 استبدال كود برومو$"), handle_promo_redemption)],
        states={
            VoucherConversationState.ENTER_VOUCHER_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_promo_redemption)
            ]
        },
        fallbacks=[MessageHandler(filters.Regex("^(❌ إلغاء|🏠 القائمة الرئيسية)$"), cancel_operation)],
        conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
    )
    
    # === معالج إهداء الرصيد ===
    gift_balance_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎁 إهداء رصيد$"), handle_gift_balance)],
        states={
            GiftBalanceConversationState.ENTER_RECEIVER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_gift_receiver)
            ],
            GiftBalanceConversationState.ENTER_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_gift_amount)
            ],
            GiftBalanceConversationState.CONFIRM_GIFT: [
                MessageHandler(filters.Regex("^(✅ تأكيد|❌ إلغاء)$"), confirm_gift_balance)
            ]
        },
        fallbacks=[MessageHandler(filters.Regex("^(❌ إلغاء|🏠 القائمة الرئيسية)$"), cancel_operation)],
        conversation_timeout=Config.USER_CONVERSATION_TIMEOUT
    )
    
    
    # === معالج لوحة الأدمن (تم دمج جميع عمليات الأدمن في محادثة واحدة) ===
    admin_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("admin", show_admin_panel),
            MessageHandler(filters.User(Config.ADMIN_IDS) & filters.Regex("^(👨‍💻 لوحة الأدمن|/admin)$"), show_admin_panel)
        ],
        states={
            AdminConversationState.ADMIN_MAIN: [
                MessageHandler(filters.Regex("^🔧 عمليات المستخدمين$"), admin_user_ops_menu),
                MessageHandler(filters.Regex("^💰 التدفقات المالية$"), admin_finance_menu),
                MessageHandler(filters.Regex("^🎁 الهدايا والعروض$"), admin_gifts_menu),
                MessageHandler(filters.Regex("^📢 بث رسالة جماعية$"), admin_broadcast),
                MessageHandler(filters.Regex("^🛠 تفعيل/تعطيل الصيانة$"), admin_toggle_maintenance),
                MessageHandler(filters.Regex("^🛠 حالة الصيانة$"), check_maintenance_status),
                MessageHandler(filters.Regex("^🏠 القائمة الرئيسية$"), show_main_menu),
                MessageHandler(filters.Regex("^📊 نسبة الإحالات$"), admin_commission_rate),
                MessageHandler(filters.Regex("^📡 إعدادات القنوات$"), admin_channels_menu)
            ],
            # === التدفقات المالية ===
            AdminConversationState.ADMIN_FINANCE: [
                MessageHandler(filters.Regex("^📥 الشحن$"), admin_deposit_ops),
                MessageHandler(filters.Regex("^📤 السحب$"), admin_withdraw_ops),
                MessageHandler(filters.Regex("^💰 معرفة رصيد محفظة الموقع$"), admin_view_wallet_balance),
                MessageHandler(filters.Regex("^💰 عرض اجمالي الحسابات$"), admin_view_total_accounts),
                MessageHandler(filters.Regex("^💱 تغيير سعر الدولار$"), admin_change_usd_rate),
                MessageHandler(filters.Regex("^💎 تغيير عناوين USDT$"), admin_change_usdt_addresses),
                MessageHandler(filters.Regex("^🏧 تغيير كود سيريتيل$"), admin_change_seritel),
                MessageHandler(filters.Regex("^🏧 تغيير حساب شام كاش$"), admin_change_sham),
                MessageHandler(filters.Regex("^🔙 رجوع$"), show_admin_panel)
            ],
            # === الشحن ===
            AdminConversationState.ADMIN_DEPOSIT_OPS: [
                MessageHandler(filters.Regex("^(⛔️ ايقاف الشحن كاملاً|✅ تشغيل الشحن كاملاً)$"), admin_toggle_all_deposits),
                MessageHandler(filters.Regex("^🎁 بونص الشحن$"), admin_bonus_menu),
                MessageHandler(filters.Regex("^🔙 رجوع$"), admin_finance_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_toggle_deposit_method)
            ],
            # === السحب ===
            AdminConversationState.ADMIN_WITHDRAW_OPS: [
                MessageHandler(filters.Regex("^(⛔️ ايقاف السحب كاملاً|✅ تشغيل السحب كاملاً)$"), admin_toggle_all_withdrawals),
                MessageHandler(filters.Regex("^📊 تغيير عمولة السحب$"), admin_change_commission_menu),
                MessageHandler(filters.Regex("^🔙 رجوع$"), admin_finance_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_toggle_withdraw_method)
            ],
            AdminConversationState.ADMIN_CHANGE_COMMISSION: [
                MessageHandler(filters.Regex("^🔙 رجوع$"), admin_withdraw_ops),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_change_commission)
            ],
            AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_finish_change_commission),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_change_commission_menu)
            ],
            # === البونص ===
            AdminConversationState.ADMIN_BONUS_METHOD: [
                MessageHandler(filters.Regex("^🔙 رجوع$"), admin_deposit_ops),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_bonus_method)
            ],
            AdminConversationState.ADMIN_BONUS_PERCENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_bonus_percent),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_bonus_menu)
            ],
            # === USDT وسعر الصرف ===
            AdminConversationState.ADMIN_CHANGE_USD_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_change_usd_rate),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_finance_menu)
            ],
            AdminConversationState.ADMIN_CHANGE_USDT_BEP20: [
                MessageHandler(filters.Regex("^🔙 رجوع$"), admin_finance_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_change_usdt)
            ],
            AdminConversationState.ADMIN_CHANGE_USDT_TRC20: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_usdt_address),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_change_usdt_addresses)
            ],
            # === سيريتيل وشام ===
            AdminConversationState.ADMIN_CHANGE_SERITEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_change_seritel),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_finance_menu)
            ],
            AdminConversationState.ADMIN_CHANGE_SERITEL_CONFIRM: [
                MessageHandler(filters.Regex("^(✅ تأكيد|❌ إلغاء)$"), admin_confirm_change_seritel)
            ],
            AdminConversationState.ADMIN_CHANGE_SHAM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_change_sham),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_finance_menu)
            ],
            AdminConversationState.ADMIN_CHANGE_SHAM_CONFIRM: [
                MessageHandler(filters.Regex("^(✅ تأكيد|❌ إلغاء)$"), admin_confirm_change_sham)
            ],
            # === عمليات المستخدمين ===
            AdminConversationState.ADMIN_USER_OPS: [
                MessageHandler(filters.Regex("^💰 تعديل رصيد مستخدم$"), admin_edit_user_balance),
                MessageHandler(filters.Regex("^📜 كشف سجل لاعب$"), admin_user_history),
                MessageHandler(filters.Regex("^🗑 حذف حساب لاعب$"), admin_delete_user),
                MessageHandler(filters.Regex("^🔗 ربط حساب لاعب$"), admin_link_account),
                MessageHandler(filters.Regex("^👥 الإحالات$"), admin_referrals_user),
                MessageHandler(filters.Regex("^🚫 حظر مستخدم$"), admin_ban_user),
                MessageHandler(filters.Regex("^📩 توجيه رسالة مخصصة$"), admin_send_custom_message),
                MessageHandler(filters.Regex("^📢 بث رسالة جماعية$"), admin_broadcast),
                MessageHandler(filters.Regex("^🔙 رجوع$"), show_admin_panel)
            ],
            AdminConversationState.ADMIN_EDIT_BALANCE_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_edit_balance)
            ],
            AdminConversationState.ADMIN_EDIT_BALANCE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_finish_edit_balance),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            AdminConversationState.ADMIN_USER_HISTORY_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_user_history_user),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            AdminConversationState.ADMIN_USER_HISTORY_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_user_history_days),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            AdminConversationState.ADMIN_DELETE_USER_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_delete_user),
                MessageHandler(filters.Regex("^(✅ تأكيد الحذف|❌ إلغاء)$"), admin_confirm_delete_user)
            ],
            AdminConversationState.ADMIN_LINK_ACCOUNT_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_link_user),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            AdminConversationState.ADMIN_LINK_ACCOUNT_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_link_id),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            AdminConversationState.ADMIN_LINK_ACCOUNT_CONFIRM: [
                MessageHandler(filters.Regex("^(✅ تأكيد الربط|✅ متابعة|❌ إلغاء)$"), admin_confirm_link_account)
            ],
            AdminConversationState.ADMIN_REFERRALS_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_referrals),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            AdminConversationState.ADMIN_BAN_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_ban_user),
                MessageHandler(filters.Regex("^(⛔️ حظر المستخدم|✅ إلغاء الحظر|❌ إلغاء)$"), admin_finish_ban_user)
            ],
            AdminConversationState.ADMIN_SEND_MESSAGE_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_custom_message),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            AdminConversationState.ADMIN_SEND_MESSAGE_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_finish_custom_message),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_user_ops_menu)
            ],
            # === الهدايا والعروض ===
            AdminConversationState.ADMIN_GIFTS: [
                MessageHandler(filters.Regex("^🎁 انشاء اكواد هدايا$"), admin_create_voucher),
                MessageHandler(filters.Regex("^🎫 انشاء كود برومو$"), admin_create_promo),
                MessageHandler(filters.Regex("^🔙 رجوع$"), show_admin_panel)
            ],
            AdminConversationState.ADMIN_CREATE_VOUCHER_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_voucher_amount),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_gifts_menu)
            ],
            AdminConversationState.ADMIN_CREATE_VOUCHER_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_finish_create_vouchers),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_gifts_menu)
            ],
            AdminConversationState.ADMIN_CREATE_PROMO_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_promo_amount),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_gifts_menu)
            ],
            AdminConversationState.ADMIN_CREATE_PROMO_USES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_finish_create_promo),
                MessageHandler(filters.Regex("^❌ إلغاء$"), admin_gifts_menu)
            ],
            # === البث والصيانة ===
            AdminConversationState.ADMIN_BROADCAST_MESSAGE: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, admin_handle_broadcast),
                MessageHandler(filters.Regex("^❌ إلغاء$"), show_admin_panel)
            ],
            AdminConversationState.ADMIN_MAINTENANCE_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_maintenance),
                MessageHandler(filters.Regex("^❌ إلغاء$"), show_admin_panel)
            ],
            
            # نسبة الإحالات
            AdminConversationState.ADMIN_CHANGE_COMMISSION_VALUE: [
               MessageHandler(filters.TEXT & ~filters.COMMAND, admin_handle_commission_rate_change),
               MessageHandler(filters.Regex("^🔙 رجوع$"), show_admin_panel)
            ],
        
        # إعدادات القنوات
           "CHANNELS_MENU": [
            MessageHandler(filters.Regex("^📢 قناة البوت"), admin_change_channel),
            MessageHandler(filters.Regex("^🔔 قناة الإشعارات"), admin_change_channel),
            MessageHandler(filters.Regex("^📊 قناة التقارير"), admin_change_channel),
            MessageHandler(filters.Regex("^⚠️ قناة الأخطاء"), admin_change_channel),
            MessageHandler(filters.Regex("^🔙 رجوع$"), show_admin_panel)
            ],
          "CHANGE_CHANNEL": [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_save_channel),
            MessageHandler(filters.Regex("^❌ إلغاء$"), admin_channels_menu)
            ],
  

    },
        fallbacks=[
            CommandHandler('cancel', show_admin_panel),
            MessageHandler(filters.Regex("^🔙 رجوع$"), show_admin_panel),
            MessageHandler(filters.Regex("^🏠 القائمة الرئيسية$"), show_main_menu)
        ],
        per_chat=True,
        per_user=True,
        conversation_timeout=Config.ADMIN_PANEL_TIMEOUT
    )
    
    
    # === تسجيل جميع المعالجات ===
    # معالجات Callback
    application.add_handler(CallbackQueryHandler(handle_deposit_approval, pattern=r"^(approve|reject)_deposit_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_withdraw_approval, pattern=r"^(approve|reject)_withdraw_\d+$"))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="check_subscription"))
    
    # معالجات المحادثات
    application.add_handler(admin_conv_handler)
    application.add_handler(wayxbet_register_handler)
    application.add_handler(deposit_handler)
    application.add_handler(withdraw_handler)
    application.add_handler(wayxbet_deposit_handler)
    application.add_handler(wayxbet_withdraw_handler)
    application.add_handler(voucher_handler)
    application.add_handler(promo_handler)
    application.add_handler(gift_balance_handler)
    
    # معالجات الأوامر
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", force_reset))
    application.add_handler(CommandHandler("admin", show_admin_panel))
    application.add_handler(CommandHandler("maintenance_status", check_maintenance_status, filters=filters.User(Config.ADMIN_IDS)))
    
    # معالجات القوائم العامة
    application.add_handler(MessageHandler(filters.User(Config.ADMIN_IDS) & filters.Regex("^👨‍💻 لوحة الأدمن$"), show_admin_panel))
    application.add_handler(MessageHandler(filters.Regex("^💰 الرصيد$"), show_balance))
    application.add_handler(MessageHandler(filters.Regex("^🤑 دعوة الأصدقاء$"), invite_friends))
    application.add_handler(MessageHandler(filters.Regex("^📩 التواصل مع الدعم$"), support))
    application.add_handler(MessageHandler(filters.Regex("^📜 الشروط والأحكام$"), show_terms))
    application.add_handler(MessageHandler(filters.Regex("^🏠 القائمة الرئيسية$"), show_main_menu))
    application.add_handler(MessageHandler(filters.Regex(f"^{Config.MAIN_SITE_NAME}$"), handle_wayxbet_menu))
    application.add_handler(MessageHandler(filters.Regex("^↩️ عودة$"), show_main_menu))
    application.add_handler(MessageHandler(filters.Regex("^ℹ️ معلومات الحساب$"), show_account_info))
    application.add_handler(MessageHandler(filters.FORWARDED & filters.User(Config.ADMIN_IDS), handle_forwarded_user_message))
    # أمر عرض سجل المستخدم للأدمن
    application.add_handler(CommandHandler("history", cmd_user_history, filters=filters.User(Config.ADMIN_IDS)))
    # بدء تشغيل البوت
    logger.info("🚀 بدء تشغيل البوت...")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()