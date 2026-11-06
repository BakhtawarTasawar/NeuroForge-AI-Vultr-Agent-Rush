import io
import json
import pytest
from app.db.models import Dataset, User, UserRole
from app.services.dataset_parser import (
    DatasetParseError,
    parse_scientific_dataset,
)
from app.services.dataset_quality import (
    compute_dataset_quality,
    validate_group_mappings,
)


def test_parse_csv_features_as_rows():
    csv_content = (
        "Gene_Symbol,Sample_01,Sample_02,Sample_03,Sample_04\n"
        "TP53,10.2,11.5,10.8,9.9\n"
        "BRCA1,5.4,5.1,5.8,5.2\n"
        "EGFR,12.1,11.9,12.5,12.2\n"
        "MYC,8.3,8.7,8.1,8.5\n"
    ).encode("utf-8")

    parsed = parse_scientific_dataset(csv_content, "expression.csv")
    assert parsed.file_format == "CSV"
    assert parsed.num_features == 4
    assert parsed.num_samples == 4
    assert parsed.orientation.detected_orientation == "features_as_rows"
    assert parsed.orientation.confidence >= 0.7
    assert len(parsed.content_hash) == 64


def test_parse_samples_as_rows():
    csv_content = (
        "Sample_ID,TP53,BRCA1,EGFR,MYC\n"
        "Sample_01,10.2,5.4,12.1,8.3\n"
        "Sample_02,11.5,5.1,11.9,8.7\n"
        "Sample_03,10.8,5.8,12.5,8.1\n"
        "Sample_04,9.9,5.2,12.2,8.5\n"
    ).encode("utf-8")

    parsed = parse_scientific_dataset(csv_content, "ml_matrix.csv")
    assert parsed.orientation.detected_orientation == "samples_as_rows"
    assert parsed.orientation.confidence >= 0.7


def test_parse_gct_12():
    gct_content = (
        "#1.2\n"
        "3\t3\n"
        "Name\tDescription\tTCGA_01\tTCGA_02\tTCGA_03\n"
        "BRCA1\tBreast Cancer 1\t7.2\t7.5\t7.1\n"
        "TP53\tTumor Protein 53\t11.4\t11.8\t11.2\n"
        "PTEN\tPhosphatase\t6.3\t6.1\t6.5\n"
    ).encode("utf-8")

    parsed = parse_scientific_dataset(gct_content, "test.gct")
    assert parsed.file_format == "GCT_1.2"
    assert parsed.num_features == 3
    assert parsed.num_samples == 3
    assert parsed.sample_ids == ["TCGA_01", "TCGA_02", "TCGA_03"]
    assert parsed.orientation.detected_orientation == "features_as_rows"


def test_parse_gct_13():
    gct_content = (
        "#1.3\n"
        "2\t2\t1\t0\n"
        "id\tdescription\tGSM001\tGSM002\n"
        "EGFR\tEpidermal Growth Factor\t14.2\t13.9\n"
        "KRAS\tGTPase\t8.1\t8.4\n"
    ).encode("utf-8")

    parsed = parse_scientific_dataset(gct_content, "dataset_v13.gct")
    assert parsed.file_format == "GCT_1.3"
    assert parsed.num_features == 2
    assert parsed.num_samples == 2
    assert parsed.orientation.detected_orientation == "features_as_rows"


def test_parse_empty_and_oversized_rejected():
    with pytest.raises(DatasetParseError):
        parse_scientific_dataset(b"", "empty.csv")

    with pytest.raises(DatasetParseError):
        # 26 MB of zero bytes
        huge = b"a" * (26 * 1024 * 1024)
        parse_scientific_dataset(huge, "huge.csv")


def test_quality_assessment_deterministic():
    import numpy as np
    import pandas as pd

    # Log2 continuous expression matrix: 6 features x 6 samples
    data = np.array([
        [10.2, 10.5, 10.1, 9.8, 10.4, 10.0],
        [5.1, 5.3, 5.0, 5.2, 5.1, 5.4],
        [12.0, 11.8, 12.2, 12.1, 11.9, 12.3],
        [8.4, 8.2, 8.5, 8.3, 8.6, 8.1],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # Constant / zero-variance feature
        [7.0, np.nan, 7.2, 7.1, 6.9, 7.3],  # Feature with 1 missing cell
    ])
    df = pd.DataFrame(
        data,
        index=["BRCA1", "TP53", "EGFR", "MYC", "ZERO_GENE", "PTEN"],
        columns=["S1", "S2", "S3", "S4", "S5", "S6"],
    )

    quality = compute_dataset_quality(df)
    assert quality.total_features == 6
    assert quality.total_samples == 6
    assert quality.total_cells == 36
    assert quality.missing_cells_count == 1
    assert quality.constant_features_count == 1
    assert "ZERO_GENE" in quality.constant_features_sample
    assert quality.distribution.scale_inference == "log2_transformed"
    assert quality.pca is not None
    assert len(quality.pca.coordinates) == 6


def test_sample_size_adequacy_welch_t_test():
    sample_ids = ["S1", "S2", "S3", "S4", "S5", "S6"]

    # Inadequate: 2 in control, 4 in treatment
    bad_groups = {
        "S1": "Control",
        "S2": "Control",
        "S3": "Treatment",
        "S4": "Treatment",
        "S5": "Treatment",
        "S6": "Treatment",
    }
    val_bad = validate_group_mappings(sample_ids, bad_groups, "log2_transformed", "Control", "Treatment")
    assert not val_bad.is_ready_for_testing
    assert not val_bad.sample_counts_valid
    assert any("Minimum 3 independent samples" in w for w in val_bad.warnings)

    # Adequate: 3 in control, 3 in treatment
    good_groups = {
        "S1": "Control",
        "S2": "Control",
        "S3": "Control",
        "S4": "Treatment",
        "S5": "Treatment",
        "S6": "Treatment",
    }
    val_good = validate_group_mappings(sample_ids, good_groups, "log2_transformed", "Control", "Treatment")
    assert val_good.is_ready_for_testing
    assert val_good.sample_counts_valid


def test_raw_counts_scale_warning_for_welch():
    sample_ids = ["S1", "S2", "S3", "S4", "S5", "S6"]
    good_groups = {
        "S1": "Control",
        "S2": "Control",
        "S3": "Control",
        "S4": "Treatment",
        "S5": "Treatment",
        "S6": "Treatment",
    }
    # Raw counts cannot be evaluated with Welch's t-test without normalization
    val = validate_group_mappings(sample_ids, good_groups, "raw_counts", "Control", "Treatment")
    assert not val.is_ready_for_testing
    assert not val.data_scale_valid_for_welch
    assert any("Welch's t-test requires log2-normalized" in w for w in val.warnings)


# API Integration Tests

from app.core.security import create_access_token, get_password_hash


def test_api_dataset_upload_inspect_preview_and_quality(client, db_session):
    researcher = User(
        email="res_intel@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Dr. Intelligence",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(researcher)
    db_session.commit()
    token = create_access_token(researcher.id, researcher.role)
    headers = {"Authorization": f"Bearer {token}"}

    csv_data = (
        "Gene_Symbol,Sample_A,Sample_B,Sample_C,Sample_D,Sample_E,Sample_F\n"
        "TP53,10.2,10.5,10.1,9.8,10.4,10.0\n"
        "BRCA1,5.1,5.3,5.0,5.2,5.1,5.4\n"
        "EGFR,12.0,11.8,12.2,12.1,11.9,12.3\n"
        "MYC,8.4,8.2,8.5,8.3,8.6,8.1\n"
        "PTEN,7.0,7.2,7.1,6.9,7.3,7.0\n"
    ).encode("utf-8")

    # 1. Upload
    res = client.post(
        "/datasets/upload",
        files={"file": ("expression.csv", io.BytesIO(csv_data), "text/csv")},
        data={"title": "TCGA Breast Cohort", "organism": "Homo sapiens", "tissue": "Breast"},
        headers=headers,
    )
    assert res.status_code == 201
    dataset = res.json()
    dataset_id = dataset["id"]
    assert dataset["sample_count"] == 6
    assert dataset["feature_count"] == 5
    assert dataset["matrix_orientation"] == "features_as_rows"
    assert dataset["content_hash"] is not None

    # 2. Inspect
    insp_res = client.get(f"/datasets/{dataset_id}/inspection", headers=headers)
    assert insp_res.status_code == 200
    insp = insp_res.json()
    assert insp["matrix_orientation"] == "features_as_rows"
    assert len(insp["sample_identifiers"]) == 6
    assert len(insp["feature_identifiers_sample"]) == 5

    # 3. Preview (bounded)
    prev_res = client.get(f"/datasets/{dataset_id}/preview?row_page=1&row_limit=3&col_page=1&col_limit=3", headers=headers)
    assert prev_res.status_code == 200
    prev = prev_res.json()
    assert prev["total_rows"] == 5
    assert prev["total_cols"] == 6
    assert len(prev["rows"]) == 3
    assert len(prev["columns"]) == 4  # _row_id + 3 sliced sample cols

    # 4. Quality
    qual_res = client.get(f"/datasets/{dataset_id}/quality", headers=headers)
    assert qual_res.status_code == 200
    qual = qual_res.json()
    assert qual["distribution"]["scale_inference"] == "log2_transformed"
    assert qual["missing_cells_count"] == 0
    assert qual["pca"] is not None

    # 5. Group Configuration
    groups = {
        "Sample_A": "Control",
        "Sample_B": "Control",
        "Sample_C": "Control",
        "Sample_D": "Treatment",
        "Sample_E": "Treatment",
        "Sample_F": "Treatment",
    }
    grp_res = client.post(
        f"/datasets/{dataset_id}/groups",
        json={"group_mappings": groups, "control_group": "Control", "treatment_group": "Treatment"},
        headers=headers,
    )
    assert grp_res.status_code == 200
    assert grp_res.json()["group_validation"]["is_ready_for_testing"] is True

    # 6. Metadata update
    meta_res = client.patch(
        f"/datasets/{dataset_id}/metadata",
        json={"tissue": "Mammary Epithelium", "experimental_condition": "Tumor vs Normal"},
        headers=headers,
    )
    assert meta_res.status_code == 200
    assert meta_res.json()["tissue"] == "Mammary Epithelium"

    # 7. Orientation update
    ori_res = client.patch(
        f"/datasets/{dataset_id}/orientation",
        json={"orientation": "samples_as_rows"},
        headers=headers,
    )
    assert ori_res.status_code == 200
    assert ori_res.json()["matrix_orientation"] == "samples_as_rows"


def test_rbac_dataset_restrictions(client, db_session):
    admin = User(
        email="adm_intel@neuroforge.org",
        hashed_password=get_password_hash("AdminPass123"),
        full_name="Admin Chief",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    researcher = User(
        email="res_owner@neuroforge.org",
        hashed_password=get_password_hash("ResPass123"),
        full_name="Dr. Owner",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    viewer = User(
        email="view_user@neuroforge.org",
        hashed_password=get_password_hash("ViewPass123"),
        full_name="Viewer Observer",
        role=UserRole.VIEWER.value,
        is_active=True,
    )
    db_session.add_all([admin, researcher, viewer])
    db_session.commit()

    admin_token = create_access_token(admin.id, admin.role)
    researcher_token = create_access_token(researcher.id, researcher.role)
    viewer_token = create_access_token(viewer.id, viewer.role)

    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    researcher_headers = {"Authorization": f"Bearer {researcher_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    csv_data = "Gene,S1,S2,S3\nTP53,1,2,3\n".encode("utf-8")

    # VIEWER cannot upload
    res_upload = client.post(
        "/datasets/upload",
        files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        headers=viewer_headers,
    )
    assert res_upload.status_code == 403

    # Researcher uploads
    res_res = client.post(
        "/datasets/upload",
        files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        headers=researcher_headers,
    )
    assert res_res.status_code == 201
    dataset_id = res_res.json()["id"]

    # VIEWER cannot modify orientation
    res_mod = client.patch(
        f"/datasets/{dataset_id}/orientation",
        json={"orientation": "samples_as_rows"},
        headers=viewer_headers,
    )
    assert res_mod.status_code == 403

    # Admin CAN inspect researcher's dataset
    res_adm = client.get(f"/datasets/{dataset_id}/inspection", headers=admin_headers)
    assert res_adm.status_code == 200
