import hashlib
import io
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DocumentChunk, KnowledgeDocument, Project, generate_uuid, utc_now
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

logger = logging.getLogger("neuroforge.knowledge_service")


class KnowledgeIngestionError(Exception):
    """Raised when scientific document parsing or embedding fails."""
    pass


class ScientificTextExtractor:
    """Extract clean, normalized textual content from scientific document formats."""

    @staticmethod
    def extract_text(content: bytes, filename: str) -> str:
        ext = Path(filename).suffix.lower()

        if ext == ".pdf":
            return ScientificTextExtractor._extract_pdf(content)
        elif ext in [".txt", ".md", ".csv", ".tsv"]:
            return ScientificTextExtractor._extract_plain_text(content)
        elif ext == ".json":
            return ScientificTextExtractor._extract_json(content)
        else:
            # Fallback to plain text attempt
            return ScientificTextExtractor._extract_plain_text(content)

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(f"--- Page {i + 1} ---\n{text.strip()}")
            combined = "\n\n".join(pages_text).strip()
            if not combined:
                raise KnowledgeIngestionError("No readable text found in PDF document.")
            return combined
        except Exception as e:
            if isinstance(e, KnowledgeIngestionError):
                raise
            raise KnowledgeIngestionError(f"Failed to parse PDF document: {str(e)}")

    @staticmethod
    def _extract_plain_text(content: bytes) -> str:
        # Try UTF-8 with fallback
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                text = content.decode(encoding).strip()
                if text:
                    return text
            except UnicodeDecodeError:
                continue
        # Fallback with error replacement
        return content.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _extract_json(content: bytes) -> str:
        try:
            data = json.loads(content.decode("utf-8", errors="replace"))
            extracted_parts = []

            def _recurse_extract(obj: Any, prefix: str = ""):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        _recurse_extract(v, f"{prefix} {k}" if prefix else k)
                elif isinstance(obj, list):
                    for item in obj:
                        _recurse_extract(item, prefix)
                elif isinstance(obj, str) and len(obj.strip()) > 3:
                    extracted_parts.append(f"{prefix}: {obj.strip()}" if prefix else obj.strip())

            _recurse_extract(data)
            return "\n\n".join(extracted_parts).strip()
        except Exception as e:
            raise KnowledgeIngestionError(f"Failed to parse JSON scientific knowledge: {str(e)}")


class ScientificTextChunker:
    """Sliding-window chunker with sentence and paragraph boundary preservation."""

    @staticmethod
    def chunk_text(
        text: str,
        chunk_size: int = 700,
        chunk_overlap: int = 120,
    ) -> List[Dict[str, Any]]:
        if not text or not text.strip():
            return []

        cleaned_text = re.sub(r"\r\n|\r", "\n", text)
        paragraphs = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]

        chunks: List[Dict[str, Any]] = []
        current_buffer = ""
        chunk_index = 0

        for para in paragraphs:
            # If paragraph itself is larger than chunk_size, split by sentences
            if len(para) > chunk_size:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    if len(current_buffer) + len(sent) + 1 <= chunk_size:
                        current_buffer = f"{current_buffer} {sent}".strip()
                    else:
                        if current_buffer:
                            chunks.append({
                                "chunk_index": chunk_index,
                                "chunk_text": current_buffer,
                                "token_count": int(len(current_buffer.split()) * 1.3),
                            })
                            chunk_index += 1
                            # Retain overlap from end of previous buffer
                            overlap_start = max(0, len(current_buffer) - chunk_overlap)
                            current_buffer = f"{current_buffer[overlap_start:]} {sent}".strip()
                        else:
                            current_buffer = sent
            else:
                if len(current_buffer) + len(para) + 2 <= chunk_size:
                    current_buffer = f"{current_buffer}\n\n{para}".strip()
                else:
                    if current_buffer:
                        chunks.append({
                            "chunk_index": chunk_index,
                            "chunk_text": current_buffer,
                            "token_count": int(len(current_buffer.split()) * 1.3),
                        })
                        chunk_index += 1
                        overlap_start = max(0, len(current_buffer) - chunk_overlap)
                        current_buffer = f"{current_buffer[overlap_start:]}\n\n{para}".strip()
                    else:
                        current_buffer = para

        if current_buffer.strip():
            chunks.append({
                "chunk_index": chunk_index,
                "chunk_text": current_buffer.strip(),
                "token_count": int(len(current_buffer.split()) * 1.3),
            })

        return chunks


class KnowledgeService:
    """
    High-level facade coordinating document extraction, chunking, embedding,
    relational persistence, and vector indexing for Project-isolated RAG.
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStore] = None,
    ):
        self.embedding_service = embedding_service or EmbeddingService()
        self.vector_store = vector_store or VectorStore()

    def ingest_document(
        self,
        db: Session,
        project_id: str,
        owner_id: str,
        title: str,
        filename: str,
        content: bytes,
        source_type: str = "upload",
        doi: Optional[str] = None,
        authors: Optional[str] = None,
        publication_year: Optional[int] = None,
        journal: Optional[str] = None,
        source_url: Optional[str] = None,
        tags: Optional[str] = None,
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeDocument:
        """
        Ingest a scientific knowledge document into PostgreSQL and persistent vector store.
        Calculates SHA-256, chunks text, generates embeddings, and saves atomically.
        """
        # Validate project exists
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project '{project_id}' not found.")

        # Compute hash
        content_hash = hashlib.sha256(content).hexdigest()

        # Extract text
        raw_text = ScientificTextExtractor.extract_text(content, filename)
        if not raw_text or len(raw_text.strip()) < 10:
            raise KnowledgeIngestionError("Document contains insufficient extractable text.")

        # Chunk text
        chunks_data = ScientificTextChunker.chunk_text(raw_text)
        if not chunks_data:
            raise KnowledgeIngestionError("No valid chunks could be formed from the document.")

        # Generate embeddings
        chunk_texts = [c["chunk_text"] for c in chunks_data]
        embeddings = self.embedding_service.generate_embeddings(chunk_texts)

        # Detect format
        ext = Path(filename).suffix.lstrip(".").upper() or "TXT"

        custom_meta_str = json.dumps(custom_metadata) if custom_metadata else None

        # Relational Record in PostgreSQL
        doc = KnowledgeDocument(
            project_id=project_id,
            owner_id=owner_id,
            title=title.strip() or filename,
            filename=filename,
            file_format=ext,
            file_size_bytes=len(content),
            content_hash=content_hash,
            chunk_count=len(chunks_data),
            source_type=source_type,
            doi=doi.strip() if doi and doi.strip() else None,
            authors=authors.strip() if authors and authors.strip() else None,
            publication_year=publication_year,
            journal=journal.strip() if journal and journal.strip() else None,
            source_url=source_url.strip() if source_url and source_url.strip() else None,
            tags=tags.strip() if tags and tags.strip() else None,
            custom_metadata=custom_meta_str,
        )
        db.add(doc)
        db.flush()  # Generates doc.id

        vector_tuples: List[Tuple[Any, ...]] = []

        for i, chunk_info in enumerate(chunks_data):
            chunk_id = generate_uuid()
            emb_vector = embeddings[i]
            meta_dict = {
                "document_title": doc.title,
                "source_filename": doc.filename,
                "chunk_index": chunk_info["chunk_index"],
                "source_type": source_type,
                "doi": doc.doi,
                "authors": doc.authors,
                "publication_year": doc.publication_year,
                "journal": doc.journal,
                "source_url": doc.source_url,
                "tags": doc.tags,
            }
            if custom_metadata:
                meta_dict["custom_metadata"] = custom_metadata

            db_chunk = DocumentChunk(
                id=chunk_id,
                document_id=doc.id,
                project_id=project_id,
                chunk_index=chunk_info["chunk_index"],
                chunk_text=chunk_info["chunk_text"],
                token_count=chunk_info["token_count"],
                embedding_json=json.dumps(emb_vector),
                metadata_json=json.dumps(meta_dict),
            )
            db.add(db_chunk)

            # Extra payload fields for Qdrant payload filtering and citations
            qdrant_payload = {
                "document_title": doc.title,
                "source_filename": doc.filename,
                "source_type": source_type,
                "doi": doc.doi or "",
                "authors": doc.authors or "",
                "publication_year": doc.publication_year or 0,
                "journal": doc.journal or "",
                "tags": doc.tags or "",
            }
            vector_tuples.append((chunk_id, project_id, doc.id, emb_vector, qdrant_payload))

        try:
            db.commit()
            db.refresh(doc)
            # Sync to persistent vector index
            self.vector_store.upsert_chunks(vector_tuples)
            logger.info(f"Ingested knowledge document '{doc.title}' ({len(chunks_data)} chunks) for project '{project_id}'.")
            return doc
        except Exception as exc:
            db.rollback()
            logger.error(f"Failed to ingest knowledge document: {exc}")
            raise

    def retrieve_context(
        self,
        db: Session,
        project_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.25,
    ) -> List[Dict[str, Any]]:
        """
        Execute semantic similarity retrieval strictly scoped to project_id.
        Returns a list of structured citation dictionaries.
        """
        if not query or not query.strip():
            return []

        # Generate query vector
        query_vector = self.embedding_service.generate_single_embedding(query.strip())

        # Vector search in local store
        ranked_matches = self.vector_store.search(
            project_id=project_id,
            query_vector=query_vector,
            top_k=top_k,
            score_threshold=score_threshold,
        )

        if not ranked_matches:
            return []

        chunk_ids = [m[0] for m in ranked_matches]
        scores_by_id = {m[0]: m[1] for m in ranked_matches}

        # Fetch chunk details from relational DB
        chunks = (
            db.query(DocumentChunk, KnowledgeDocument)
            .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
            .filter(DocumentChunk.id.in_(chunk_ids))
            .filter(DocumentChunk.project_id == project_id)  # Multi-tenant isolation verification
            .all()
        )

        citations: List[Dict[str, Any]] = []
        for chunk, doc in chunks:
            score = scores_by_id.get(chunk.id, 0.0)
            meta = json.loads(chunk.metadata_json) if chunk.metadata_json else {}
            citations.append({
                "chunk_id": chunk.id,
                "document_id": doc.id,
                "document_title": doc.title,
                "source_filename": doc.filename,
                "chunk_index": chunk.chunk_index,
                "relevance_score": score,
                "chunk_text": chunk.chunk_text,
                "metadata": meta,
            })

        # Sort by relevance descending
        citations.sort(key=lambda x: x["relevance_score"], reverse=True)
        return citations

    def delete_document(self, db: Session, document_id: str) -> bool:
        """Delete document, its chunks from DB, and its indexed vectors."""
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if not doc:
            return False

        # Remove vectors
        self.vector_store.delete_document_chunks(document_id)

        # Remove from DB (cascade removes chunks)
        db.delete(doc)
        db.commit()
        logger.info(f"Deleted knowledge document '{document_id}' and associated vectors.")
        return True
