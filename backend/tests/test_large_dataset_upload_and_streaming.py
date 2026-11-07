import io
import json
import os
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest
from fastapi import status

from app.core.security import create_access_token, get_password_hash
from app.db.models import Dataset, Project, User, UserRole
from app.services.dataset_parser import (
    MAX_FILE_SIZE_BYTES,
    DatasetParseError,
    parse_scientific_dataset,
)
from app.services.dataset_quality import (
    compute_dataset_quality,
    compute_pca,
)
from app.services.storage import (
    get_dataset_file_path,
    get_temp_upload_dir,
    get_upload_dir,
    save_upload_file,
    save_upload_from_file,
)


@pytest.fixture
def auth_user_fixture(db_session):
    user = User(
        email="performance_researcher@neuroforge.org",
        hashed_password=get_password_hash("ResearcherPass123"),
        full_name="Performance Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id, user.role)

    project = Project(
        title="High-Throughput Study",
        description="High-Throughput Performance Project",
        domain="Cancer Gene-Expression",
        status="Active",
        owner_id=user.id,
    )
    db_session.add(project)
    db_session.commit()

    return {"user": user, "token": token, "project": project}


# =============================================================================
# 1. Path-Based and Bytes Parity Parsing Tests
# =============================================================================

def test_path_based_parsing_csv_and_tsv(tmp_path):
    """Verify parse_scientific_dataset correctly parses CSV and TSV directly from a Path object."""
    csv_file = tmp_path / "matrix.csv"
    csv_content = (
        "gene_id,TCGA_01,TCGA_02,TCGA_03\n"
        "TP53,10.2,10.5,10.1\n"
        "BRCA1,8.4,8.2,8.5\n"
        "EGFR,11.0,11.2,10.9\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    parsed = parse_scientific_dataset(csv_file, "matrix.csv")
    assert parsed.file_format == "CSV"
    assert parsed.num_features == 3
    assert parsed.num_samples == 3
    assert parsed.sample_ids == ["TCGA_01", "TCGA_02", "TCGA_03"]
    assert "TP53" in parsed.feature_ids
    assert parsed.numeric_matrix.shape == (3, 3)

    tsv_file = tmp_path / "matrix.tsv"
    tsv_content = csv_content.replace(",", "\t")
    tsv_file.write_text(tsv_content, encoding="utf-8")

    parsed_tsv = parse_scientific_dataset(tsv_file, "matrix.tsv")
    assert parsed_tsv.file_format == "TSV"
    assert parsed_tsv.num_features == 3
    assert parsed_tsv.num_samples == 3


def test_path_based_parsing_gct(tmp_path):
    """Verify parse_scientific_dataset correctly parses GCT 1.2 and 1.3 from Path objects."""
    gct12_file = tmp_path / "test.gct"
    gct12_content = (
        "#1.2\n"
        "3\t3\n"
        "Name\tDescription\tS1\tS2\tS3\n"
        "BRCA1\tBreast Cancer 1\t7.2\t7.5\t7.1\n"
        "TP53\tTumor Protein 53\t11.4\t11.8\t11.2\n"
        "PTEN\tPhosphatase\t6.3\t6.1\t6.5\n"
    )
    gct12_file.write_text(gct12_content, encoding="utf-8")

    parsed12 = parse_scientific_dataset(gct12_file, "test.gct")
    assert parsed12.file_format == "GCT_1.2"
    assert parsed12.num_features == 3
    assert parsed12.num_samples == 3
    assert parsed12.sample_ids == ["S1", "S2", "S3"]

    gct13_file = tmp_path / "test13.gct"
    gct13_content = (
        "#1.3\n"
        "2\t2\t1\t0\n"
        "id\tdescription\tGSM01\tGSM02\n"
        "EGFR\tEpidermal Growth Factor\t14.2\t13.9\n"
        "KRAS\tGTPase\t8.1\t8.4\n"
    )
    gct13_file.write_text(gct13_content, encoding="utf-8")

    parsed13 = parse_scientific_dataset(gct13_file, "test13.gct")
    assert parsed13.file_format == "GCT_1.3"
    assert parsed13.num_features == 2
    assert parsed13.num_samples == 2


def test_bytes_and_path_parsing_parity(tmp_path):
    """Ensure that Path parsing and Bytes parsing return identical results and matrices."""
    csv_text = (
        "gene_id,TCGA_A,TCGA_B\n"
        "TP53,12.3,14.5\n"
        "PTEN,5.6,5.8\n"
    )
    csv_bytes = csv_text.encode("utf-8")
    csv_path = tmp_path / "parity.csv"
    csv_path.write_bytes(csv_bytes)

    from_bytes = parse_scientific_dataset(csv_bytes, "parity.csv")
    from_path = parse_scientific_dataset(csv_path, "parity.csv")

    assert from_bytes.file_format == from_path.file_format
    assert from_bytes.content_hash == from_path.content_hash
    assert from_bytes.num_features == from_path.num_features
    assert from_bytes.num_samples == from_path.num_samples
    assert from_bytes.feature_ids == from_path.feature_ids
    assert from_bytes.sample_ids == from_path.sample_ids
    pd.testing.assert_frame_equal(from_bytes.numeric_matrix, from_path.numeric_matrix)


# =============================================================================
# 2. Upload Boundary & Streaming Enforcement
# =============================================================================

def test_upload_boundary_streaming_rejection(client, auth_user_fixture):
    """Verify that uploading beyond 200 MiB is rejected with HTTP 413 during streaming."""
    f = auth_user_fixture

    # Test file exceeding MAX_FILE_SIZE_BYTES
    oversized_data = b"A" * 1024  # small chunk for test, patch MAX_FILE_SIZE_BYTES to 500 bytes
    with patch("app.api.routers.datasets.MAX_FILE_SIZE_BYTES", 500):
        res = client.post(
            "/datasets/upload",
            data={"project_id": f["project"].id, "title": "Boundary Test"},
            files={"file": ("stream_oversize.csv", io.BytesIO(oversized_data), "text/csv")},
            headers={"Authorization": f"Bearer {f['token']}"},
        )
        assert res.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        assert "exceeds maximum allowed size" in res.json()["detail"].lower()


# =============================================================================
# 3. Malformed GCT Validation
# =============================================================================

def test_malformed_gct_rejected(tmp_path):
    """Verify various malformed GCT files are cleanly rejected with DatasetParseError."""
    # 1. Invalid version
    f1 = tmp_path / "bad_ver.gct"
    f1.write_text("#2.0\n3\t3\nName\tDesc\tS1\n", encoding="utf-8")
    with pytest.raises(DatasetParseError) as exc:
        parse_scientific_dataset(f1, "bad_ver.gct")
    assert "Unrecognized GCT version" in str(exc.value)

    # 2. Missing dimensions row
    f2 = tmp_path / "bad_dims.gct"
    f2.write_text("#1.2\nName\tDesc\tS1\n", encoding="utf-8")
    with pytest.raises(DatasetParseError) as exc:
        parse_scientific_dataset(f2, "bad_dims.gct")
    assert "GCT" in str(exc.value)

    # 3. Non-numeric dimensions
    f3 = tmp_path / "non_num_dims.gct"
    f3.write_text("#1.2\nthree\tthree\nName\tDesc\tS1\n", encoding="utf-8")
    with pytest.raises(DatasetParseError) as exc:
        parse_scientific_dataset(f3, "non_num_dims.gct")
    assert "Invalid numeric values" in str(exc.value)

    # 4. Empty data rows
    f4 = tmp_path / "empty_data.gct"
    f4.write_text("#1.2\n2\t2\nName\tDesc\tS1\tS2\n", encoding="utf-8")
    with pytest.raises(DatasetParseError) as exc:
        parse_scientific_dataset(f4, "empty_data.gct")
    assert "contains header and metadata but no data rows" in str(exc.value)


# =============================================================================
# 4. Dimension & Limits Enforcement (Never Silently Truncate)
# =============================================================================

def test_dimension_limits_rejected(tmp_path):
    """Verify configured row, column and cell limits are strictly enforced without truncation."""
    csv_file = tmp_path / "big_dims.csv"
    lines = ["gene_id,s1,s2,s3,s4"]
    for i in range(25):
        lines.append(f"GENE_{i},1.0,2.0,3.0,4.0")
    csv_file.write_text("\n".join(lines), encoding="utf-8")

    # Exceeding max_rows (limit: 10 rows, file has 25)
    with pytest.raises(DatasetParseError) as exc:
        parse_scientific_dataset(csv_file, "big_dims.csv", max_rows=10)
    assert "exceed configured maximum limits" in str(exc.value)
    assert "Never silently truncate data" in str(exc.value)

    # Exceeding max_cols (limit: 2 cols, file has 4 data cols)
    with pytest.raises(DatasetParseError) as exc:
        parse_scientific_dataset(csv_file, "big_dims.csv", max_cols=2)
    assert "exceed configured maximum limits" in str(exc.value)

    # Exceeding max_cells (limit: 50 cells, file has 100 cells)
    with pytest.raises(DatasetParseError) as exc:
        parse_scientific_dataset(csv_file, "big_dims.csv", max_cells=50)
    assert "exceed configured maximum limits" in str(exc.value)


# =============================================================================
# 5. Temporary Upload Staging & Cleanup
# =============================================================================

def test_upload_staging_and_cleanup_on_success_and_failure(client, auth_user_fixture):
    """Verify temporary files in .tmp staging directory are guaranteed cleaned up."""
    f = auth_user_fixture
    temp_dir = get_temp_upload_dir()

    # Baseline: check temp dir
    before_tmp_files = list(temp_dir.glob("*.tmp"))

    # Successful upload
    valid_csv = b"gene_id,s1,s2\nTP53,10.0,11.0\nBRCA1,5.0,6.0\n"
    res_ok = client.post(
        "/datasets/upload",
        data={"project_id": f["project"].id, "title": "Cleanup Test Success"},
        files={"file": ("clean_ok.csv", io.BytesIO(valid_csv), "text/csv")},
        headers={"Authorization": f"Bearer {f['token']}"},
    )
    assert res_ok.status_code == status.HTTP_201_CREATED

    # After success, staging file should not remain in .tmp
    after_success_tmp = list(temp_dir.glob("*.tmp"))
    assert len(after_success_tmp) == len(before_tmp_files)

    # Failed upload: malformed CSV that fails parsing
    malformed_csv = b"CORRUPTED_NO_HEADER_DATA_WITH_NOTHING"
    res_fail = client.post(
        "/datasets/upload",
        data={"project_id": f["project"].id, "title": "Cleanup Test Fail"},
        files={"file": ("clean_fail.csv", io.BytesIO(malformed_csv), "text/csv")},
        headers={"Authorization": f"Bearer {f['token']}"},
    )
    assert res_fail.status_code == status.HTTP_400_BAD_REQUEST

    # After failure, staging file must still be cleaned up
    after_fail_tmp = list(temp_dir.glob("*.tmp"))
    assert len(after_fail_tmp) == len(before_tmp_files)


# =============================================================================
# 6. Large Matrix Behavior, Bounded Sampling & PCA
# =============================================================================

def test_large_matrix_quality_assessment_sampling_and_pca_bounding():
    """Verify high-dimensional matrices use bounded sampling and bounded PCA without full flatten copies."""
    # 1. Test PCA bounding with 2,500 features (exceeds max_pca_features=2000)
    np.random.seed(42)
    n_features = 2500
    n_samples = 8
    data = np.random.normal(loc=10.0, scale=2.0, size=(n_features, n_samples))
    feature_names = [f"FEAT_{i}" for i in range(n_features)]
    sample_names = [f"SAMP_{i}" for i in range(n_samples)]

    df = pd.DataFrame(data, index=feature_names, columns=sample_names)

    # compute_pca with max_pca_features=2000
    pca_res = compute_pca(df, max_pca_features=2000)
    assert pca_res is not None
    assert len(pca_res.coordinates) == n_samples
    assert pca_res.total_explained_variance > 0.0

    # 2. Test large matrix distribution sampling (> 500,000 cells)
    # 60,000 features x 10 samples = 600,000 cells
    n_big_features = 60000
    n_big_samples = 10
    big_data = np.random.uniform(low=0.0, high=15.0, size=(n_big_features, n_big_samples))
    big_df = pd.DataFrame(big_data, index=[f"G_{i}" for i in range(n_big_features)], columns=[f"S_{i}" for i in range(n_big_samples)])

    quality = compute_dataset_quality(big_df)
    assert quality.total_features == 60000
    assert quality.total_samples == 10
    assert quality.total_cells == 600000
    assert quality.distribution.min_val >= 0.0
    assert quality.distribution.max_val <= 15.0

    # Verify summary notes explain bounded sampling and PCA bounding
    notes_joined = " ".join(quality.summary_notes)
    assert "deterministic bounded systematic sampling" in notes_joined or "bounded" in notes_joined
    assert "top 2,000" in notes_joined


# =============================================================================
# 7. Atomic Storage & Partial File Prevention
# =============================================================================

def test_atomic_storage_and_partial_file_prevention(tmp_path):
    """Verify save_upload_from_file and save_upload_file atomically persist files without leaving partial fragments."""
    # Test file-to-file atomic save
    source_file = tmp_path / "source_atomic.csv"
    source_file.write_text("id,val\nA,1.0\n", encoding="utf-8")

    stored_name, target_path = save_upload_from_file(source_file, "source_atomic.csv")
    assert target_path.exists()
    assert target_path.is_file()
    assert target_path.read_text(encoding="utf-8") == "id,val\nA,1.0\n"

    # Test bytes atomic save
    bytes_data = b"id,val\nB,2.0\n"
    stored_name_bytes, target_path_bytes = save_upload_file(bytes_data, "bytes_atomic.csv")
    assert target_path_bytes.exists()
    assert target_path_bytes.read_bytes() == bytes_data

    # Cleanup test files
    target_path.unlink(missing_ok=True)
    target_path_bytes.unlink(missing_ok=True)
