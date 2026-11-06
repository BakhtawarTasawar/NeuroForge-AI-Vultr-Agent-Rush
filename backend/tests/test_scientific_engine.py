import io
import json
import math
import numpy as np
import pandas as pd
import pytest
import scipy.stats as stats

from app.core.security import create_access_token, get_password_hash
from app.db.models import Dataset, Experiment, ExperimentStatus, Project, User, UserRole
from app.services.statistical_engine import (
    benjamini_hochberg_correction,
    compute_pca_projection,
    compute_welch_t_test,
    run_differential_expression,
    validate_differential_expression_design,
)


# =====================================================================
# 1. Statistical Correctness Tests
# =====================================================================

def test_welch_t_test_against_scipy_reference():
    """Verify Welch's t-test matches scipy.stats.ttest_ind(equal_var=False) exactly."""
    group_a = np.array([10.2, 11.5, 9.8, 10.4, 10.1])
    group_b = np.array([14.1, 13.8, 14.5, 13.9, 14.2])

    # scipy reference: ttest_ind(b, a, equal_var=False) for direction B - A
    scipy_res = stats.ttest_ind(group_b, group_a, equal_var=False)

    our_res = compute_welch_t_test(group_a, group_b, feature_id="TEST_GENE", is_log2_scale=True)

    assert our_res.status == "computed"
    assert math.isclose(our_res.t_stat, scipy_res.statistic, abs_tol=1e-3)
    assert math.isclose(our_res.p_value, scipy_res.pvalue, abs_tol=1e-6)
    assert math.isclose(our_res.df, scipy_res.df, abs_tol=1e-2)
    assert our_res.n_a == 5
    assert our_res.n_b == 5
    assert our_res.mean_diff > 0


def test_confidence_interval_and_effect_size():
    """Verify 95% confidence interval and Hedges' g calculation."""
    group_a = np.array([5.0, 5.2, 4.9, 5.1, 5.3])
    group_b = np.array([8.0, 8.2, 7.9, 8.1, 8.3])

    res = compute_welch_t_test(group_a, group_b, feature_id="EGFR", is_log2_scale=True, alpha=0.05)

    assert res.ci_lower is not None
    assert res.ci_upper is not None
    assert res.ci_lower < res.mean_diff < res.ci_upper
    # Hedges' g should be positive and substantial
    assert res.hedges_g is not None and res.hedges_g > 2.0


def test_benjamini_hochberg_correction_known_example():
    """
    Test Benjamini-Hochberg against manual calculation:
    p-values: [0.01, 0.04, 0.03, 0.20]
    Ranks:
      Rank 1: 0.01 -> 0.01 * 4 / 1 = 0.04
      Rank 2: 0.03 -> 0.03 * 4 / 2 = 0.06
      Rank 3: 0.04 -> 0.04 * 4 / 3 = 0.0533 -> monotonic cap to min(0.0533, 0.20) = 0.0533
      Rank 4: 0.20 -> 0.20 * 4 / 4 = 0.20
    Monotonicity downwards:
      Rank 2 q = min(0.06, 0.0533) = 0.0533
      Rank 1 q = min(0.04, 0.0533) = 0.04
    Expected q-values in original order:
      p=0.01 -> 0.04
      p=0.04 -> 0.05333333
      p=0.03 -> 0.05333333
      p=0.20 -> 0.20
    """
    p_vals = [0.01, 0.04, 0.03, 0.20]
    q_vals = benjamini_hochberg_correction(p_vals)

    assert math.isclose(q_vals[0], 0.04, abs_tol=1e-4)
    assert math.isclose(q_vals[1], 0.05333333, abs_tol=1e-4)
    assert math.isclose(q_vals[2], 0.05333333, abs_tol=1e-4)
    assert math.isclose(q_vals[3], 0.20, abs_tol=1e-4)


def test_benjamini_hochberg_edge_cases():
    """Handle empty, single, NaN, and all-one p-values."""
    assert benjamini_hochberg_correction([]) == []

    single = benjamini_hochberg_correction([0.02])
    assert single == [0.02]

    with_nans = benjamini_hochberg_correction([0.01, None, 0.05, float("nan")])
    assert with_nans[1] is None
    assert with_nans[3] is None
    assert with_nans[0] is not None and with_nans[2] is not None


def test_constant_features_handling():
    """Constant features (zero variance across both groups) must return status 'constant_feature' with undefined t/p."""
    group_a = np.array([0.0, 0.0, 0.0, 0.0])
    group_b = np.array([0.0, 0.0, 0.0, 0.0])

    res = compute_welch_t_test(group_a, group_b, feature_id="ZERO_GENE", is_log2_scale=True)
    assert res.status == "constant_feature"
    assert res.t_stat is None
    assert res.p_value is None
    assert res.ci_lower is None
    assert res.ci_upper is None
    assert res.hedges_g is None
    assert "Zero sample variance across all samples" in res.notes


def test_welch_t_test_one_group_zero_variance():
    """When ONE group has zero variance but the other has nonzero variance, Welch's t is defined and matches SciPy."""
    group_a = np.array([2.0, 2.0, 2.0])
    group_b = np.array([3.0, 4.0, 5.0])

    # scipy reference: ttest_ind(b, a, equal_var=False) for direction B - A
    scipy_res = stats.ttest_ind(group_b, group_a, equal_var=False)

    res = compute_welch_t_test(group_a, group_b, feature_id="ONE_ZERO_VAR_GENE", is_log2_scale=True)
    assert res.status == "computed"
    assert res.t_stat is not None
    assert math.isclose(res.t_stat, scipy_res.statistic, abs_tol=1e-3)
    assert math.isclose(res.p_value, scipy_res.pvalue, abs_tol=1e-5)
    assert math.isclose(res.df, scipy_res.df, abs_tol=1e-2)  # df = n_b - 1 = 2.0
    assert res.ci_lower is not None and res.ci_upper is not None
    assert res.ci_lower < res.mean_diff < res.ci_upper
    assert res.hedges_g is not None and not math.isnan(res.hedges_g)
    assert "Group A exhibited zero sample variance" in res.notes


def test_welch_t_test_both_groups_zero_variance_differing_means():
    """When both groups have zero variance with differing means, standard error is 0 and statistic is undefined."""
    group_a = np.array([2.0, 2.0, 2.0])
    group_b = np.array([6.0, 6.0, 6.0])

    res = compute_welch_t_test(group_a, group_b, feature_id="DIFF_CONST_GENE", is_log2_scale=True)
    assert res.status == "constant_feature"
    assert res.t_stat is None
    assert res.p_value is None
    assert res.hedges_g is None
    assert res.mean_diff == 4.0
    assert "differing group means" in res.notes.lower()


def test_numerically_stable_p_values_extreme_cases():
    """Verify numerical stability of p-values for extreme t-statistics, small df, and tiny p-values."""
    # Extremely large t-statistic with small df (should produce tiny, non-negative, valid float)
    df_small = 2.0
    t_huge = 1000.0
    p_tiny = float(stats.t.sf(t_huge, df_small) * 2.0)
    assert p_tiny >= 0.0
    assert p_tiny < 1e-5
    assert not math.isnan(p_tiny)
    assert not math.isinf(p_tiny)

    # Moderate t-statistic with large sample size
    df_large = 100.0
    t_mod = 2.0
    p_mod = float(stats.t.sf(t_mod, df_large) * 2.0)
    assert 0.04 < p_mod < 0.06

    # Test that compute_welch_t_test retains precision for highly significant features
    g_a = np.array([1.0, 1.1, 0.9, 1.0, 1.05])
    g_b = np.array([20.0, 20.1, 19.9, 20.0, 20.05])
    res = compute_welch_t_test(g_a, g_b, "EXTREME_GENE", is_log2_scale=True)
    assert res.status == "computed"
    assert res.p_value is not None
    assert res.p_value < 1e-12
    assert res.p_value > 0.0  # Retained float precision, not truncated to 0


def test_hedges_g_unequal_sample_sizes_and_undefined_pooled_variance():
    """Verify Hedges' g calculation for unequal sample sizes and check handling when pooled variance is zero."""
    g_a = np.array([5.0, 5.2, 4.8])  # n_a = 3
    g_b = np.array([8.0, 8.1, 7.9, 8.2, 8.0, 7.8, 8.1])  # n_b = 7

    res = compute_welch_t_test(g_a, g_b, "UNEQUAL_N_GENE", is_log2_scale=True)
    assert res.status == "computed"
    assert res.hedges_g is not None
    assert not math.isnan(res.hedges_g)
    assert not math.isinf(res.hedges_g)

    # Manual calculation of pooled variance and Hedges' g
    n_a, n_b = 3, 7
    v_a = float(np.var(g_a, ddof=1))
    v_b = float(np.var(g_b, ddof=1))
    df_p = n_a + n_b - 2
    sp_sq = ((n_a - 1) * v_a + (n_b - 1) * v_b) / df_p
    sp = math.sqrt(sp_sq)
    d_expected = (np.mean(g_b) - np.mean(g_a)) / sp
    j_expected = 1.0 - (3.0 / (4.0 * df_p - 1.0))
    g_expected = d_expected * j_expected
    assert math.isclose(res.hedges_g, g_expected, abs_tol=1e-3)


def test_benjamini_hochberg_tied_p_values():
    """Tied p-values must receive identical adjusted p-values and maintain step-down monotonicity."""
    p_vals = [0.03, 0.03, 0.01, 0.05]
    q_vals = benjamini_hochberg_correction(p_vals)

    # p=0.01 has rank 1
    # p=0.03 (two ties) have ranks 2 and 3
    # p=0.05 has rank 4
    assert q_vals[0] == q_vals[1]  # Tied inputs receive identical q-values
    assert q_vals[2] <= q_vals[0]  # p=0.01 has lower or equal q than p=0.03
    assert q_vals[0] <= q_vals[3]  # p=0.03 has lower or equal q than p=0.05
    for q in q_vals:
        assert 0.0 <= q <= 1.0


def test_pca_projection_preprocessing_and_dimensions():
    """Test PCA projection handling of constant features, missing values, and high dimensionality."""
    # Matrix with 5 genes (features as rows), 4 samples (columns)
    # Gene 0: varying
    # Gene 1: constant (zero variance)
    # Gene 2: varying with a missing value (NaN)
    # Gene 3: varying
    # Gene 4: constant (zero variance)
    df = pd.DataFrame(
        {
            "S1": [1.0, 5.0, np.nan, 2.0, 0.0],
            "S2": [2.0, 5.0, 3.0, 4.0, 0.0],
            "S3": [1.5, 5.0, 3.2, 2.5, 0.0],
            "S4": [4.0, 5.0, 7.0, 8.0, 0.0],
        },
        index=["GENE_A", "GENE_CONST1", "GENE_NAN", "GENE_B", "GENE_CONST2"],
    )

    pca_res = compute_pca_projection(df, sample_ids=["S1", "S2", "S3", "S4"], n_components=2)

    assert pca_res.n_components == 2
    assert len(pca_res.coordinates) == 4
    assert pca_res.sample_ids == ["S1", "S2", "S3", "S4"]
    assert len(pca_res.explained_variance_ratio) == 2
    assert 0.0 <= pca_res.total_variance_explained <= 1.01
    assert any("zero-variance" in note.lower() for note in pca_res.preprocessing_notes)
    assert any("imputed" in note.lower() for note in pca_res.preprocessing_notes)

    # Verify no coordinates are NaN or Infinite
    for row in pca_res.coordinates:
        for c in row:
            assert not math.isnan(c)
            assert not math.isinf(c)

    # Test too few samples raises ValueError
    with pytest.raises(ValueError):
        compute_pca_projection(df, sample_ids=["S1"], n_components=2)


def test_missing_and_non_finite_values():
    """NaNs and infinite values are safely ignored in sample calculations."""
    group_a = np.array([10.0, np.nan, 10.2, 9.8, float("inf"), 10.1])
    group_b = np.array([12.0, 12.2, np.nan, 11.9, 12.1])

    res = compute_welch_t_test(group_a, group_b, feature_id="PTEN", is_log2_scale=True)
    assert res.status == "computed"
    assert res.n_a == 4  # 4 valid finite values
    assert res.n_b == 4  # 4 valid finite values


def test_zero_values_and_log2_fc():
    """Check log2 FC when scale is log2 vs linear."""
    # On log2 scale: mean_diff = mean_b - mean_a = log2 FC
    group_a = np.array([2.0, 2.0, 2.0])
    group_b = np.array([4.0, 4.0, 4.0])
    res_log2 = compute_welch_t_test(group_a, group_b, "G1", is_log2_scale=True)
    assert res_log2.log2_fc == 2.0

    # On linear scale with positive values: log2(mean_b / mean_a) = log2(8 / 2) = 2.0
    lin_a = np.array([2.0, 2.0, 2.0])
    lin_b = np.array([8.0, 8.0, 8.0])
    res_lin = compute_welch_t_test(lin_a, lin_b, "G2", is_log2_scale=False)
    assert math.isclose(res_lin.log2_fc, 2.0, abs_tol=1e-3)


def test_insufficient_sample_sizes():
    """Welch's t-test requires at least 2 observations per group for sample variance."""
    group_a = np.array([10.0])
    group_b = np.array([12.0, 12.2, 12.1])

    res = compute_welch_t_test(group_a, group_b, feature_id="SOLO_GENE")
    assert res.status == "insufficient_observations"
    assert res.t_stat is None
    assert res.p_value is None


def test_deterministic_repeated_execution():
    """Running differential expression twice on identical data produces identical outputs."""
    data = {
        "S1": [10.1, 5.0, 12.2],
        "S2": [10.2, 5.1, 12.1],
        "S3": [9.9, 4.9, 12.3],
        "S4": [14.0, 5.2, 12.0],
        "S5": [14.1, 5.0, 12.2],
        "S6": [13.9, 5.1, 12.1],
    }
    df = pd.DataFrame(data, index=["TP53", "BRCA1", "EGFR"])
    groups = {"S1": "Ctrl", "S2": "Ctrl", "S3": "Ctrl", "S4": "Treat", "S5": "Treat", "S6": "Treat"}

    res1 = run_differential_expression(df, groups, "Ctrl", "Treat", "d1", "hash1")
    res2 = run_differential_expression(df, groups, "Ctrl", "Treat", "d1", "hash1")

    assert res1.total_features_tested == res2.total_features_tested
    assert res1.significant_features_count == res2.significant_features_count
    for f1, f2 in zip(res1.top_features, res2.top_features):
        assert f1.feature_id == f2.feature_id
        assert f1.p_value == f2.p_value
        assert f1.adj_p_value == f2.adj_p_value


# =====================================================================
# 2. Scientific Design Validation Tests
# =====================================================================

def test_design_validation_raw_rna_seq_counts_rejected():
    """Raw counts must be explicitly rejected with the exact required scientific explanation."""
    sample_ids = ["S1", "S2", "S3", "S4", "S5", "S6"]
    groups = {"S1": "A", "S2": "A", "S3": "A", "S4": "B", "S5": "B", "S6": "B"}

    is_valid, err, _, _ = validate_differential_expression_design(
        dataset_orientation="features_as_rows",
        scale_inference="raw_counts",
        group_mappings=groups,
        sample_ids=sample_ids,
        group_a_name="A",
        group_b_name="B",
    )
    assert not is_valid
    assert "Raw RNA-seq counts require a validated count-based statistical workflow, such as DESeq2. This analysis is not available yet." in err


def test_design_validation_ambiguous_orientation_rejected():
    """Ambiguous orientation must be rejected until confirmed."""
    sample_ids = ["S1", "S2", "S3", "S4", "S5", "S6"]
    groups = {"S1": "A", "S2": "A", "S3": "A", "S4": "B", "S5": "B", "S6": "B"}

    is_valid, err, _, _ = validate_differential_expression_design(
        dataset_orientation="ambiguous",
        scale_inference="log2_transformed",
        group_mappings=groups,
        sample_ids=sample_ids,
        group_a_name="A",
        group_b_name="B",
    )
    assert not is_valid
    assert "orientation is ambiguous" in err.lower()


def test_design_validation_insufficient_group_samples():
    """Fewer than 3 samples in either group must be rejected."""
    sample_ids = ["S1", "S2", "S3", "S4", "S5"]
    groups = {"S1": "A", "S2": "A", "S3": "B", "S4": "B", "S5": "B"}  # Group A has only 2

    is_valid, err, _, _ = validate_differential_expression_design(
        dataset_orientation="features_as_rows",
        scale_inference="log2_transformed",
        group_mappings=groups,
        sample_ids=sample_ids,
        group_a_name="A",
        group_b_name="B",
        min_samples=3,
    )
    assert not is_valid
    assert "Minimum 3 required" in err


# =====================================================================
# 3. Security, Access Control & Reproducibility Tests
# =====================================================================

def test_cross_researcher_experiment_isolation(client, db_session):
    """Researcher B cannot access or view Researcher A's experiments or results."""
    user_a = User(
        email="res_alice@neuroforge.org",
        hashed_password=get_password_hash("PassAlice123"),
        full_name="Alice Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    user_b = User(
        email="res_bob@neuroforge.org",
        hashed_password=get_password_hash("PassBob123"),
        full_name="Bob Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add_all([user_a, user_b])
    db_session.commit()

    token_a = create_access_token(user_a.id, user_a.role)
    token_b = create_access_token(user_b.id, user_b.role)

    project_a = Project(title="Alice Project", owner_id=user_a.id)
    db_session.add(project_a)
    db_session.commit()

    # Create experiment owned by Alice
    exp_a = Experiment(
        project_id=project_a.id,
        owner_id=user_a.id,
        title="Alice Differential Screen",
        code="print('Alice analysis')",
        status=ExperimentStatus.COMPLETED.value,
        experiment_type="differential_expression_welch",
    )
    db_session.add(exp_a)
    db_session.commit()

    # Bob attempts to inspect Alice's experiment -> 403 Forbidden
    headers_b = {"Authorization": f"Bearer {token_b}"}
    res_bob_get = client.get(f"/experiments/{exp_a.id}", headers=headers_b)
    assert res_bob_get.status_code == 403

    res_bob_results = client.get(f"/experiments/{exp_a.id}/results", headers=headers_b)
    assert res_bob_results.status_code == 403

    # Alice CAN inspect her experiment -> 200 OK
    headers_a = {"Authorization": f"Bearer {token_a}"}
    res_alice_get = client.get(f"/experiments/{exp_a.id}", headers=headers_a)
    assert res_alice_get.status_code == 200


def test_admin_global_experiment_access(client, db_session):
    """Administrator can inspect any experiment."""
    admin = User(
        email="admin_chief@neuroforge.org",
        hashed_password=get_password_hash("AdminPass123"),
        full_name="Admin Chief",
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    researcher = User(
        email="res_charlie@neuroforge.org",
        hashed_password=get_password_hash("CharPass123"),
        full_name="Charlie Researcher",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add_all([admin, researcher])
    db_session.commit()

    admin_token = create_access_token(admin.id, admin.role)
    project = Project(title="Charlie Oncology", owner_id=researcher.id)
    db_session.add(project)
    db_session.commit()

    exp = Experiment(
        project_id=project.id,
        owner_id=researcher.id,
        title="Charlie Experiment",
        code="print('Charlie')",
        status=ExperimentStatus.COMPLETED.value,
    )
    db_session.add(exp)
    db_session.commit()

    # Admin accesses Charlie's experiment -> 200 OK
    adm_headers = {"Authorization": f"Bearer {admin_token}"}
    res = client.get(f"/experiments/{exp.id}", headers=adm_headers)
    assert res.status_code == 200


def test_reproducibility_manifest_and_results_endpoint(client, db_session):
    """Verify that completed experiment results endpoint returns structured feature stats and manifest."""
    researcher = User(
        email="repro_scientist@neuroforge.org",
        hashed_password=get_password_hash("ValidPass123"),
        full_name="Dr. Reproducibility",
        role=UserRole.RESEARCHER.value,
        is_active=True,
    )
    db_session.add(researcher)
    db_session.commit()
    token = create_access_token(researcher.id, researcher.role)
    headers = {"Authorization": f"Bearer {token}"}

    project = Project(title="Reproducibility Audit Project", owner_id=researcher.id)
    db_session.add(project)
    db_session.commit()

    manifest_data = {
        "dataset_id": "test_dataset_123",
        "dataset_hash": "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0",
        "statistical_method": "Welch's two-sample t-test (two-sided)",
        "group_a_name": "Control",
        "group_b_name": "Tumor",
        "alpha": 0.05,
        "fdr_threshold": 0.05,
    }
    stats_data = {
        "total_features_tested": 100,
        "significant_features_count": 12,
        "upregulated_count": 8,
        "downregulated_count": 4,
    }

    exp = Experiment(
        project_id=project.id,
        owner_id=researcher.id,
        title="Audited Differential Screen",
        code="print('Audit complete')",
        status=ExperimentStatus.COMPLETED.value,
        dataset_hash=manifest_data["dataset_hash"],
        reproducibility_manifest=json.dumps(manifest_data),
        statistical_summary=json.dumps(stats_data),
    )
    db_session.add(exp)
    db_session.commit()

    res = client.get(f"/experiments/{exp.id}/results", headers=headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["status"] == "Completed"
    assert detail["reproducibility_manifest"]["statistical_method"] == "Welch's two-sample t-test (two-sided)"
    assert detail["statistical_summary"]["significant_features_count"] == 12
    assert detail["dataset_hash"] == manifest_data["dataset_hash"]


def test_sandbox_symlink_artifact_blocking():
    """Verify that symlinks created inside the container sandbox cannot be ingested as artifacts."""
    from app.services.sandbox import SandboxExecutionService

    symlink_script = """
import os
try:
    os.symlink("/etc/hosts", "/workspace/symlink_artifact.txt")
except Exception as e:
    print(f"Symlink failed: {e}")
with open("/workspace/valid_result.txt", "w") as f:
    f.write("Valid scientific output")
"""
    result = SandboxExecutionService.execute(
        experiment_id="test_symlink_security",
        code=symlink_script,
    )

    artifact_names = [a["filename"] for a in result.artifacts]
    # The valid output file is captured
    assert "valid_result.txt" in artifact_names
    # The symlink is strictly rejected
    assert "symlink_artifact.txt" not in artifact_names

