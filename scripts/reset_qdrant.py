import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from db.qdrant_client import qdrant_manager

load_dotenv()

def reset_collections():
    client = qdrant_manager.client
    
    # Drop and recreate ragnr_documents
    if client.collection_exists(qdrant_manager.collection_name):
        print(f"Dropping collection: {qdrant_manager.collection_name}")
        client.delete_collection(qdrant_manager.collection_name)
        
    # Drop and recreate semantic_cache
    if client.collection_exists(qdrant_manager.semantic_cache_name):
        print(f"Dropping collection: {qdrant_manager.semantic_cache_name}")
        client.delete_collection(qdrant_manager.semantic_cache_name)
        
    # Trigger qdrant_manager to re-initialize them
    print("Re-creating collections with the new INT8 Scalar Quantization schemas...")
    qdrant_manager._ensure_collection()
    print("Reset complete!")

if __name__ == "__main__":
    reset_collections()
