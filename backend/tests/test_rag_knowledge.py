import io
import json
import os
import pytest
from sqlalchemy.orm import Session
from qdrant_client import QdrantClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.db.models import Dataset, KnowledgeDocument, Project, ResearchSession, SessionStatus, User, UserRole
from app.services.embedding_service import EmbeddingService
from app.services.knowledge_service import (
    KnowledgeIngestionError,
    KnowledgeService,
    ScientificTextChunker,
    ScientificTextExtractor,
)
from app.services.research_graph import (
    AutonomousResearchRunner,
    ResearchState,
    initialize_research_node,
    retrieve_scientific_knowledge_node,
    generate_research_plan_node,
    generate_research_summary_node,
)
from app.services.vector_store import VectorStore, _to_point_id
from app.services.vultr_inference import InferenceResponse, VultrInferenceService


@pytest.fixture
def memory_vector_store():
    """Provides an isolated in-memory Qdrant vector store fixture for tests."""
    store = VectorStore(location=":memory:", dimension=2560)
    yield store
    try:
        store.client.close()
    except Exception:
        pass


def test_text_extraction_formats():
    """Verify clean text extraction across TXT, MD, and JSON."""
    txt_content = b"BRCA1 is a human tumor suppressor gene that maintains genomic stability."
    extracted_txt = ScientificTextExtractor.extract_text(txt_content, "paper.txt")
    assert "BRCA1 is a human tumor suppressor" in extracted_txt

    md_content = b"# TP53 Pathway\n\nTP53 regulates cellular senescence and apoptosis."
    extracted_md = ScientificTextExtractor.extract_text(md_content, "notes.md")
    assert "TP53 regulates cellular senescence" in extracted_md

    json_content = json.dumps({
        "title": "Oncogenic KRAS Signaling",
        "abstract": "Activating mutations in KRAS drive persistent MAPK signaling.",
    }).encode("utf-8")
    extracted_json = ScientificTextExtractor.extract_text(json_content, "abstract.json")
    assert "Activating mutations in KRAS" in extracted_json


def test_pdf_extraction():
    """Verify PDF parsing and page-by-page text extraction using pypdf."""
    import pypdf
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=72 * 8.5, height=72 * 11)

    pdf_bytes_io = io.BytesIO()
    writer.write(pdf_bytes_io)
    pdf_bytes = pdf_bytes_io.getvalue()

    with pytest.raises(KnowledgeIngestionError, match="No readable text"):
        ScientificTextExtractor.extract_text(pdf_bytes, "blank.pdf")


def test_chunking_sliding_window():
    """Verify sentence-preserving sliding window chunker."""
    text = (
        "Cell cycle regulation is tightly controlled by cyclins and cyclin-dependent kinases. "
        "Dysregulation of CDK4 and CDK6 promotes uncontrolled proliferation in luminal breast cancer. "
        "CDK4/6 inhibitors such as palbociclib induce G1 arrest. "
        "Resistance mechanisms include RB1 loss, CCNE1 amplification, and FGFR pathway activation."
    )
    chunks = ScientificTextChunker.chunk_text(text, chunk_size=120, chunk_overlap=30)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c["chunk_text"]) > 0
        assert c["token_count"] > 0
        assert "chunk_index" in c


def test_embedding_service_deterministic():
    """Verify deterministic unit-normalized embedding generation in mock/test mode."""
    svc = EmbeddingService(mock_mode=True, dimension=2560)
    vec1 = svc.generate_single_embedding("BRCA1 DNA repair pathway")
    vec2 = svc.generate_single_embedding("BRCA1 DNA repair pathway")
    vec3 = svc.generate_single_embedding("Astronomy and planetary motion")

    assert len(vec1) == 2560
    assert vec1 == vec2  # Exact reproducibility
    assert vec1 != vec3  # Semantic distinctness

    import numpy as np
    norm = np.linalg.norm(np.array(vec1, dtype=np.float32))
    assert 0.99 <= norm <= 1.01  # Unit normalized


def test_vultr_embedding_production_enforcement(monkeypatch):
    """
    Verify that in production (or when ALLOW_MOCK_EMBEDDINGS is False),
    missing Vultr credentials or failed Vultr API calls RAISE an explicit error
    and NEVER silently fall back to mock/deterministic embeddings.
    """
    monkeypatch.setattr(settings, "ALLOW_MOCK_EMBEDDINGS", False)
    monkeypatch.setattr(settings, "APP_ENV", "production")

    # 1. Unconfigured API key raises RuntimeError
    svc_no_key = EmbeddingService(api_key="", mock_mode=False)
    with pytest.raises(RuntimeError, match="Vultr embedding service is unconfigured"):
        svc_no_key.generate_embeddings(["BRCA1"])

    # 2. Failed API call raises RuntimeError
    svc_bad_key = EmbeddingService(api_key="invalid-key-xyz", mock_mode=False)
    with pytest.raises(RuntimeError, match="Vultr embedding service failed"):
        svc_bad_key.generate_embeddings(["BRCA1"])


def test_qdrant_point_id_conversion():
    """Verify UUID and non-UUID string IDs are converted to valid Qdrant point UUIDs."""
    valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert _to_point_id(valid_uuid) == valid_uuid

    custom_id = "chunk_a1"
    converted = _to_point_id(custom_id)
    assert converted != custom_id
    import uuid
    assert str(uuid.UUID(converted)) == converted  # Must be a valid UUID string


def test_vector_store_project_isolation(memory_vector_store):
    """Verify Qdrant vector storage enforces strict project isolation."""
    store = memory_vector_store
    svc = EmbeddingService(mock_mode=True, dimension=2560)

    proj_a = "proj_alpha_qdrant"
    proj_b = "proj_beta_qdrant"

    vec_brca = svc.generate_single_embedding("BRCA1 DNA double strand break repair")
    vec_egfr = svc.generate_single_embedding("EGFR tyrosine kinase receptor signaling")
    vec_astro = svc.generate_single_embedding("Galactic cosmology and stellar evolution")

    # Ingest into Project A
    store.upsert_chunks([
        ("chunk_a1", proj_a, "doc_a", vec_brca),
        ("chunk_a2", proj_a, "doc_a", vec_egfr),
    ])

    # Ingest into Project B
    store.upsert_chunks([
        ("chunk_b1", proj_b, "doc_b", vec_astro),
    ])

    assert store.count_project_chunks(proj_a) == 2
    assert store.count_project_chunks(proj_b) == 1

    # Query Project A for BRCA
    results_a = store.search(project_id=proj_a, query_vector=vec_brca, top_k=5)
    matched_ids_a = [r[0] for r in results_a]
    assert "chunk_a1" in matched_ids_a
    assert "chunk_b1" not in matched_ids_a  # Project B must NEVER leak into Project A

    # Query Project B for BRCA -> should only search Project B chunks
    results_b = store.search(project_id=proj_b, query_vector=vec_brca, top_k=5)
    matched_ids_b = [r[0] for r in results_b]
    assert "chunk_a1" not in matched_ids_b
    assert "chunk_a2" not in matched_ids_b

    # Delete Document A from Qdrant
    deleted_count = store.delete_document_chunks("doc_a")
    assert deleted_count == 2
    assert store.count_project_chunks(proj_a) == 0


def test_knowledge_service_ingestion_and_retrieval(db_session: Session, memory_vector_store):
    """Verify end-to-end ingestion, chunking, and semantic context retrieval via Qdrant."""
    store = memory_vector_store
    emb_svc = EmbeddingService(mock_mode=True, dimension=2560)
    ks = KnowledgeService(embedding_service=emb_svc, vector_store=store)

    user = User(
        email="researcher_rag_qdrant@neuroforge.org",
        hashed_password=get_password_hash("SecretPass123"),
        full_name="Dr. RAG Investigator",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    project = Project(
        title="Ovarian Cancer Genomic Screening",
        domain="Cancer Gene-Expression",
        owner_id=user.id,
    )
    db_session.add(project)
    db_session.commit()

    paper_text = (
        "BRCA1 and BRCA2 are tumor suppressor genes that play critical roles in homologous recombination repair. "
        "Patients with deleterious germline BRCA1 mutations exhibit elevated susceptibility to high-grade serous ovarian cancer. "
        "PARP inhibitors exploit synthetic lethality in homologous recombination-deficient tumors."
    ).encode("utf-8")

    doc = ks.ingest_document(
        db=db_session,
        project_id=project.id,
        owner_id=user.id,
        title="BRCA1 Homologous Recombination and PARP Inhibitors",
        filename="brca1_parp_review.txt",
        content=paper_text,
        source_type="abstract",
    )

    assert doc.id is not None
    assert doc.chunk_count >= 1

    # Query relevant context
    citations = ks.retrieve_context(
        db=db_session,
        project_id=project.id,
        query="BRCA1 DNA repair mechanisms and ovarian carcinoma",
        top_k=3,
        score_threshold=0.0,
    )

    assert len(citations) >= 1
    top_cite = citations[0]
    assert top_cite["document_title"] == "BRCA1 Homologous Recombination and PARP Inhibitors"
    assert "homologous recombination" in top_cite["chunk_text"].lower()
    assert top_cite["relevance_score"] > 0.0

    # Query empty/unrelated project
    citations_empty = ks.retrieve_context(
        db=db_session,
        project_id="non_existent_project_uuid",
        query="BRCA1 DNA repair",
    )
    assert len(citations_empty) == 0


def test_knowledge_api_endpoints_and_tenant_isolation(client, db_session: Session, memory_vector_store):
    """Verify REST API endpoints for knowledge ingestion, search, deletion, and cross-user authorization with Qdrant."""
    from app.api.routers import knowledge
    knowledge._knowledge_service = KnowledgeService(
        embedding_service=EmbeddingService(mock_mode=True, dimension=2560),
        vector_store=memory_vector_store,
    )

    # 1. Setup Researcher A and Project A
    user_a = User(
        email="researcher_a_qdrant@neuroforge.org",
        hashed_password=get_password_hash("PassA123"),
        full_name="Researcher Alpha",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    user_b = User(
        email="researcher_b_qdrant@neuroforge.org",
        hashed_password=get_password_hash("PassB123"),
        full_name="Researcher Beta",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add_all([user_a, user_b])
    db_session.commit()

    proj_a = Project(title="Alpha Oncology", domain="Cancer Gene-Expression", owner_id=user_a.id)
    proj_b = Project(title="Beta Immunology", domain="Biomarker Discovery", owner_id=user_b.id)
    db_session.add_all([proj_a, proj_b])
    db_session.commit()

    token_a = create_access_token(user_id=user_a.id, role=user_a.role)
    token_b = create_access_token(user_id=user_b.id, role=user_b.role)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 2. Researcher A ingests text abstract into Project A
    res_text = client.post(
        f"/projects/{proj_a.id}/knowledge/text",
        headers=headers_a,
        json={
            "title": "TP53 Pathway Disruption",
            "content": "TP53 mutations occur in over 50 percent of human cancers leading to defective apoptotic checkpoints.",
            "source_type": "abstract",
        },
    )
    assert res_text.status_code == 201
    doc_id = res_text.json()["id"]

    # 3. Researcher A uploads a file document into Project A
    file_content = b"EGFR amplification stimulates downstream PI3K-AKT and MAPK signaling cascades."
    res_upload = client.post(
        f"/projects/{proj_a.id}/knowledge/upload",
        headers=headers_a,
        files={"file": ("egfr_paper.txt", file_content, "text/plain")},
        data={"title": "EGFR Pathway Study", "source_type": "upload"},
    )
    assert res_upload.status_code == 201

    # 4. Researcher A lists documents
    res_list = client.get(f"/projects/{proj_a.id}/knowledge", headers=headers_a)
    assert res_list.status_code == 200
    assert len(res_list.json()) == 2

    # 5. Semantic Search as Researcher A
    res_search = client.post(
        f"/projects/{proj_a.id}/knowledge/search",
        headers=headers_a,
        json={"query": "TP53 apoptosis and tumor suppression", "top_k": 3},
    )
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert search_data["total_results"] >= 1
    assert any("TP53" in c["chunk_text"] for c in search_data["citations"])

    # 6. Cross-User Authorization Check: Researcher B attempts to access Project A's knowledge
    res_b_list = client.get(f"/projects/{proj_a.id}/knowledge", headers=headers_b)
    assert res_b_list.status_code == 403

    res_b_search = client.post(
        f"/projects/{proj_a.id}/knowledge/search",
        headers=headers_b,
        json={"query": "TP53", "top_k": 3},
    )
    assert res_b_search.status_code == 403

    res_b_delete = client.delete(f"/projects/{proj_a.id}/knowledge/{doc_id}", headers=headers_b)
    assert res_b_delete.status_code == 403

    # 7. Researcher A deletes document
    res_delete = client.delete(f"/projects/{proj_a.id}/knowledge/{doc_id}", headers=headers_a)
    assert res_delete.status_code == 200

    # Verify list count decreased to 1
    res_list_after = client.get(f"/projects/{proj_a.id}/knowledge", headers=headers_a)
    assert len(res_list_after.json()) == 1


def test_langgraph_research_agent_with_literature_context(db_session: Session, memory_vector_store):
    """Verify LangGraph workflow retrieves literature context and injects it into planning and report generation."""
    store = memory_vector_store
    emb_svc = EmbeddingService(mock_mode=True, dimension=2560)
    ks = KnowledgeService(embedding_service=emb_svc, vector_store=store)

    user = User(
        email="agent_scientist_qdrant@neuroforge.org",
        hashed_password=get_password_hash("AgentPass123"),
        full_name="Dr. Agent Scientist",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    project = Project(
        title="Comparative Lung Adenocarcinoma Profiling",
        domain="Cancer Gene-Expression",
        owner_id=user.id,
    )
    dataset = Dataset(
        project_id=project.id,
        owner_id=user.id,
        filename="lung_expression.csv",
        original_name="lung_expression.csv",
        file_size_bytes=1024,
        status="Validated",
    )
    db_session.add_all([project, dataset])
    db_session.commit()

    # Ingest scientific literature document into project
    ks.ingest_document(
        db=db_session,
        project_id=project.id,
        owner_id=user.id,
        title="EGFR Mutant Lung Cancer Biology",
        filename="egfr_lung.txt",
        content=b"EGFR tyrosine kinase mutations in lung adenocarcinoma drive high sensitivity to osimertinib.",
        source_type="abstract",
    )

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Investigation of EGFR Alterations",
        objective="Assess EGFR and downstream transcriptional alterations in lung carcinoma",
    )
    db_session.add(session)
    db_session.commit()

    # Initial state
    state: ResearchState = {
        "session_id": session.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session.objective,
        "domain": project.domain,
        "status": SessionStatus.INITIALIZING.value,
        "current_step": "initialize_research",
        "evidence_store": [{"summary": "Dataset contains 2,000 features and 10 samples."}],
        "tool_history": [],
        "experiment_ids": [],
    }

    # 1. Test retrieve_scientific_knowledge_node
    from unittest.mock import patch
    with patch("app.services.knowledge_service.KnowledgeService", return_value=ks):
        state = retrieve_scientific_knowledge_node(state, db_session)

    assert state.get("literature_evidence") is not None
    assert len(state["literature_evidence"]) >= 1
    assert "EGFR" in state["literature_evidence"][0]["document_title"]

    # 2. Test generate_research_plan_node prompt formatting with literature evidence
    captured_messages = []

    def mock_vultr_chat(messages, response_model=None):
        captured_messages.extend(messages)
        return InferenceResponse(
            content="{}",
            parsed={
                "objective": "Assess EGFR transcriptional alterations",
                "observed_facts": ["Dataset contains 2,000 features."],
                "assumptions_hypotheses": ["EGFR activates MAPK."],
                "proposed_experiments": [
                    {
                        "tool_name": "pca_exploratory_analysis",
                        "description": "Exploratory PCA",
                        "rationale": "Sample clustering",
                        "parameters": {},
                    }
                ],
                "expected_outcomes": ["Segregation of cohorts"],
                "scientific_limitations": ["Limited sample size"],
            },
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.1,
            total_tokens=150,
        )

    mock_svc = VultrInferenceService(mock_handler=mock_vultr_chat)
    state = generate_research_plan_node(state, db_session, mock_svc)

    user_prompt = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert "RETRIEVED PEER-REVIEWED SCIENTIFIC LITERATURE CONTEXT (RAG)" in user_prompt
    assert "EGFR Mutant Lung Cancer Biology" in user_prompt

    # 3. Test generate_research_summary_node distinguishes empirical findings and literature
    captured_summary_messages = []

    def mock_vultr_summary(messages, response_model=None):
        captured_summary_messages.extend(messages)
        return InferenceResponse(
            content="{}",
            parsed={
                "title": "Autonomous Investigation Summary",
                "executive_summary": "Differential screening revealed significant transcriptional alterations.",
                "dataset_characteristics": {"features": 2000, "samples": 10},
                "methodology": "Welch's t-test with Benjamini-Hochberg FDR correction and exploratory PCA.",
                "key_findings": [
                    {
                        "feature_name": "EGFR",
                        "log2_fold_change": 2.4,
                        "fdr_q_value": 0.001,
                        "regulation_direction": "Upregulated",
                        "biological_context": "Significantly elevated in mutant cohort",
                    }
                ],
                "retrieved_literature_synthesis": "Literature review indicates EGFR mutations drive sensitivity to targeted inhibitors.",
                "literature_citations": ["EGFR Mutant Lung Cancer Biology (egfr_lung.txt)"],
                "scientific_caveats": ["Observational finding requiring orthogonal validation."],
                "unconfirmed_hypotheses": ["Downstream AKT phosphorylation may be elevated."],
                "recommended_future_work": ["Targeted Western blot verification."],
            },
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.2,
            total_tokens=220,
        )

    mock_summary_svc = VultrInferenceService(mock_handler=mock_vultr_summary)
    state = generate_research_summary_node(state, db_session, mock_summary_svc)

    assert state.get("final_summary") is not None
    summary = state["final_summary"]
    assert "retrieved_literature_synthesis" in summary
    assert len(summary["literature_citations"]) >= 1
    assert summary["key_findings"][0]["feature_name"] == "EGFR"


def test_langgraph_research_agent_without_literature_graceful_fallback(db_session: Session, memory_vector_store):
    """Verify LangGraph workflow gracefully handles projects with ZERO uploaded literature."""
    store = memory_vector_store
    emb_svc = EmbeddingService(mock_mode=True, dimension=2560)
    ks = KnowledgeService(embedding_service=emb_svc, vector_store=store)

    user = User(
        email="solo_scientist_qdrant@neuroforge.org",
        hashed_password=get_password_hash("SoloPass123"),
        full_name="Dr. Solo",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    project = Project(title="Zero Knowledge Project", domain="Biomarker Discovery", owner_id=user.id)
    dataset = Dataset(project_id=project.id, owner_id=user.id, filename="data.csv", original_name="data.csv", file_size_bytes=512)
    db_session.add_all([project, dataset])
    db_session.commit()

    session = ResearchSession(
        project_id=project.id,
        dataset_id=dataset.id,
        owner_id=user.id,
        title="Screening Session",
        objective="Analyze expression patterns",
    )
    db_session.add(session)
    db_session.commit()

    state: ResearchState = {
        "session_id": session.id,
        "project_id": project.id,
        "dataset_id": dataset.id,
        "user_id": user.id,
        "objective": session.objective,
        "domain": project.domain,
        "status": SessionStatus.INITIALIZING.value,
        "current_step": "initialize_research",
        "evidence_store": [{"summary": "500 features inspected."}],
    }

    from unittest.mock import patch
    with patch("app.services.knowledge_service.KnowledgeService", return_value=ks):
        state = retrieve_scientific_knowledge_node(state, db_session)

    assert state["literature_evidence"] == []

    captured_messages = []

    def mock_vultr_chat(messages, response_model=None):
        captured_messages.extend(messages)
        return InferenceResponse(
            content="{}",
            parsed={
                "objective": "Analyze expression patterns",
                "observed_facts": ["500 features inspected."],
                "assumptions_hypotheses": ["Features are normally distributed."],
                "proposed_experiments": [],
                "expected_outcomes": [],
                "scientific_limitations": ["No literature uploaded"],
            },
            model="llama-3.3-70b-instruct-fp8",
            duration_seconds=0.1,
            total_tokens=100,
        )

    mock_svc = VultrInferenceService(mock_handler=mock_vultr_chat)
    state = generate_research_plan_node(state, db_session, mock_svc)

    user_prompt = next(m["content"] for m in captured_messages if m["role"] == "user")
    assert "No external literature documents uploaded for this project" in user_prompt
    assert state.get("research_plan") is not None


def test_knowledge_document_custom_metadata(client, db_session: Session, memory_vector_store):
    """Verify scientific document custom metadata ingestion, persistence, retrieval, and pagination."""
    from app.api.routers import knowledge
    knowledge._knowledge_service = KnowledgeService(
        embedding_service=EmbeddingService(mock_mode=True, dimension=2560),
        vector_store=memory_vector_store,
    )

    user = User(
        email="metadata_scientist@neuroforge.org",
        hashed_password=get_password_hash("MetaPass123"),
        full_name="Dr. Metadata",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    proj = Project(title="Metadata Project", domain="Cancer Gene-Expression", owner_id=user.id)
    db_session.add(proj)
    db_session.commit()

    token = create_access_token(user_id=user.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Ingest via JSON text endpoint with complete custom metadata
    res_text = client.post(
        f"/projects/{proj.id}/knowledge/text",
        headers=headers,
        json={
            "title": "KRAS G12C Targeting in NSCLC",
            "content": "Sotorasib and adagrasib specifically inhibit mutant KRAS G12C by locking the switch II pocket in an inactive GDP-bound state.",
            "source_type": "paper",
            "doi": "10.1056/NEJMoa1914710",
            "authors": "Canon J, Rex K, Saiki AY, et al.",
            "publication_year": 2019,
            "journal": "Nature",
            "source_url": "https://doi.org/10.1056/NEJMoa1914710",
            "tags": "kras,nsclc,targeted-therapy",
            "custom_metadata": {"clinical_trial_phase": "Phase I/II", "cohort_size": 129},
        },
    )
    assert res_text.status_code == 201
    data = res_text.json()
    assert data["doi"] == "10.1056/NEJMoa1914710"
    assert data["publication_year"] == 2019
    assert data["journal"] == "Nature"
    assert "clinical_trial_phase" in data["custom_metadata"]

    # 2. Upload via multipart file endpoint with custom metadata
    file_bytes = b"Osimertinib demonstrates superior progression-free survival in EGFR T790M positive advanced non-small cell lung cancer."
    res_upload = client.post(
        f"/projects/{proj.id}/knowledge/upload",
        headers=headers,
        files={"file": ("osimertinib_study.txt", file_bytes, "text/plain")},
        data={
            "title": "Osimertinib in EGFR T790M",
            "source_type": "trial",
            "doi": "10.1056/NEJMoa1612674",
            "authors": "Mok TS, Wu YL, Ahn MJ, et al.",
            "publication_year": "2017",
            "journal": "The New England Journal of Medicine",
            "source_url": "https://www.nejm.org/doi/full/10.1056/NEJMoa1612674",
            "tags": "egfr,t790m,osimertinib",
            "custom_metadata": json.dumps({"line_of_therapy": "second_line"}),
        },
    )
    assert res_upload.status_code == 201
    upload_data = res_upload.json()
    assert upload_data["doi"] == "10.1056/NEJMoa1612674"
    assert upload_data["publication_year"] == 2017
    assert upload_data["journal"] == "The New England Journal of Medicine"

    # 3. Test pagination on list endpoint
    res_list = client.get(f"/projects/{proj.id}/knowledge?limit=1&offset=0", headers=headers)
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1

    # 4. Search and verify citation contains document metadata
    res_search = client.post(
        f"/projects/{proj.id}/knowledge/search",
        headers=headers,
        json={"query": "KRAS switch II pocket inhibitor", "top_k": 3},
    )
    assert res_search.status_code == 200
    search_json = res_search.json()
    assert search_json["total_results"] >= 1
    top_citation = search_json["citations"][0]
    assert "doi" in top_citation["metadata"]
    assert top_citation["metadata"]["doi"] == "10.1056/NEJMoa1914710"
