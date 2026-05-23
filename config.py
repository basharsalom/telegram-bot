import os
from dotenv import load_dotenv


# تحميل المتغيرات من ملف .env
load_dotenv()

class Config:
    # === إعدادات البوت الأساسية ===
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    BOT_USERNAME = os.getenv("BOT_USERNAME")
    
    # === إعدادات القنوات ===
    CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
    NOTIFICATION_GROUP_USERNAME = os.getenv("NOTIFICATION_GROUP_USERNAME")
    REPORTS_CHANNEL_USERNAME = os.getenv("REPORTS_CHANNEL_USERNAME")
    ERRORS_CHANNEL_USERNAME = os.getenv("ERRORS_CHANNEL_USERNAME")
    
    # === إعدادات الأدمن ===
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
    
    # === إعدادات WayXBet API ===
    WAYXBET_USERNAME = os.getenv("WAYXBET_USERNAME")
    WAYXBET_PASSWORD = os.getenv("WAYXBET_PASSWORD")
    WAYXBET_BASE_URL = os.getenv("WAYXBET_BASE_URL")
    WAYXBET_SITE_NAME = os.getenv("WAYXBET_SITE_NAME")
    MAIN_SITE_NAME = os.getenv("MAIN_SITE_NAME")
    
    # === الإعدادات المالية ===
    COMMISSION_RATE = float(os.getenv("COMMISSION_RATE", "0.02"))
    
    SERITEL_WITHDRAW_COMMISSION = float(os.getenv("SERITEL_WITHDRAW_COMMISSION", "5"))
    SHAM_WITHDRAW_COMMISSION = float(os.getenv("SHAM_WITHDRAW_COMMISSION", "10"))
    USDT_WITHDRAW_COMMISSION = float(os.getenv("USDT_WITHDRAW_COMMISSION", "10"))
    
    SERITEL_MIN_WITHDRAW = float(os.getenv("SERITEL_MIN_WITHDRAW", "5"))
    SHAM_MIN_WITHDRAW = float(os.getenv("SHAM_MIN_WITHDRAW", "10"))
    USDT_MIN_WITHDRAW = float(os.getenv("USDT_MIN_WITHDRAW", "10"))
    
    USD_EXCHANGE_RATE = float(os.getenv("USD_EXCHANGE_RATE", "173"))
    
    # === إعدادات USDT ===
    USDT_BEP20_ADDRESS = os.getenv("USDT_BEP20_ADDRESS")
    USDT_TRC20_ADDRESS = os.getenv("USDT_TRC20_ADDRESS")
    
    # === مهلات المحادثة ===
    ADMIN_PANEL_TIMEOUT = int(os.getenv("ADMIN_PANEL_TIMEOUT", "86000"))
    USER_CONVERSATION_TIMEOUT = int(os.getenv("USER_CONVERSATION_TIMEOUT", "86000"))

    # === إعدادات API-SYRIA ===
    API_SYRIA_KEY = os.getenv("API_SYRIA_KEY")  # مفتاح API الذي اشتريته
    API_SYRIA_BASE_URL = os.getenv("API_SYRIA_BASE_URL", "https://apisyria.com/api/v1")
    
    @classmethod
    
    def validate(cls):
        """التحقق من وجود المتغيرات الإلزامية"""
        errors = []
        
        required_vars = [
            ('BOT_TOKEN', cls.BOT_TOKEN),
            ('CHANNEL_USERNAME', cls.CHANNEL_USERNAME),
            ('WAYXBET_USERNAME', cls.WAYXBET_USERNAME),
            ('WAYXBET_PASSWORD', cls.WAYXBET_PASSWORD),
            ('WAYXBET_BASE_URL', cls.WAYXBET_BASE_URL),
        ]
        
        for name, value in required_vars:
            if not value:
                errors.append(f"❌ {name} غير مضبوط في ملف .env")
        
        if errors:
            raise ValueError("\n".join(errors))
        
        print("✅ تم التحقق من الإعدادات بنجاح")

   
    @classmethod
    def save_setting(cls, key, value):
        """حفظ إعداد"""
        _settings.save(key, value)
        if hasattr(cls, key):
            setattr(cls, key, value)
    
    @classmethod
    def load_settings(cls):
        """تحميل الإعدادات المحفوظة"""
        dynamic_keys = [
            'USD_EXCHANGE_RATE',
            'USDT_BEP20_ADDRESS', 
            'USDT_TRC20_ADDRESS',
            'SERITEL_WITHDRAW_COMMISSION',
            'SHAM_WITHDRAW_COMMISSION',
            'USDT_WITHDRAW_COMMISSION',
            'SERITEL_MIN_WITHDRAW',
            'SHAM_MIN_WITHDRAW',
            'USDT_MIN_WITHDRAW'
        ]
        
        for key in dynamic_keys:
            value = _settings.load(key)
            if value is not None:
                if key == 'USD_EXCHANGE_RATE':
                    setattr(cls, key, float(value))
                elif 'COMMISSION' in key or 'MIN' in key:
                    setattr(cls, key, float(value))
                else:
                    setattr(cls, key, value)
# =============================================
# أضف هذا الكود في نهاية config.py
# =============================================

import sqlite3
from datetime import datetime

class _SettingsManager:
    """مدير الإعدادات الداخلي"""
    
    def __init__(self):
        self._init_db()
    
    def _init_db(self):
        try:
            self.conn = sqlite3.connect('bot.db', check_same_thread=False)
            self.conn.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP
            )
            ''')
            self.conn.commit()
        except Exception as e:
            print(f"⚠️ خطأ في تهيئة قاعدة الإعدادات: {e}")
            self.conn = None
    
    def save(self, key, value):
        if self.conn:
            try:
                self.conn.execute(
                    'INSERT OR REPLACE INTO bot_settings (key, value, updated_at) VALUES (?, ?, ?)',
                    (key, str(value), datetime.now())
                )
                self.conn.commit()
            except:
                pass
    
    def load(self, key, default=None):
        if self.conn:
            try:
                cursor = self.conn.execute('SELECT value FROM bot_settings WHERE key = ?', (key,))
                row = cursor.fetchone()
                return row[0] if row else default
            except:
                return default
        return default

# إنشاء كائن الإعدادات
_settings = _SettingsManager()

# ثم أضف دوال save و load داخل كلاس Config
# أضف هذا الكود داخل كلاس Config (قبل الإغلاق)