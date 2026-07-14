import os
import shutil
from pathlib import Path
import boto3
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import redis

# Load environment variables
load_dotenv("d:/RagnrAI/.env")

print("1. Clearing Local Cache...")
cache_dir = Path("d:/RagnrAI/document_cache")
if cache_dir.exists():
    for item in cache_dir.glob("*"):
        if item.is_file():
            item.unlink()
print("Local cache cleared.")

print("2. Clearing PostgreSQL...")
try:
    import psycopg
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        db_url = db_url.replace("+psycopg2", "").replace("+psycopg", "")
        
    with psycopg.connect(db_url, autocommit=True) as conn:
        print("Terminating other database connections to release locks...")
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();")
        conn.execute("TRUNCATE TABLE document_jobs, chat_messages, chat_threads, uploaded_documents CASCADE;")
        try:
            conn.execute("TRUNCATE TABLE checkpoints, checkpoint_writes, checkpoint_blobs CASCADE;")
        except Exception as e:
            print(f"Note: Could not truncate LangGraph checkpoints (may not exist yet): {e}")
    print("PostgreSQL cleared.")
except Exception as e:
    print(f"PostgreSQL clear error: {e}")

print("3. Clearing Qdrant...")
try:
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    q_client = QdrantClient(url=qdrant_url)
    collection_name = "ragnr_documents"
    if q_client.collection_exists(collection_name):
        q_client.delete_collection(collection_name)
        print("Qdrant collection deleted.")
        
        # Recreate it using fastembed settings so it's ready
        q_client.set_model("BAAI/bge-small-en-v1.5")
        q_client.set_sparse_model("prithivida/Splade_PP_en_v1")
        q_client.create_collection(
            collection_name=collection_name,
            vectors_config=q_client.get_fastembed_vector_params(),
            sparse_vectors_config=q_client.get_fastembed_sparse_vector_params()
        )
        print("Qdrant collection recreated.")
        print("Qdrant collection recreated.")
    else:
        print("Qdrant collection didn't exist.")
        
    semantic_cache_name = "semantic_cache"
    if q_client.collection_exists(semantic_cache_name):
        q_client.delete_collection(semantic_cache_name)
        print("Qdrant semantic cache deleted.")
        q_client.create_collection(
            collection_name=semantic_cache_name,
            vectors_config=q_client.get_fastembed_vector_params(),
            sparse_vectors_config=q_client.get_fastembed_sparse_vector_params()
        )
        print("Qdrant semantic cache recreated.")
except Exception as e:
    print(f"Qdrant clear error: {e}")

print("4. Clearing MinIO (Storage)...")
try:
    s3 = boto3.client(
        's3',
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION")
    )
    bucket = os.getenv("S3_BUCKET_NAME", "ragnr-documents")
    objects = s3.list_objects_v2(Bucket=bucket)
    if 'Contents' in objects:
        for obj in objects['Contents']:
            s3.delete_object(Bucket=bucket, Key=obj['Key'])
    print("MinIO cleared.")
except Exception as e:
    print(f"MinIO clear error (might be empty already): {e}")

print("5. Clearing Redis Cache...")
try:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(redis_url)
    r.flushall()
    print("Redis cleared.")
except Exception as e:
    print(f"Redis clear error: {e}")

print("All systems reset successfully!")
