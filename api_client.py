# api_client.py
import httpx
import logging
from typing import Optional, Dict, Any
from datetime import datetime
import sqlite3

logger = logging.getLogger(__name__)

class SyriaAPIClient:
    """عميل للتعامل مع API-SYRIA للتحقق من عمليات سيريتيل كاش وشام كاش"""
    
    def __init__(self, api_key: str, base_url: str = "https://apisyria.com/api/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        await self.client.aclose()
    
    async def verify_seritel_transaction(self, cash_code: str, transaction_id: str) -> Dict[str, Any]:
        """
        التحقق من عملية سيريتيل كاش
        cash_code: كود التاجر (الرقم الذي تم التحويل إليه)
        transaction_id: رقم العملية المكون من 12 رقم
        """
        try:
            # إزالة أي مسافات أو أحرف غير رقمية
            transaction_id = ''.join(filter(str.isdigit, transaction_id))
            cash_code = ''.join(filter(str.isdigit, cash_code))
            
            response = await self.client.get(
                f"{self.base_url}",
                params={
                    "resource": "syriatel",
                    "action": "find_tx",
                    "cash_code": cash_code,
                    "gsm": transaction_id,  # رقم العملية يُرسل كـ gsm في الـ API
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
                return {
                    "success": True,
                    "found": True,
                    "amount": tx_data.get("transaction", {}).get("amount", 0),
                    "from_number": tx_data.get("transaction", {}).get("from", ""),
                    "to_code": cash_code,
                    "datetime": tx_data.get("transaction", {}).get("datetime", ""),
                    "raw": tx_data
                }
            else:
                return {"success": True, "found": False, "message": "لم يتم العثور على العملية"}
                
        except Exception as e:
            logger.error(f"خطأ في التحقق من سيريتيل: {e}")
            return {"success": False, "error": str(e)}
    
    async def verify_sham_transaction(self, account_address: str, transaction_id: str) -> Dict[str, Any]:
        """
        التحقق من عملية شام كاش
        account_address: عنوان حساب شام كاش (مثل 251aw******)
        transaction_id: رقم العملية
        """
        try:
            transaction_id = str(transaction_id).strip()
            
            response = await self.client.get(
                f"{self.base_url}",
                params={
                    "resource": "shamcash",
                    "action": "find_tx",
                    "tx": transaction_id,
                    "account_address": account_address,
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
                    "amount": transaction.get("amount", 0),
                    "currency": transaction.get("currency", "SYP"),  # SYP أو USD
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