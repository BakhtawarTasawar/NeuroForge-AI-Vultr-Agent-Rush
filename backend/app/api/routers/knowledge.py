import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.db.models import KnowledgeDocument, Project, User, UserRole
from app.schemas.models import (
    DocumentChunkResponse,
    KnowledgeCitation,
    KnowledgeDocumentCreateTextRequest,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.services.knowledge_service import KnowledgeIngestionError, KnowledgeService

logger = logging.getLogger("neuroforge.api.knowledge")

router = APIRouter(prefix="", tags=["Scientific Knowledge & Vector RAG"])

_knowledge_service = KnowledgeService()

MAX_KNOWLEDGE_DOC_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


def _check_project_access(project_id: str, user: User, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if user.role != UserRole.ADMIN.value and project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this project.")
    return project


@router.post(
    "/projects/{project_id}/knowledge/upload",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a scientific literature document (PDF, TXT, MD, JSON)",
)
async def upload_knowledge_document(
    project_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    source_type: Optional[str] = Form("upload"),
    doi: Optional[str] = Form(None),
    authors: Optional[str] = Form(None),
    publication_year: Optional[int] = Form(None),
    journal: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    custom_metadata: Optional[str] = Form(None),  # Optional JSON string of arbitrary metadata
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _check_project_access(project_id, current_user, db)

    content = await file.read(MAX_KNOWLEDGE_DOC_SIZE_BYTES + 1)
    if len(content) > MAX_KNOWLEDGE_DOC_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Knowledge document exceeds maximum allowed size of {MAX_KNOWLEDGE_DOC_SIZE_BYTES // (1024*1024)} MB.",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded document is empty.")

    doc_title = title.strip() if title and title.strip() else (file.filename or "Untitled Document")

    parsed_custom_metadata = None
    if custom_metadata and custom_metadata.strip():
        try:
            import json
            parsed_custom_metadata = json.loads(custom_metadata)
            if not isinstance(parsed_custom_metadata, dict):
                raise ValueError("custom_metadata must be a JSON dictionary.")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid custom_metadata JSON: {e}")

    try:
        doc = _knowledge_service.ingest_document(
            db=db,
            project_id=project.id,
            owner_id=current_user.id,
            title=doc_title,
            filename=file.filename or "document.txt",
            content=content,
            source_type=source_type or "upload",
            doi=doi,
            authors=authors,
            publication_year=publication_year,
            journal=journal,
            source_url=source_url,
            tags=tags,
            custom_metadata=parsed_custom_metadata,
        )
        return doc
    except KnowledgeIngestionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error ingesting knowledge document: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to ingest knowledge document.")


@router.post(
    "/projects/{project_id}/knowledge/text",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a scientific abstract, pathway description, or research notes",
)
def ingest_knowledge_text(
    project_id: str,
    payload: KnowledgeDocumentCreateTextRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _check_project_access(project_id, current_user, db)

    content_bytes = payload.content.encode("utf-8")
    filename = f"{payload.title.replace(' ', '_')[:32]}.txt"

    try:
        doc = _knowledge_service.ingest_document(
            db=db,
            project_id=project.id,
            owner_id=current_user.id,
            title=payload.title,
            filename=filename,
            content=content_bytes,
            source_type=payload.source_type or "abstract",
            doi=payload.doi,
            authors=payload.authors,
            publication_year=payload.publication_year,
            journal=payload.journal,
            source_url=payload.source_url,
            tags=payload.tags,
            custom_metadata=payload.custom_metadata,
        )
        return doc
    except KnowledgeIngestionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.error(f"Error ingesting knowledge text: {exc}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to ingest knowledge text.")


@router.get(
    "/projects/{project_id}/knowledge",
    response_model=List[KnowledgeDocumentResponse],
    summary="List all ingested scientific knowledge documents for a project",
)
def list_knowledge_documents(
    project_id: str,
    limit: Optional[int] = 50,
    offset: Optional[int] = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_project_access(project_id, current_user, db)
    docs = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.project_id == project_id)
        .order_by(KnowledgeDocument.created_at.desc())
        .offset(max(0, offset or 0))
        .limit(min(100, max(1, limit or 50)))
        .all()
    )
    return docs


@router.get(
    "/projects/{project_id}/knowledge/{document_id}",
    response_model=KnowledgeDocumentResponse,
    summary="Get details and chunks of a specific knowledge document",
)
def get_knowledge_document(
    project_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_project_access(project_id, current_user, db)
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.project_id == project_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found.")

    # Populate chunk response models
    chunk_responses = []
    for c in doc.chunks:
        chunk_responses.append(
            DocumentChunkResponse(
                id=c.id,
                document_id=c.document_id,
                project_id=c.project_id,
                chunk_index=c.chunk_index,
                chunk_text=c.chunk_text,
                token_count=c.token_count,
                metadata_json=c.metadata_json,
                created_at=c.created_at,
            )
        )
    resp = KnowledgeDocumentResponse.model_validate(doc)
    resp.chunks = chunk_responses
    return resp


@router.delete(
    "/projects/{project_id}/knowledge/{document_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a knowledge document and its indexed vectors",
)
def delete_knowledge_document(
    project_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_project_access(project_id, current_user, db)
    doc = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.project_id == project_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found.")

    deleted = _knowledge_service.delete_document(db, document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete document vectors.")

    return {"detail": "Knowledge document deleted successfully."}


@router.post(
    "/projects/{project_id}/knowledge/search",
    response_model=KnowledgeSearchResponse,
    summary="Execute semantic similarity search against project knowledge base",
)
def search_knowledge(
    project_id: str,
    payload: KnowledgeSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_project_access(project_id, current_user, db)

    citations = _knowledge_service.retrieve_context(
        db=db,
        project_id=project_id,
        query=payload.query,
        top_k=payload.top_k or 5,
        score_threshold=payload.score_threshold or 0.0,
    )

    citation_models = [KnowledgeCitation(**c) for c in citations]
    return KnowledgeSearchResponse(
        query=payload.query,
        project_id=project_id,
        total_results=len(citation_models),
        citations=citation_models,
    )
