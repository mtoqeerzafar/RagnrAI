import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from config import constants
from config.settings import settings
from utils.logging import logger

class StructureAwareChunker:
    def __init__(self, source_name: str):
        self.source_name = source_name
        self.paragraph_batch_size = settings.PARAGRAPH_BATCH_SIZE
        self.max_table_rows_per_chunk = settings.MAX_TABLE_ROWS_PER_CHUNK
        self.table_row_batch_size = settings.TABLE_ROW_BATCH_SIZE

    def chunk_document(self, docling_doc) -> List[Document]:
        chunks = []
        current_block = []
        last_flushed_paragraph = ""

        current_meta = {
            "h1": None,
            "h2": None,
            "h3": None,
            "h4": None
        }

        def flush_paragraphs():
            nonlocal current_block, last_flushed_paragraph
            if current_block:
                para_text = "\n".join(current_block)
                chunks.append(self._build_chunk(para_text, current_meta.copy(), "paragraph"))
                last_flushed_paragraph = para_text
                current_block = []

        for item, level in docling_doc.iterate_items():
            
            # 1. Heading Management
            if item.label in ("section_header", "page_header", "title"):
                flush_paragraphs()
                last_flushed_paragraph = "" # Reset context on new heading
                text = item.text.strip()
                if level == 1:
                    current_meta["h1"] = text
                    current_meta["h2"] = None
                    current_meta["h3"] = None
                    current_meta["h4"] = None
                elif level == 2:
                    current_meta["h2"] = text
                    current_meta["h3"] = None
                    current_meta["h4"] = None
                elif level == 3:
                    current_meta["h3"] = text
                    current_meta["h4"] = None
                else:
                    current_meta["h4"] = text
                continue
                
            # 3. & 7. Table Processing & Defensive Handling
            if item.label == "table":
                flush_paragraphs()
                try:
                    table_md = item.export_to_markdown()
                    rows = table_md.strip().split('\n')
                    context_prefix = f"{last_flushed_paragraph}\n\n" if last_flushed_paragraph else ""
                    
                    if len(rows) <= self.max_table_rows_per_chunk:
                        chunks.append(self._build_chunk(context_prefix + table_md, current_meta.copy(), "table", getattr(item.prov[0], "page_no", None) if item.prov else None))
                    else:
                        header = rows[0:2]
                        body = rows[2:]
                        for i in range(0, len(body), self.table_row_batch_size):
                            batch = body[i:i + self.table_row_batch_size]
                            batch_md = "\n".join(header + batch)
                            chunks.append(self._build_chunk(context_prefix + batch_md, current_meta.copy(), "table", getattr(item.prov[0], "page_no", None) if item.prov else None))
                except Exception as e:
                    logger.warning(f"Failed to extract table structure, falling back to text: {e}")
                    context_prefix = f"{last_flushed_paragraph}\n\n" if last_flushed_paragraph else ""
                    chunks.append(self._build_chunk(context_prefix + item.text, current_meta.copy(), "table_fallback", getattr(item.prov[0], "page_no", None) if item.prov else None))
                continue

            # 5. List Processing
            if item.label == "list_item":
                flush_paragraphs()
                context_prefix = f"{last_flushed_paragraph}\n\n" if last_flushed_paragraph else ""
                chunks.append(self._build_chunk(context_prefix + item.text, current_meta.copy(), "list", getattr(item.prov[0], "page_no", None) if item.prov else None))
                continue

            # 4. & 6. Paragraph Processing & Unknown Element Fallback
            if hasattr(item, "text") and item.text:
                text = item.text.strip()
                if text:
                    current_block.append(text)
                
                if len(current_block) >= self.paragraph_batch_size:
                    flush_paragraphs()

        flush_paragraphs()
        return chunks

    def _build_chunk(self, text: str, meta: dict, chunk_type: str, page_no: int = None) -> Document:
        # 2. Breadcrumb Injection
        path = []
        for k in ["h1", "h2", "h3", "h4"]:
            if meta.get(k):
                path.append(meta[k])
                
        breadcrumb = "[Source: " + self.source_name + (" > " + " > ".join(path) if path else "") + "]"
        enriched_text = f"{breadcrumb}\n\n{text}"
        
        # 9. & 10. Metadata and Return Type
        metadata = {
            "source": self.source_name,
            "file_name": self.source_name,
            "chunk_type": chunk_type,
            "hierarchy": meta
        }
        if page_no:
            metadata["page"] = page_no
            
        return Document(
            page_content=enriched_text,
            metadata=metadata
        )

class DocumentProcessor:
    def __init__(self):
        self.cache_dir = Path(settings.CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.converter = None # Lazy loaded

    def _get_converter(self):
        if self.converter is None:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions, AcceleratorDevice
            
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = False
            pipeline_options.generate_page_images = False
            pipeline_options.accelerator_options = AcceleratorOptions(
                num_threads=2, device=AcceleratorDevice.CPU
            )
            
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
        return self.converter

    def process_single_file(self, file_path: Path) -> List[Document]:
        """Process a single file, typically downloaded from S3 by a Celery worker."""
        if not str(file_path).endswith(('.pdf', '.docx', '.txt', '.md')):
            logger.warning(f"Skipping unsupported file type: {file_path}")
            return []

        try:
            # Generate content-based hash for caching
            with open(file_path, "rb") as f:
                file_hash = self._generate_hash(f.read())
            
            cache_path = self.cache_dir / f"{file_hash}.json"
            
            if self._is_cache_valid(cache_path):
                logger.info(f"Loading from cache: {file_path.name}")
                chunks = self._load_from_cache(cache_path)
            else:
                logger.info(f"Processing and caching: {file_path.name}")
                
                # Extract Docling DOM
                converter = self._get_converter()
                docling_doc = converter.convert(file_path).document
                
                # Chunk using Custom Structure-Aware Chunker
                chunker = StructureAwareChunker(file_path.stem)
                chunks = chunker.chunk_document(docling_doc)
                
                # Sanitize Enterprise PII/PHI/Secrets
                try:
                    from security.guardrails.pii_guardrail import pii_guardrail
                    for chunk in chunks:
                        chunk.page_content = pii_guardrail.sanitize(chunk.page_content)
                except Exception as e:
                    logger.error(f"Failed to sanitize {file_path.name}: {e}")

                self._save_to_cache(chunks, cache_path)
            
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {str(e)}")
            raise e

    def _generate_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _save_to_cache(self, chunks: List[Document], cache_path: Path):
        # 2. Safer Cache Format (JSON instead of Pickle)
        data = {
            "timestamp": datetime.now().timestamp(),
            "chunks": [{"page_content": c.page_content, "metadata": c.metadata} for c in chunks]
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_cache(self, cache_path: Path) -> List[Document]:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [Document(page_content=c["page_content"], metadata=c["metadata"]) for c in data["chunks"]]

    def _is_cache_valid(self, cache_path: Path) -> bool:
        if not cache_path.exists():
            return False
            
        cache_age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        return cache_age < timedelta(days=settings.CACHE_EXPIRE_DAYS)