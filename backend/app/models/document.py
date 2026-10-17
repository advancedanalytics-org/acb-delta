"""SQLAlchemy database models for documents and chunks."""

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(String(100), primary_key=True)
    code = Column(String(100), nullable=True)
    title = Column(Text, nullable=True)
    doc_type = Column(String(50), nullable=False, default="internal")  # "internal" | "vbpl"
    issuer = Column(String(255), nullable=True)
    effective_date = Column(String(50), nullable=True)
    page_count = Column(Integer, default=0)
    pdf_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    chunks = relationship(
        "DocumentChunkModel", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunkModel(Base):
    __tablename__ = "document_chunks"

    id = Column(String(150), primary_key=True)
    doc_id = Column(
        String(100), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_type = Column(String(50), nullable=False, default="internal", index=True)
    issuer = Column(String(255), nullable=True)
    effective_date = Column(String(50), nullable=True)
    article_path = Column(String(255), nullable=True, index=True)
    page = Column(Integer, nullable=False)
    bbox = Column(JSON, nullable=False)  # list of [x0, y0, x1, y1]
    text = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=True)
    chunk_metadata = Column("chunk_metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    document = relationship("DocumentModel", back_populates="chunks")
