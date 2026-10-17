"""Services package for chunking, embedding, storage, and vector store."""

from app.services.chunker import DocumentMetadata, PDFChunk, chunk_pdf, extract_metadata
from app.services.embedding import LangChainEmbeddingService
from app.services.storage import StorageService
from app.services.vector_store import LangChainPGVectorStore, init_db

EmbeddingService = LangChainEmbeddingService
VectorStore = LangChainPGVectorStore

__all__ = [
    "PDFChunk",
    "DocumentMetadata",
    "chunk_pdf",
    "extract_metadata",
    "LangChainEmbeddingService",
    "EmbeddingService",
    "StorageService",
    "LangChainPGVectorStore",
    "VectorStore",
    "init_db",
]
