# api_client.py - متوافق مع API سوريا الجديد (يبحث في كل الفترات)
import httpx
import logging
from typing import Dict, Any
import sqlite3

logger = logging.getLogger(__name__)

class SyriaAPIClient:
    """عميل متوافق مع API-SYRIA (https://apisyria.com/api/v1)"""

    def __init__(self, api_key: str, base_url: str = "https://apisyria.com/api/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def verify_seritel_transaction(self, cash_code: str, transaction_id: str) -> Dict[str, Any]:
        """
        التحقق من عملية سيريتيل كاش باستخدام API الجديد
        cash_code: كود التاجر (الرقم الذي تم التحويل إليه)
        transaction_id: رقم العملية (12 رقم)
        """
        try:
            # تنظيف المدخلات
            transaction_id = ''.join(filter(str.isdigit, transaction_id))
            cash_code = ''.join(filter(str.isdigit, cash_code))

            # إرسال الطلب مع period=all للبحث في كل الفترات (لا يقتصر على أيام محددة)
            response = await self.client.get(
                self.base_url,
                params={
                    "resource": "syriatel",
                    "action": "find_tx",
                    "gsm": cash_code,
                    "tx": transaction_id,
                    "period": "all",          # البحث في كل العمليات (بدون حدود زمنية)
                    "api_key": self.api_key
                }
            )

            if response.status_code != 200:
                return {"success": False, "error": f"خطأ في الاتصال: {response.status_code}"}

            data = response.json()

            if not data.get("success"):
                return {"success": False, "error": data.get("error", "فشل التحقق من العملية")}

            tx_data = data.get("data", {})
            if tx_data.get("found"):
                transaction = tx_data.get("transaction", {})
                return {
                    "success": True,
                    "found": True,
                    "amount": float(transaction.get("amount", 0)),
                    "from_number": transaction.get("from", ""),
                    "to_code": cash_code,
                    "datetime": transaction.get("date", transaction.get("datetime", "")),
                    "raw": tx_data
                }
            else:
                return {"success": True, "found": False, "message": "لم يتم العثور على العملية"}

        except Exception as e:
            logger.error(f"خطأ في التحقق من سيريتيل: {e}")
            return {"success": False, "error": str(e)}

    async def verify_sham_transaction(self, account_address: str, transaction_id: str) -> Dict[str, Any]:
        """
        التحقق من عملية شام كاش باستخدام API الجديد
        account_address: عنوان حساب شام كاش (الذي استلم التحويل)
        transaction_id: رقم العملية
        """
        try:
            transaction_id = str(transaction_id).strip()

            response = await self.client.get(
                self.base_url,
                params={
                    "resource": "shamcash",
                    "action": "find_tx",
                    "account_address": account_address,
                    "tx": transaction_id,
                    "api_key": self.api_key
                }
            )

            if response.status_code != 200:
                return {"success": False, "error": f"خطأ في الاتصال: {response.status_code}"}

            data = response.json()

            if not data.get("success"):
                return {"success": False, "error": data.get("error", "فشل التحقق من العملية")}

            tx_data = data.get("data", {})
            if tx_data.get("found"):
                transaction = tx_data.get("transaction", {})
                return {
                    "success": True,
                    "found": True,
                    "amount": float(transaction.get("amount", 0)),
                    "currency": transaction.get("currency", "SYP"),
                    "from_name": transaction.get("from_name", ""),
                    "to_name": transaction.get("to_name", ""),
                    "datetime": transaction.get("datetime", ""),
                    "raw": tx_data
                }
            else:
                return {"success": True, "found": False, "message": "لم يتم العثور على العملية"}

        except Exception as e:
            logger.error(f"خطأ في التحقق من شام كاش: {e}")
            return {"success": False, "error": str(e)}

    async def check_transaction_used(self, transaction_id: str, method: str, db_conn) -> bool:
        """التحقق من أن رقم العملية لم يُستخدم من قبل"""
        try:
            cursor = db_conn.execute('''
                SELECT 1 FROM deposit_requests 
                WHERE transaction_id = ? AND method = ? AND status IN ('approved', 'pending')
            ''', (transaction_id, method))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"خطأ في التحقق من استخدام العملية: {e}")
            return False