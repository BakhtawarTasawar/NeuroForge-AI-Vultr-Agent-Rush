import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


@dataclass
class DistributionStats:
    min_val: float
    max_val: float
    mean_val: float
    median_val: float
    q25_val: float
    q75_val: float
    std_val: float
    sparsity_percent: float  # Percentage of exact zeros
    scale_inference: str     # "log2_transformed", "raw_counts", "normalized_continuous", "mixed_or_unknown"
    scale_explanation: str


@dataclass
class SampleQualitySummary:
    sample_id: str
    mean_val: float
    median_val: float
    std_val: float
    missing_count: int
    zero_count: int
    mean_cohort_correlation: Optional[float] = None
    is_potential_outlier: bool = False
    outlier_reason: Optional[str] = None


@dataclass
class PCACoordinate:
    sample_id: str
    pc1: float
    pc2: float
    group: Optional[str] = None


@dataclass
class PCAResult:
    pc1_variance_ratio: float
    pc2_variance_ratio: float
    total_explained_variance: float
    coordinates: List[PCACoordinate] = field(default_factory=list)


@dataclass
class GroupValidationResult:
    readiness_state: str  # metadata_incomplete, unsupported_data_type, unsupported_design, insufficient_samples, ready_for_exploratory_analysis, analysis_completed
    is_ready_for_testing: bool
    groups: Dict[str, int]
    control_group: Optional[str]
    treatment_group: Optional[str]
    assigned_samples_count: int
    unassigned_samples_count: int
    sample_counts_valid: bool
    data_scale_valid_for_welch: bool
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)


@dataclass
class QualityAssessmentResult:
    total_features: int
    total_samples: int
    total_cells: int
    missing_cells_count: int
    missing_cells_percent: float
    features_with_missing_count: int
    samples_with_missing_count: int
    constant_features_count: int
    constant_features_sample: List[str]
    distribution: DistributionStats
    samples_summary: List[SampleQualitySummary]
    cohort_mean_correlation: Optional[float]
    potential_outliers: List[str]
    pca: Optional[PCAResult]
    group_validation: Optional[GroupValidationResult]
    overall_health_status: str  # "Excellent", "Good", "Needs Review", "Critical Issues"
    summary_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_scale(values: np.ndarray) -> Tuple[str, str]:
    """
    Infer scale deterministically:
    - Raw RNA-seq count data: non-negative integers, large dynamic range (e.g. max > 500), high sparsity.
    - Log2 transformed: range usually within [0, 30] or [-5, 30].
    - Normalized continuous: float values with decimal precision.
    """
    valid = values[~np.isnan(values)]
    if len(valid) == 0:
        return "mixed_or_unknown", "Matrix contains only missing or invalid numeric values."

    min_v = float(np.min(valid))
    max_v = float(np.max(valid))

    # Check integer nature (sample 1000 values)
    sample_size = min(len(valid), 1000)
    sample_vals = valid[:sample_size]
    is_mostly_integers = np.all(np.isclose(sample_vals, np.round(sample_vals), atol=1e-5))

    if min_v >= 0 and max_v > 500 and is_mostly_integers:
        return (
            "raw_counts",
            "Values appear to be unnormalized raw sequencing counts (non-negative integer values with large dynamic range). "
            "Note: Standard Welch's t-test assumes continuous normalized distribution and is not statistically sound for raw counts. "
            "Count-based differential expression (e.g., negative binomial modeling / DESeq2) or log2 normalization is recommended."
        )

    if min_v >= -2.0 and max_v <= 35.0:
        return (
            "log2_transformed",
            f"Values have a dynamic range [min: {min_v:.2f}, max: {max_v:.2f}] consistent with log2-transformed continuous expression (e.g., log2(TPM+1), log2(FPKM+1), or normalized microarray intensities). Appropriate for Welch's t-test."
        )

    return (
        "normalized_continuous",
        f"Values represent continuous numerical measurements with range [{min_v:.2f}, {max_v:.2f}]."
    )


def compute_pca(
    matrix_df: pd.DataFrame,
    group_mappings: Optional[Dict[str, str]] = None,
    max_pca_features: int = 2000,
) -> Optional[PCAResult]:
    """
    Compute 2D PCA projection across samples.
    Input matrix: features (rows) x samples (columns).
    Transposed for PCA: samples (rows) x features (columns).
    For high-dimensional matrices, bounds PCA to top variable features to avoid memory spikes.
    """
    try:
        # If feature dimension is high, select top high-variance features deterministically
        if len(matrix_df) > max_pca_features:
            variances = matrix_df.var(axis=1, skipna=True)
            top_idx = variances.nlargest(max_pca_features).index
            work_matrix = matrix_df.loc[top_idx]
        else:
            work_matrix = matrix_df

        # Transpose: samples as observations, features as variables
        sample_df = work_matrix.T

        if len(sample_df) < 2 or len(sample_df.columns) < 2:
            return None

        # Impute missing values with feature mean
        imputer = SimpleImputer(strategy="mean")
        imputed_data = imputer.fit_transform(sample_df.values)

        # Standardize features (scale)
        scaler = StandardScaler(with_mean=True, with_std=True)
        scaled_data = scaler.fit_transform(imputed_data)

        # Replace any residual NaNs or Infs
        scaled_data = np.nan_to_num(scaled_data, nan=0.0, posinf=0.0, neginf=0.0)

        n_components = min(2, len(sample_df), len(sample_df.columns))
        pca = PCA(n_components=n_components)
        pca_coords = pca.fit_transform(scaled_data)

        var_ratios = pca.explained_variance_ratio_
        pc1_var = float(var_ratios[0]) if len(var_ratios) > 0 else 0.0
        pc2_var = float(var_ratios[1]) if len(var_ratios) > 1 else 0.0

        coords = []
        for i, sample_id in enumerate(sample_df.index):
            pc1_val = float(pca_coords[i, 0])
            pc2_val = float(pca_coords[i, 1]) if n_components > 1 else 0.0
            group_val = group_mappings.get(str(sample_id)) if group_mappings else None
            coords.append(
                PCACoordinate(
                    sample_id=str(sample_id),
                    pc1=round(pc1_val, 4),
                    pc2=round(pc2_val, 4),
                    group=group_val,
                )
            )

        return PCAResult(
            pc1_variance_ratio=round(pc1_var, 4),
            pc2_variance_ratio=round(pc2_var, 4),
            total_explained_variance=round(pc1_var + pc2_var, 4),
            coordinates=coords,
        )
    except Exception:
        return None


def validate_group_mappings(
    sample_ids: List[str],
    group_mappings: Optional[Dict[str, str]],
    scale_inference: str,
    control_group_name: Optional[str] = None,
    treatment_group_name: Optional[str] = None,
) -> GroupValidationResult:
    """
    Validate experimental group assignment.
    Ensures exactly two comparison groups, minimum 3 independent samples per group for Welch's t-test,
    continuous normalized data scale, and tracks assigned vs unassigned samples.
    """
    sample_set = set(sample_ids)
    assigned_count = 0
    group_counts: Dict[str, int] = {}

    if group_mappings:
        for sid, grp in group_mappings.items():
            if sid in sample_set and grp and str(grp).strip():
                clean_grp = str(grp).strip()
                group_counts[clean_grp] = group_counts.get(clean_grp, 0) + 1
                assigned_count += 1

    unassigned_count = max(0, len(sample_ids) - assigned_count)

    # General scientific caveats
    caveats = [
        "Statistical readiness for exploratory screening verifies structural compatibility with Welch's t-test (N >= 3 per group on continuous data).",
        "It does not guarantee statistical power, biological validity, or generalizability of findings.",
        "Confirmatory testing with orthogonal experimental methods (e.g. qPCR, targeted proteomics) is required for biological conclusions.",
    ]

    if not group_mappings or len(group_counts) == 0:
        return GroupValidationResult(
            readiness_state="metadata_incomplete",
            is_ready_for_testing=False,
            groups={},
            control_group=None,
            treatment_group=None,
            assigned_samples_count=0,
            unassigned_samples_count=len(sample_ids),
            sample_counts_valid=False,
            data_scale_valid_for_welch=(scale_inference != "raw_counts"),
            warnings=["No sample group assignments configured yet. Samples must be explicitly assigned to comparison groups."],
            recommendations=["Assign at least 3 samples to Group A (e.g. Control) and at least 3 samples to Group B (e.g. Treatment)."],
            caveats=caveats,
        )

    # Check for unsupported design: more than 2 groups
    if len(group_counts) > 2:
        return GroupValidationResult(
            readiness_state="unsupported_design",
            is_ready_for_testing=False,
            groups=group_counts,
            control_group=control_group_name,
            treatment_group=treatment_group_name,
            assigned_samples_count=assigned_count,
            unassigned_samples_count=unassigned_count,
            sample_counts_valid=False,
            data_scale_valid_for_welch=(scale_inference != "raw_counts"),
            warnings=[f"Multi-group designs ({len(group_counts)} groups detected: {', '.join(group_counts.keys())}) are not supported in this two-group screening workflow."],
            recommendations=["Select exactly two distinct comparison groups (e.g., Control vs Treatment) for two-sample Welch's t-test analysis."],
            caveats=caveats,
        )

    if len(group_counts) < 2:
        return GroupValidationResult(
            readiness_state="metadata_incomplete",
            is_ready_for_testing=False,
            groups=group_counts,
            control_group=control_group_name,
            treatment_group=treatment_group_name,
            assigned_samples_count=assigned_count,
            unassigned_samples_count=unassigned_count,
            sample_counts_valid=False,
            data_scale_valid_for_welch=(scale_inference != "raw_counts"),
            warnings=["Only one group has assigned samples. Two distinct comparison groups are required for differential expression."],
            recommendations=["Assign samples to a second comparison group (minimum 3 samples per group)."],
            caveats=caveats,
        )

    # Identify comparison groups
    sorted_grps = sorted(group_counts.keys(), key=lambda k: group_counts[k], reverse=True)
    ctrl = control_group_name if (control_group_name and control_group_name in group_counts) else sorted_grps[0]
    treat = treatment_group_name if (treatment_group_name and treatment_group_name in group_counts and treatment_group_name != ctrl) else (sorted_grps[1] if sorted_grps[1] != ctrl else sorted_grps[0])

    ctrl_count = group_counts.get(ctrl, 0)
    treat_count = group_counts.get(treat, 0)

    warnings: List[str] = []
    recommendations: List[str] = []

    # Check data scale
    scale_valid_for_welch = (scale_inference != "raw_counts")
    if not scale_valid_for_welch:
        warnings.append(
            "Raw RNA-seq counts require a validated count-based statistical workflow, such as DESeq2. This analysis is not available yet. Welch's t-test requires log2-normalized continuous data."
        )
        recommendations.append(
            "Apply log2 transformation (log2(counts + 1)) or wait for count-based negative binomial modeling (DESeq2 pipeline pending) before statistical testing."
        )
        return GroupValidationResult(
            readiness_state="unsupported_data_type",
            is_ready_for_testing=False,
            groups=group_counts,
            control_group=ctrl,
            treatment_group=treat,
            assigned_samples_count=assigned_count,
            unassigned_samples_count=unassigned_count,
            sample_counts_valid=(ctrl_count >= 3 and treat_count >= 3),
            data_scale_valid_for_welch=False,
            warnings=warnings,
            recommendations=recommendations,
            caveats=caveats,
        )

    # Check sample size adequacy
    sample_counts_valid = True
    if ctrl_count < 3:
        sample_counts_valid = False
        warnings.append(
            f"Group '{ctrl}' contains {ctrl_count} sample(s). Minimum 3 independent samples per group are required for Welch's t-test degrees of freedom."
        )
    if treat_count < 3:
        sample_counts_valid = False
        warnings.append(
            f"Group '{treat}' contains {treat_count} sample(s). Minimum 3 independent samples per group are required for Welch's t-test degrees of freedom."
        )

    if not sample_counts_valid:
        recommendations.append(
            "Increase sample size to at least 3 independent biological replicates per comparison group."
        )
        return GroupValidationResult(
            readiness_state="insufficient_samples",
            is_ready_for_testing=False,
            groups=group_counts,
            control_group=ctrl,
            treatment_group=treat,
            assigned_samples_count=assigned_count,
            unassigned_samples_count=unassigned_count,
            sample_counts_valid=False,
            data_scale_valid_for_welch=True,
            warnings=warnings,
            recommendations=recommendations,
            caveats=caveats,
        )

    recommendations.append(
        f"Design is ready for exploratory screening ({ctrl}: {ctrl_count} samples vs {treat}: {treat_count} samples). Unassigned samples: {unassigned_count}."
    )

    return GroupValidationResult(
        readiness_state="ready_for_exploratory_analysis",
        is_ready_for_testing=True,
        groups=group_counts,
        control_group=ctrl,
        treatment_group=treat,
        assigned_samples_count=assigned_count,
        unassigned_samples_count=unassigned_count,
        sample_counts_valid=True,
        data_scale_valid_for_welch=True,
        warnings=warnings,
        recommendations=recommendations,
        caveats=caveats,
    )


def compute_dataset_quality(
    matrix_df: pd.DataFrame,
    group_mappings: Optional[Dict[str, str]] = None,
    control_group: Optional[str] = None,
    treatment_group: Optional[str] = None,
) -> QualityAssessmentResult:
    """
    Perform deterministic scientific dataset quality assessment.
    matrix_df must be formatted as features (rows) x samples (columns).
    """
    total_features, total_samples = matrix_df.shape
    total_cells = total_features * total_samples

    # 1. Missingness & Numeric Validity
    missing_cells = int(matrix_df.isna().sum().sum())
    missing_percent = round((missing_cells / total_cells * 100.0) if total_cells > 0 else 0.0, 2)

    features_with_missing = int((matrix_df.isna().sum(axis=1) > 0).sum())
    samples_with_missing = int((matrix_df.isna().sum(axis=0) > 0).sum())

    # 2. Constant / Zero-variance Features
    feature_variances = matrix_df.var(axis=1, skipna=True)
    constant_mask = (feature_variances == 0) | feature_variances.isna()
    constant_features_count = int(constant_mask.sum())
    constant_features_sample = list(matrix_df.index[constant_mask][:10])

    # 3. Overall Value Distributions & Sparsity
    sampled_distribution = False
    if total_cells <= 500_000:
        flat_values = matrix_df.to_numpy().flatten()
        valid_values = flat_values[~np.isnan(flat_values)]

        if len(valid_values) > 0:
            min_v = float(np.min(valid_values))
            max_v = float(np.max(valid_values))
            mean_v = float(np.mean(valid_values))
            median_v = float(np.median(valid_values))
            q25_v = float(np.percentile(valid_values, 25))
            q75_v = float(np.percentile(valid_values, 75))
            std_v = float(np.std(valid_values))
            zero_cells = int((valid_values == 0).sum())
            sparsity = round((zero_cells / len(valid_values) * 100.0), 2)
        else:
            min_v = max_v = mean_v = median_v = q25_v = q75_v = std_v = 0.0
            sparsity = 0.0

        scale_type, scale_msg = evaluate_scale(valid_values)
    else:
        # Bounded evaluation for large matrices: compute extrema/zeros without full flatten
        col_mins = matrix_df.min(skipna=True)
        col_maxs = matrix_df.max(skipna=True)
        min_v = float(col_mins.min()) if len(col_mins) > 0 and not col_mins.isna().all() else 0.0
        max_v = float(col_maxs.max()) if len(col_maxs) > 0 and not col_maxs.isna().all() else 0.0
        zero_cells = int((matrix_df == 0).sum().sum())
        valid_cells_count = max(0, total_cells - missing_cells)
        sparsity = round((zero_cells / valid_cells_count * 100.0) if valid_cells_count > 0 else 0.0, 2)

        # Deterministic systematic sampling across rows
        row_step = max(1, total_features // 1000)
        sampled_slice = matrix_df.iloc[::row_step]
        sample_flat = sampled_slice.to_numpy().flatten()
        valid_sample = sample_flat[~np.isnan(sample_flat)]
        if len(valid_sample) > 500_000:
            valid_sample = valid_sample[:500_000]

        if len(valid_sample) > 0:
            mean_v = float(np.mean(valid_sample))
            median_v = float(np.median(valid_sample))
            q25_v = float(np.percentile(valid_sample, 25))
            q75_v = float(np.percentile(valid_sample, 75))
            std_v = float(np.std(valid_sample))
        else:
            mean_v = median_v = q25_v = q75_v = std_v = 0.0

        scale_type, scale_msg = evaluate_scale(valid_sample)
        sampled_distribution = True

    dist_stats = DistributionStats(
        min_val=round(min_v, 4),
        max_val=round(max_v, 4),
        mean_val=round(mean_v, 4),
        median_val=round(median_v, 4),
        q25_val=round(q25_v, 4),
        q75_val=round(q75_v, 4),
        std_val=round(std_v, 4),
        sparsity_percent=sparsity,
        scale_inference=scale_type,
        scale_explanation=scale_msg,
    )

    # 4. Per-sample Statistics and Inter-sample Correlation
    sample_summaries: List[SampleQualitySummary] = []
    
    # Bound correlation calculation to top 2,000 informative features if matrix is large
    bounded_features = False
    if total_features > 2000:
        top_corr_feat = feature_variances.nlargest(2000).index
        corr_matrix_df = matrix_df.loc[top_corr_feat]
        bounded_features = True
    else:
        corr_matrix_df = matrix_df

    corr_df = corr_matrix_df.dropna()
    if len(corr_df) < 10 and len(corr_matrix_df) >= 10:
        # Fast vectorized median imputation across rows
        row_medians = corr_matrix_df.median(axis=1)
        corr_df = corr_matrix_df.T.fillna(row_medians).T.dropna()

    correlation_matrix: Optional[pd.DataFrame] = None
    if len(corr_df) >= 3 and total_samples >= 2:
        try:
            correlation_matrix = corr_df.corr(method="pearson")
        except Exception:
            correlation_matrix = None

    sample_mean_corrs: Dict[str, float] = {}
    if correlation_matrix is not None:
        for sid in matrix_df.columns:
            # Average correlation with other samples (excluding self correlation = 1.0)
            other_corrs = correlation_matrix.loc[sid].drop(labels=[sid], errors="ignore")
            if len(other_corrs) > 0:
                sample_mean_corrs[str(sid)] = float(other_corrs.mean())

    cohort_mean_corr = None
    if sample_mean_corrs:
        all_corrs = list(sample_mean_corrs.values())
        cohort_mean_corr = round(float(np.mean(all_corrs)), 4)
        cohort_std_corr = float(np.std(all_corrs))
    else:
        cohort_std_corr = 0.0

    # 5. Outlier Detection (Non-fatal, advisory flag)
    potential_outliers: List[str] = []
    for sid in matrix_df.columns:
        col = matrix_df[sid]
        valid_col = col.dropna()
        c_mean = float(valid_col.mean()) if len(valid_col) > 0 else 0.0
        c_med = float(valid_col.median()) if len(valid_col) > 0 else 0.0
        c_std = float(valid_col.std()) if len(valid_col) > 1 else 0.0
        c_missing = int(col.isna().sum())
        c_zeros = int((valid_col == 0).sum())

        s_mean_corr = sample_mean_corrs.get(str(sid))
        is_outlier = False
        outlier_reason = None

        if s_mean_corr is not None and cohort_mean_corr is not None and cohort_std_corr > 1e-4 and total_samples >= 4:
            # If sample correlation is > 2 standard deviations below cohort mean
            if s_mean_corr < (cohort_mean_corr - 2.0 * cohort_std_corr):
                is_outlier = True
                outlier_reason = (
                    f"Sample correlation with cohort ({s_mean_corr:.3f}) is >2 std deviations below cohort mean ({cohort_mean_corr:.3f}). "
                    "May represent biological heterogeneity or technical artifact. Researcher review advised."
                )
                potential_outliers.append(str(sid))

        sample_summaries.append(
            SampleQualitySummary(
                sample_id=str(sid),
                mean_val=round(c_mean, 4),
                median_val=round(c_med, 4),
                std_val=round(c_std, 4),
                missing_count=c_missing,
                zero_count=c_zeros,
                mean_cohort_correlation=round(s_mean_corr, 4) if s_mean_corr is not None else None,
                is_potential_outlier=is_outlier,
                outlier_reason=outlier_reason,
            )
        )

    # 6. PCA
    pca_result = compute_pca(matrix_df, group_mappings)

    # 7. Group Validation
    group_val = validate_group_mappings(
        sample_ids=[str(s) for s in matrix_df.columns],
        group_mappings=group_mappings,
        scale_inference=scale_type,
        control_group_name=control_group,
        treatment_group_name=treatment_group,
    )

    # 8. Overall Health Status
    summary_notes = []
    if missing_percent > 20.0:
        health_status = "Critical Issues"
        summary_notes.append(f"High missingness ({missing_percent}% of cells are missing). Quality may impair downstream statistics.")
    elif constant_features_count > (total_features * 0.5):
        health_status = "Needs Review"
        summary_notes.append(f"Over 50% of features have zero variance ({constant_features_count} features).")
    elif potential_outliers:
        health_status = "Needs Review"
        summary_notes.append(f"Identified {len(potential_outliers)} potential sample quality outlier(s) based on correlation distance.")
    elif missing_percent > 2.0:
        health_status = "Good"
        summary_notes.append(f"Low missingness ({missing_percent}%). Recommend standard imputation before model training.")
    else:
        health_status = "Excellent"
        summary_notes.append("Dataset is clean with complete matrix dimensions and balanced distributions.")

    if sampled_distribution:
        summary_notes.append(
            f"High-dimensional matrix ({total_features} features x {total_samples} samples): "
            "Distribution stats evaluated via deterministic bounded systematic sampling."
        )

    if bounded_features:
        summary_notes.append(
            f"Inter-sample correlation and PCA bounded to top 2,000 variable features "
            f"(out of {total_features} total features) for O(1) performance scalability."
        )

    return QualityAssessmentResult(
        total_features=total_features,
        total_samples=total_samples,
        total_cells=total_cells,
        missing_cells_count=missing_cells,
        missing_cells_percent=missing_percent,
        features_with_missing_count=features_with_missing,
        samples_with_missing_count=samples_with_missing,
        constant_features_count=constant_features_count,
        constant_features_sample=constant_features_sample,
        distribution=dist_stats,
        samples_summary=sample_summaries,
        cohort_mean_correlation=cohort_mean_corr,
        potential_outliers=potential_outliers,
        pca=pca_result,
        group_validation=group_val,
        overall_health_status=health_status,
        summary_notes=summary_notes,
    )

