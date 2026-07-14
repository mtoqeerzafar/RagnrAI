import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "ragnr_worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_CACHE_URL", "redis://localhost:6379/1"),
    include=['workers.tasks']
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)
