import os
from qdrant_client import QdrantClient
from qdrant_client.models import ScalarQuantization, ScalarQuantizationConfig, ScalarType
from utils.logging import logger
from dotenv import load_dotenv

load_dotenv()

class QdrantManager:
    def __init__(self):
        self.url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.collection_name = "ragnr_documents"
        self.semantic_cache_name = "semantic_cache"
        self._models_loaded = False
        
        # Connect to Qdrant using gRPC to avoid httpx zstd memory errors
        self.client = QdrantClient(url=self.url, prefer_grpc=True)
        self._ensure_collection()

    def load_models(self):
        if not self._models_loaded:
            logger.info("Loading FastEmbed models into System RAM...")
            providers = ["CPUExecutionProvider"]
                
            # Configure FastEmbed local models for Dense and Sparse embeddings
            self.client.set_model("BAAI/bge-small-en-v1.5", providers=providers)
            self.client.set_sparse_model("prithivida/Splade_PP_en_v1", providers=providers)
            self._models_loaded = True
            logger.info("Models loaded successfully.")

    def _ensure_collection(self):
        if not self.client.collection_exists(self.collection_name):
            logger.info(f"Creating Qdrant collection: {self.collection_name}")
            self.load_models()
            # Create collection with hybrid vectors configuration
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=self.client.get_fastembed_vector_params(),
                sparse_vectors_config=self.client.get_fastembed_sparse_vector_params(),
                quantization_config=ScalarQuantization(
                    scalar=ScalarQuantizationConfig(
                        type=ScalarType.INT8,
                        always_ram=True
                    )
                )
            )
            logger.info("Hybrid collection created successfully.")
            
        if not self.client.collection_exists(self.semantic_cache_name):
            logger.info(f"Creating Qdrant collection: {self.semantic_cache_name}")
            self.load_models()
            self.client.create_collection(
                collection_name=self.semantic_cache_name,
                vectors_config=self.client.get_fastembed_vector_params(),
                quantization_config=ScalarQuantization(
                    scalar=ScalarQuantizationConfig(
                        type=ScalarType.INT8,
                        always_ram=True
                    )
                )
            )
            logger.info("Semantic Cache collection created successfully.")

qdrant_manager = QdrantManager()
