from loguru import logger

import os
from loguru import logger

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

# Main app log (everything else)
logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    filter=lambda record: "log_type" not in record["extra"]
)

# Retrieval specific log
logger.add(
    "logs/retrieval.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    filter=lambda record: record["extra"].get("log_type") == "retrieval"
)

# Workflow specific log
logger.add(
    "logs/workflow.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    filter=lambda record: record["extra"].get("log_type") == "workflow"
)

# Cache specific log
logger.add(
    "logs/cache.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    filter=lambda record: record["extra"].get("log_type") == "cache"
)

# Performance specific log
logger.add(
    "logs/performance.log",
    rotation="10 MB",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    filter=lambda record: record["extra"].get("log_type") == "performance"
)

# Export bound loggers for ease of use
retrieval_logger = logger.bind(log_type="retrieval")
workflow_logger = logger.bind(log_type="workflow")
cache_logger = logger.bind(log_type="cache")
performance_logger = logger.bind(log_type="performance")