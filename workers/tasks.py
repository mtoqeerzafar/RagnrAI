import os
from pathlib import Path
from workers.celery_app import celery_app
from storage.s3_client import s3_client
from document_processor.file_handler import DocumentProcessor
from db.database import SessionLocal
from db.models import DocumentJob
from utils.logging import logger

processor = DocumentProcessor()

@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, job_id: str, s3_key: str):
    db = SessionLocal()
    job = db.query(DocumentJob).filter(DocumentJob.id == job_id).first()
    
    if not job:
        logger.error(f"Job {job_id} not found.")
        db.close()
        return False
        
    job.status = "PROCESSING"
    db.commit()

    temp_dir = Path("/tmp/ragnr") if os.name != 'nt' else Path("C:/tmp/ragnr")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # We download the file to process locally
    local_file_path = temp_dir / s3_key
    
    try:
        # Download from S3
        success = s3_client.download_file(s3_key, str(local_file_path))
        if not success:
            raise Exception("Failed to download file from S3")
            
        # Process the file (Extract markdown and split into chunks)
        chunks = processor.process_single_file(local_file_path)
        
        # Aggressive memory cleanup after Docling (PyTorch based)
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        # Phase 2: Push chunks to Qdrant for Hybrid Search
        from db.qdrant_client import qdrant_manager
        
        if chunks:
            # We use fastembed integration in qdrant-client. 
            # We just need to extract text and metadata.
            texts = [chunk.page_content for chunk in chunks]
            
            # Attach tenant_id, thread_id, s3_key and document_id to each chunk's metadata
            metadatas = [
                {**chunk.metadata, "tenant_id": job.tenant_id, "thread_id": job.thread_id, "s3_key": s3_key, "document_id": job.id} 
                for chunk in chunks
            ]
            
            logger.info(f"Indexing {len(texts)} chunks to Qdrant with batch_size=4...")
            qdrant_manager.load_models()
            qdrant_manager.client.add(
                collection_name=qdrant_manager.collection_name,
                documents=texts,
                metadata=metadatas,
                batch_size=4  # Limit VRAM usage for FastEmbed
            )
        
        job.status = "COMPLETED"
        db.commit()
        
        # Bump the tenant_version in Redis to naturally invalidate cache
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            r = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            r.incr(f"tenant_version:{job.tenant_id}")
        except Exception as cache_err:
            logger.warning(f"Failed to bump tenant_version for {job.tenant_id}: {cache_err}")
            
        return True
        
    except Exception as e:
        logger.error(f"Task failed for job {job_id}: {str(e)}")
        job.status = "FAILED"
        job.error_message = str(e)
        db.commit()
        
        # Retry with exponential backoff if it's a transient issue
        raise self.retry(exc=e, countdown=2 ** self.request.retries)
        
    finally:
        db.close()
        # Cleanup temp file
        if local_file_path.exists():
            try:
                os.remove(local_file_path)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {local_file_path}: {e}")
