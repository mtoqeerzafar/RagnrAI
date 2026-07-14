import hashlib
import redis.asyncio as redis
from typing import Optional
from utils.logging import cache_logger as logger
import os

class ExactCache:
    def __init__(self):
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        self.redis_client = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        self.ttl = 86400  # 24 hours

    def _generate_key(self, query: str, tenant_id: str, thread_id: str, version: str = "0") -> str:
        # Hash query to avoid extremely long keys and handle special chars
        query_hash = hashlib.sha256(query.encode('utf-8')).hexdigest()
        return f"exact_cache:{tenant_id}:{thread_id}:v{version}:{query_hash}"

    async def get_tenant_version(self, tenant_id: str) -> str:
        try:
            version = await self.redis_client.get(f"tenant_version:{tenant_id}")
            return version if version else "0"
        except Exception:
            return "0"

    async def check_cache(self, query: str, tenant_id: str, thread_id: str) -> Optional[str]:
        try:
            version = await self.get_tenant_version(tenant_id)
            key = self._generate_key(query, tenant_id, thread_id, version)
            answer = await self.redis_client.get(key)
            if answer:
                logger.info("Exact Cache HIT!")
                return answer
            return None
        except Exception as e:
            logger.warning(f"Exact cache search failed: {e}")
            return None

    async def set_cache(self, query: str, answer: str, tenant_id: str, thread_id: str):
        try:
            version = await self.get_tenant_version(tenant_id)
            key = self._generate_key(query, tenant_id, thread_id, version)
            await self.redis_client.set(key, answer, ex=self.ttl)
            logger.info("Saved verified answer to Exact Cache.")
        except Exception as e:
            logger.warning(f"Failed to set exact cache: {e}")

exact_cache_manager = ExactCache()
