import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import scipy
import scipy.stats as stats
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


@dataclass
class FeatureStatisticalResult:
    feature_id: str
    n_a: int
    n_b: int
    mean_a: float
    mean_b: float
    mean_diff: float
    log2_fc: Optional[float]
    t_stat: Optional[float]
    df: Optional[float]
    p_value: Optional[float]
    adj_p_value: Optional[float]
    ci_lower: Optional[float]
    ci_upper: Optional[float]
    cohens_d: Optional[float]
    hedges_g: Optional[float]
    status: str  # "computed", "constant_feature", "insufficient_observations", "invalid_numeric"
    is_significant: bool = False
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReproducibilityManifest:
    dataset_id: str
    dataset_hash: str
    experiment_type: str
    statistical_method: str
    group_a_name: str
    group_b_name: str
    group_a_samples: List[str]
    group_b_samples: List[str]
    unassigned_samples: List[str]
    scale_inference: str
    is_log2_scale: bool
    missing_value_policy: str
    multiple_testing_correction: str
    alpha: float
    fdr_threshold: float
    min_samples_per_group: int
    software_environment: Dict[str, str]
    timestamp: str
    effect_size_convention: str = (
        "Hedges' g with pooled variance s_pooled = sqrt(((n_A - 1)*s_A^2 + (n_B - 1)*s_B^2)/(n_A + n_B - 2)) "
        "and small-sample correction factor J(df) = 1 - 3/(4*df - 1)"
    )
    preprocessing_configuration: Dict[str, Any] = field(default_factory=lambda: {
        "imputation": "pairwise_finite_exclusion",
        "standardization": "feature_wise_unit_variance_where_nonzero",
        "log2_fold_change_rule": "difference_of_means_if_log2_else_log2_ratio_if_positive",
    })

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PCAResult:
    coordinates: List[List[float]]
    sample_ids: List[str]
    explained_variance_ratio: List[float]
    total_variance_explained: float
    n_components: int
    preprocessing_notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DifferentialExpressionSummary:
    experiment_type: str
    dataset_id: str
    dataset_hash: str
    group_a_name: str
    group_b_name: str
    group_a_count: int
    group_b_count: int
    unassigned_count: int
    total_features_tested: int
    significant_features_count: int  # FDR <= fdr_threshold
    upregulated_count: int           # FDR <= fdr_threshold and log2_fc > 0
    downregulated_count: int         # FDR <= fdr_threshold and log2_fc < 0
    constant_features_count: int
    fdr_threshold: float
    alpha: float
    reproducibility_manifest: ReproducibilityManifest
    top_features: List[FeatureStatisticalResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def benjamini_hochberg_correction(p_values: List[Optional[float]]) -> List[Optional[float]]:
    """
    Correct multiple hypothesis tests using the Benjamini-Hochberg (1995) procedure (FDR).
    Ranks valid p-values, computes q = p * (m / rank), and enforces step-down monotonicity.
    Preserves exact positions of input p-values, mapping NaNs/Nones to None.
    Determinism guaranteed by stable sort key (p_value, original_index).
    Only valid finite p-values in [0.0, 1.0] are included in the hypothesis count m.
    """
    n_total = len(p_values)
    if n_total == 0:
        return []

    # Extract valid entries
    valid_entries: List[Tuple[int, float]] = []
    for idx, p in enumerate(p_values):
        if p is not None and not math.isnan(p) and not math.isinf(p) and 0.0 <= p <= 1.0:
            valid_entries.append((idx, float(p)))

    m = len(valid_entries)
    if m == 0:
        return [None] * n_total

    # Sort ascending by p-value, using original index as secondary key for strict determinism
    valid_entries.sort(key=lambda item: (item[1], item[0]))

    # Compute raw Benjamini-Hochberg q-factors: q_(i) = min(1.0, p_(i) * m / rank)
    q_factors: List[float] = []
    for rank_1based, (_, p_val) in enumerate(valid_entries, start=1):
        q = min(1.0, p_val * (m / rank_1based))
        q_factors.append(q)

    # Enforce monotonicity downwards from m-2 down to 0
    for i in range(m - 2, -1, -1):
        if q_factors[i] > q_factors[i + 1]:
            q_factors[i] = q_factors[i + 1]

    # Map back to original indices
    result: List[Optional[float]] = [None] * n_total
    for (orig_idx, _), q_val in zip(valid_entries, q_factors):
        result[orig_idx] = float(q_val)

    return result


def compute_welch_t_test(
    values_a: np.ndarray,
    values_b: np.ndarray,
    feature_id: str,
    is_log2_scale: bool = True,
    alpha: float = 0.05,
) -> FeatureStatisticalResult:
    """
    Perform Welch's independent two-sample t-test (unequal variances assumed).
    Calculates t-statistic, Welch-Satterthwaite degrees of freedom, raw two-tailed p-value
    using numerically stable survival function (2 * t.sf(abs(t), df)), confidence intervals
    for the mean difference (B - A), and Hedges' g effect size.

    Handles zero variance rigorously:
    - If BOTH groups have zero variance: standard error is zero; t, p, df, CI, and effect sizes are undefined (None).
    - If ONE group has zero variance and the other group has nonzero variance (with N >= 2):
      Welch's statistic is mathematically defined with df = N_nonzero - 1, and t, p, CI, and Hedges' g are computed.
    - If either group has < 2 valid observations: status is 'insufficient_observations'.
    """
    # Filter valid numeric entries
    a_clean = values_a[~np.isnan(values_a) & ~np.isinf(values_a)]
    b_clean = values_b[~np.isnan(values_b) & ~np.isinf(values_b)]

    n_a = len(a_clean)
    n_b = len(b_clean)

    if n_a < 2 or n_b < 2:
        return FeatureStatisticalResult(
            feature_id=feature_id,
            n_a=n_a,
            n_b=n_b,
            mean_a=float(np.mean(a_clean)) if n_a > 0 else 0.0,
            mean_b=float(np.mean(b_clean)) if n_b > 0 else 0.0,
            mean_diff=float(np.mean(b_clean) - np.mean(a_clean)) if (n_a > 0 and n_b > 0) else 0.0,
            log2_fc=None,
            t_stat=None,
            df=None,
            p_value=None,
            adj_p_value=None,
            ci_lower=None,
            ci_upper=None,
            cohens_d=None,
            hedges_g=None,
            status="insufficient_observations",
            notes=f"Insufficient observations (Group A: {n_a}, Group B: {n_b}; minimum 2 required for sample variance).",
        )

    mean_a = float(np.mean(a_clean))
    mean_b = float(np.mean(b_clean))
    mean_diff = mean_b - mean_a

    # Sample variance (ddof=1)
    var_a = float(np.var(a_clean, ddof=1))
    var_b = float(np.var(b_clean, ddof=1))

    # Standard error squared of the difference
    se_sq = (var_a / n_a) + (var_b / n_b)

    # Log2 fold change
    log2_fc: Optional[float] = None
    if is_log2_scale:
        log2_fc = round(mean_diff, 4)
    elif mean_a > 0 and mean_b > 0:
        log2_fc = round(math.log2(mean_b / mean_a), 4)
    else:
        log2_fc = None  # Non-positive values on linear scale

    # Case 1: Both groups have zero variance (or se_sq practically zero)
    if se_sq <= 1e-15 or (var_a <= 1e-15 and var_b <= 1e-15):
        if math.isclose(mean_a, mean_b, abs_tol=1e-8):
            reason = "Zero sample variance across all samples in both comparison groups; standard error is zero and t-statistic is mathematically undefined."
        else:
            reason = f"Both groups exhibit zero within-group variance with differing group means (A: {mean_a:.4f}, B: {mean_b:.4f}); standard error is zero and t-statistic is mathematically undefined."

        return FeatureStatisticalResult(
            feature_id=feature_id,
            n_a=n_a,
            n_b=n_b,
            mean_a=round(mean_a, 4),
            mean_b=round(mean_b, 4),
            mean_diff=round(mean_diff, 4),
            log2_fc=log2_fc,
            t_stat=None,
            df=None,
            p_value=None,
            adj_p_value=None,
            ci_lower=None,
            ci_upper=None,
            cohens_d=None,
            hedges_g=None,
            status="constant_feature",
            notes=reason,
        )

    # Case 2: One group has zero variance, but the other group has nonzero variance
    # Or Case 3: Both groups have nonzero variance
    se = math.sqrt(se_sq)
    t_stat = mean_diff / se

    # Welch-Satterthwaite degrees of freedom
    # Numerator is (s_A^2/n_A + s_B^2/n_B)^2 = se_sq^2
    # Denominator terms: (s_A^2/n_A)^2 / (n_A - 1) + (s_B^2/n_B)^2 / (n_B - 1)
    term_a = ((var_a / n_a) ** 2 / (n_a - 1)) if (var_a > 1e-15 and n_a > 1) else 0.0
    term_b = ((var_b / n_b) ** 2 / (n_b - 1)) if (var_b > 1e-15 and n_b > 1) else 0.0
    denom = term_a + term_b

    notes = None
    if denom <= 0:
        df = float(n_a + n_b - 2)
    else:
        df = (se_sq ** 2) / denom

    if var_a <= 1e-15:
        notes = f"Group A exhibited zero sample variance; Welch's t-test and effective degrees of freedom calculated from Group B variance (df = {df:.1f})."
    elif var_b <= 1e-15:
        notes = f"Group B exhibited zero sample variance; Welch's t-test and effective degrees of freedom calculated from Group A variance (df = {df:.1f})."

    # Numerically stable two-sided p-value via survival function: 2 * t.sf(abs(t), df)
    p_val = float(stats.t.sf(abs(t_stat), df) * 2.0)
    p_val = min(1.0, max(0.0, p_val))

    # Confidence interval for mean difference (1 - alpha)
    t_crit = float(stats.t.ppf(1.0 - alpha / 2.0, df))
    ci_lower = mean_diff - t_crit * se
    ci_upper = mean_diff + t_crit * se

    # Effect sizes: Cohen's d & Hedges' g using pooled standard deviation
    # s_pooled = sqrt( ((n_a - 1)*var_a + (n_b - 1)*var_b) / (n_a + n_b - 2) )
    df_pooled = n_a + n_b - 2
    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / df_pooled if df_pooled > 0 else 0.0

    if pooled_var > 0:
        s_pooled = math.sqrt(pooled_var)
        cohens_d = mean_diff / s_pooled
        # Hedges' g correction factor J(df_pooled) = 1 - 3 / (4 * df_pooled - 1)
        j_factor = 1.0 - (3.0 / (4.0 * df_pooled - 1.0)) if df_pooled >= 2 else 1.0
        hedges_g = cohens_d * j_factor
    else:
        cohens_d = None
        hedges_g = None

    return FeatureStatisticalResult(
        feature_id=feature_id,
        n_a=n_a,
        n_b=n_b,
        mean_a=round(mean_a, 4),
        mean_b=round(mean_b, 4),
        mean_diff=round(mean_diff, 4),
        log2_fc=log2_fc,
        t_stat=round(t_stat, 4),
        df=round(df, 2),
        p_value=float(p_val),
        adj_p_value=None,  # Populated after full multiple testing correction
        ci_lower=round(ci_lower, 4),
        ci_upper=round(ci_upper, 4),
        cohens_d=round(cohens_d, 4) if cohens_d is not None else None,
        hedges_g=round(hedges_g, 4) if hedges_g is not None else None,
        status="computed",
        notes=notes,
    )


def compute_pca_projection(
    df: pd.DataFrame,
    sample_ids: List[str],
    n_components: int = 2,
) -> PCAResult:
    """
    Fit exploratory Principal Component Analysis (PCA) on continuous sample-feature matrix.
    Orientation: df has features as rows and sample_ids as columns.
    Samples are transposed to rows (N samples x P features) for PCA fitting.
    Applies median imputation for missing values and safe standardization (excluding zero-variance features).
    """
    if len(sample_ids) < 2:
        raise ValueError(f"PCA requires at least 2 samples, received {len(sample_ids)}.")

    valid_cols = [c for c in sample_ids if c in df.columns]
    if len(valid_cols) < 2:
        raise ValueError("Fewer than 2 requested sample columns exist in the dataset matrix.")

    sub_df = df[valid_cols].copy()
    if len(sub_df) < 1:
        raise ValueError("Cannot perform PCA on an empty feature matrix.")

    # Transpose so rows are samples (N) and columns are features (P)
    sample_matrix = sub_df.T  # Shape: (N samples, P features)

    notes = []
    # 1. Imputation for missing values
    imputer = SimpleImputer(strategy="median")
    imputed_values = imputer.fit_transform(sample_matrix.values)
    n_missing = int(np.isnan(sample_matrix.values).sum())
    if n_missing > 0:
        notes.append(f"Imputed {n_missing} missing values using feature-wise medians.")

    # 2. Identify and handle constant features without producing NaNs
    feature_stds = np.std(imputed_values, axis=0, ddof=0)
    zero_std_mask = feature_stds <= 1e-12
    n_constant = int(np.sum(zero_std_mask))

    if n_constant > 0:
        notes.append(f"Handled {n_constant} zero-variance features by zero-centering without division by zero.")

    # Standardize non-constant features
    standardized = np.zeros_like(imputed_values)
    feature_means = np.mean(imputed_values, axis=0)

    for j in range(imputed_values.shape[1]):
        if zero_std_mask[j]:
            standardized[:, j] = 0.0
        else:
            standardized[:, j] = (imputed_values[:, j] - feature_means[j]) / feature_stds[j]

    # Number of components bounded by min(n_samples, n_features, requested)
    max_possible_comp = min(len(valid_cols), sub_df.shape[0])
    actual_components = min(n_components, max_possible_comp)
    if actual_components < 1:
        raise ValueError("Insufficient dimensions to compute principal components.")

    pca = PCA(n_components=actual_components)
    coords = pca.fit_transform(standardized)

    ev_ratio = [float(r) for r in pca.explained_variance_ratio_]
    tot_var = float(np.sum(ev_ratio))

    return PCAResult(
        coordinates=[[float(c) for c in row] for row in coords],
        sample_ids=valid_cols,
        explained_variance_ratio=ev_ratio,
        total_variance_explained=tot_var,
        n_components=actual_components,
        preprocessing_notes=notes,
    )


def validate_differential_expression_design(
    dataset_orientation: str,
    scale_inference: str,
    group_mappings: Dict[str, str],
    sample_ids: List[str],
    group_a_name: str,
    group_b_name: str,
    min_samples: int = 3,
) -> Tuple[bool, Optional[str], List[str], List[str]]:
    """
    Validate all scientific constraints before executing differential expression:
    1. Orientation must not be ambiguous.
    2. Data scale must not be unnormalized raw counts.
    3. Exactly two groups compared.
    4. Minimum samples threshold met.
    Returns: (is_valid, error_message, group_a_samples, group_b_samples)
    """
    if dataset_orientation == "ambiguous":
        return False, "Dataset orientation is ambiguous. Please confirm feature/sample orientation before running analysis.", [], []

    if scale_inference == "raw_counts":
        return False, "Raw RNA-seq counts require a validated count-based statistical workflow, such as DESeq2. This analysis is not available yet.", [], []

    sample_set = set(sample_ids)
    group_a_samples = [s for s, g in group_mappings.items() if g == group_a_name and s in sample_set]
    group_b_samples = [s for s, g in group_mappings.items() if g == group_b_name and s in sample_set]

    if not group_a_name or not group_b_name or group_a_name == group_b_name:
        return False, "Two distinct comparison groups (e.g. Group A vs Group B) must be specified.", [], []

    if len(group_a_samples) < min_samples:
        return False, f"Comparison Group '{group_a_name}' has only {len(group_a_samples)} sample(s). Minimum {min_samples} required for Welch's t-test.", [], []

    if len(group_b_samples) < min_samples:
        return False, f"Comparison Group '{group_b_name}' has only {len(group_b_samples)} sample(s). Minimum {min_samples} required for Welch's t-test.", [], []

    return True, None, group_a_samples, group_b_samples


def run_differential_expression(
    matrix_df: pd.DataFrame,
    group_mappings: Dict[str, str],
    group_a_name: str,
    group_b_name: str,
    dataset_id: str,
    dataset_hash: str,
    scale_inference: str = "log2_transformed",
    alpha: float = 0.05,
    fdr_threshold: float = 0.05,
    min_samples_per_group: int = 3,
) -> DifferentialExpressionSummary:
    """
    Execute full differential expression screening pipeline across all features:
    1. Validates experimental design.
    2. Runs Welch's t-test per feature.
    3. Corrects p-values using Benjamini-Hochberg (FDR).
    4. Evaluates significance against FDR threshold.
    5. Builds reproducibility manifest.
    """
    sample_ids = [str(c) for c in matrix_df.columns]
    is_valid, err, a_samples, b_samples = validate_differential_expression_design(
        dataset_orientation="features_as_rows",
        scale_inference=scale_inference,
        group_mappings=group_mappings,
        sample_ids=sample_ids,
        group_a_name=group_a_name,
        group_b_name=group_b_name,
        min_samples=min_samples_per_group,
    )
    if not is_valid:
        raise ValueError(err)

    is_log2 = (scale_inference == "log2_transformed")

    a_cols = [c for c in matrix_df.columns if str(c) in set(a_samples)]
    b_cols = [c for c in matrix_df.columns if str(c) in set(b_samples)]

    assigned_set = set(a_samples) | set(b_samples)
    unassigned_samples = [s for s in sample_ids if s not in assigned_set]

    # Pre-allocate results
    raw_results: List[FeatureStatisticalResult] = []
    p_values: List[Optional[float]] = []

    for feat_id, row in matrix_df.iterrows():
        vals_a = row[a_cols].to_numpy(dtype=float)
        vals_b = row[b_cols].to_numpy(dtype=float)

        res = compute_welch_t_test(
            values_a=vals_a,
            values_b=vals_b,
            feature_id=str(feat_id),
            is_log2_scale=is_log2,
            alpha=alpha,
        )
        raw_results.append(res)
        p_values.append(res.p_value)

    # Benjamini-Hochberg FDR correction
    adj_p_values = benjamini_hochberg_correction(p_values)

    sig_count = 0
    up_count = 0
    down_count = 0
    constant_count = 0

    for res, adj_p in zip(raw_results, adj_p_values):
        res.adj_p_value = adj_p
        if res.status == "constant_feature":
            constant_count += 1

        if adj_p is not None and adj_p <= fdr_threshold:
            res.is_significant = True
            sig_count += 1
            if res.log2_fc is not None:
                if res.log2_fc > 0:
                    up_count += 1
                elif res.log2_fc < 0:
                    down_count += 1

    # Sort results by adjusted p-value ascending (nulls last)
    sorted_results = sorted(
        raw_results,
        key=lambda r: (r.adj_p_value is None, r.adj_p_value if r.adj_p_value is not None else 1.0)
    )

    manifest = ReproducibilityManifest(
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        experiment_type="differential_expression_welch",
        statistical_method="Welch's independent two-sample t-test (two-sided, unequal variances)",
        group_a_name=group_a_name,
        group_b_name=group_b_name,
        group_a_samples=a_samples,
        group_b_samples=b_samples,
        unassigned_samples=unassigned_samples,
        scale_inference=scale_inference,
        is_log2_scale=is_log2,
        missing_value_policy="pair_wise_finite_only",
        multiple_testing_correction="Benjamini-Hochberg False Discovery Rate (FDR)",
        alpha=alpha,
        fdr_threshold=fdr_threshold,
        min_samples_per_group=min_samples_per_group,
        software_environment={
            "python": "3.14+",
            "scipy": scipy.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    warnings = []
    if constant_count > 0:
        warnings.append(f"{constant_count} features exhibited zero variance across both groups and were excluded from ranking.")
    if len(unassigned_samples) > 0:
        warnings.append(f"{len(unassigned_samples)} samples in the dataset were left unassigned and excluded from this two-group comparison.")

    limitations = [
        "Welch's t-test evaluates individual features independently and assumes continuous, approximately normal distributions.",
        "Significance at FDR threshold does not establish causality, biological mechanism, or diagnostic capability.",
        "Results are exploratory and require orthogonal biological validation.",
    ]

    return DifferentialExpressionSummary(
        experiment_type="differential_expression_welch",
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        group_a_name=group_a_name,
        group_b_name=group_b_name,
        group_a_count=len(a_samples),
        group_b_count=len(b_samples),
        unassigned_count=len(unassigned_samples),
        total_features_tested=len(raw_results),
        significant_features_count=sig_count,
        upregulated_count=up_count,
        downregulated_count=down_count,
        constant_features_count=constant_count,
        fdr_threshold=fdr_threshold,
        alpha=alpha,
        reproducibility_manifest=manifest,
        top_features=sorted_results[:50],  # Top 50 for quick display
        warnings=warnings,
        limitations=limitations,
    )


def generate_sandbox_script(
    group_mappings: Dict[str, str],
    group_a_name: str,
    group_b_name: str,
    dataset_id: str,
    dataset_hash: str,
    scale_inference: str,
    fdr_threshold: float = 0.05,
    alpha: float = 0.05,
) -> str:
    """
    Generate deterministic, standalone scientific Python script that executes
    inside the isolated Docker container. Generates CSV results, JSON summary,
    reproducibility manifest, Volcano plot, and PCA plot using genuine values.
    """
    # Serialize arguments safely
    group_map_json = json.dumps(group_mappings)
    
    script = f'''import json
import math
import sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import scipy
import scipy.stats as stats
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

print("Starting NeuroForge Scientific Analysis Engine inside isolated sandbox...")

DATASET_PATH = "/workspace/dataset.csv"
GROUP_MAPPINGS = {group_map_json}
GROUP_A = {json.dumps(group_a_name)}
GROUP_B = {json.dumps(group_b_name)}
DATASET_ID = {json.dumps(dataset_id)}
DATASET_HASH = {json.dumps(dataset_hash)}
SCALE_INFERENCE = {json.dumps(scale_inference)}
IS_LOG2 = (SCALE_INFERENCE == "log2_transformed")
FDR_THRESHOLD = {fdr_threshold}
ALPHA = {alpha}

# 1. Load dataset
try:
    df = pd.read_csv(DATASET_PATH, index_col=0, low_memory=False)
except Exception as e:
    print(f"Error loading matrix: {{e}}", file=sys.stderr)
    sys.exit(1)

sample_cols = [str(c) for c in df.columns]
group_a_cols = [c for c in df.columns if GROUP_MAPPINGS.get(str(c)) == GROUP_A]
group_b_cols = [c for c in df.columns if GROUP_MAPPINGS.get(str(c)) == GROUP_B]

print(f"Loaded matrix: {{len(df)}} features, {{len(df.columns)}} samples.")
print(f"Comparison design: '{{GROUP_A}}' (N={{len(group_a_cols)}}) vs '{{GROUP_B}}' (N={{len(group_b_cols)}}).")

if len(group_a_cols) < 2 or len(group_b_cols) < 2:
    print("Insufficient observations per group for Welch's t-test.", file=sys.stderr)
    sys.exit(1)

# 2. Welch's t-test per feature
features = []
records = []
p_vals = []
constant_count = 0

for feat_id, row in df.iterrows():
    va = row[group_a_cols].to_numpy(dtype=float)
    vb = row[group_b_cols].to_numpy(dtype=float)
    
    va_clean = va[~np.isnan(va) & ~np.isinf(va)]
    vb_clean = vb[~np.isnan(vb) & ~np.isinf(vb)]
    
    na = len(va_clean)
    nb = len(vb_clean)
    
    if na < 2 or nb < 2:
        records.append({{
            "feature_id": str(feat_id),
            "n_a": na,
            "n_b": nb,
            "mean_a": round(float(np.mean(va_clean)), 4) if na > 0 else 0.0,
            "mean_b": round(float(np.mean(vb_clean)), 4) if nb > 0 else 0.0,
            "mean_diff": round(float(np.mean(vb_clean) - np.mean(va_clean)), 4) if (na > 0 and nb > 0) else 0.0,
            "log2_fc": None,
            "t_stat": None,
            "df": None,
            "p_value": None,
            "ci_lower": None,
            "ci_upper": None,
            "hedges_g": None,
            "status": "insufficient_observations",
        }})
        continue
        
    ma = float(np.mean(va_clean))
    mb = float(np.mean(vb_clean))
    mdiff = mb - ma
    
    va_var = float(np.var(va_clean, ddof=1))
    vb_var = float(np.var(vb_clean, ddof=1))
    
    se_sq = (va_var / na) + (vb_var / nb)
    
    # Log2 FC
    log2_fc = round(mdiff, 4) if IS_LOG2 else (round(math.log2(mb / ma), 4) if (ma > 0 and mb > 0) else None)
    
    # Zero variance across both groups
    if se_sq <= 1e-15 or (va_var <= 1e-15 and vb_var <= 1e-15):
        constant_count += 1
        records.append({{
            "feature_id": str(feat_id),
            "n_a": na,
            "n_b": nb,
            "mean_a": round(ma, 4),
            "mean_b": round(mb, 4),
            "mean_diff": round(mdiff, 4),
            "log2_fc": log2_fc,
            "t_stat": None,
            "df": None,
            "p_value": None,
            "ci_lower": None,
            "ci_upper": None,
            "hedges_g": None,
            "status": "constant_feature",
        }})
        continue
        
    se = math.sqrt(se_sq)
    t = mdiff / se
    
    term_a = ((va_var / na)**2 / (na - 1)) if (va_var > 1e-15 and na > 1) else 0.0
    term_b = ((vb_var / nb)**2 / (nb - 1)) if (vb_var > 1e-15 and nb > 1) else 0.0
    denom = term_a + term_b
    df_val = (se_sq**2) / denom if denom > 0 else float(na + nb - 2)
    
    p = float(stats.t.sf(abs(t), df_val) * 2.0)
    p = min(1.0, max(0.0, p))
    
    # 95% CI
    t_crit = float(stats.t.ppf(1.0 - ALPHA / 2.0, df_val))
    ci_low = mdiff - t_crit * se
    ci_high = mdiff + t_crit * se
    
    # Hedges' g
    df_pooled = na + nb - 2
    pooled_var = ((na - 1)*va_var + (nb - 1)*vb_var) / df_pooled if df_pooled > 0 else 0.0
    if pooled_var > 0:
        s_pooled = math.sqrt(pooled_var)
        d = mdiff / s_pooled
        j_factor = 1.0 - (3.0 / (4.0*df_pooled - 1.0)) if df_pooled >= 2 else 1.0
        hedges_g = d * j_factor
    else:
        hedges_g = None
    
    features.append(str(feat_id))
    p_vals.append(p)
    records.append({{
        "feature_id": str(feat_id),
        "n_a": na,
        "n_b": nb,
        "mean_a": round(ma, 4),
        "mean_b": round(mb, 4),
        "mean_diff": round(mdiff, 4),
        "log2_fc": log2_fc,
        "t_stat": round(t, 4),
        "df": round(df_val, 2),
        "p_value": float(p),
        "ci_lower": round(ci_low, 4),
        "ci_upper": round(ci_high, 4),
        "hedges_g": round(hedges_g, 4) if hedges_g is not None else None,
        "status": "computed",
    }})

# 3. Benjamini-Hochberg FDR
m = len(p_vals)
if m > 0:
    valid_computed = [r for r in records if r.get("status") == "computed" and r.get("p_value") is not None]
    valid_p = [r["p_value"] for r in valid_computed]
    order = np.argsort(valid_p)
    sorted_p = np.array(valid_p)[order]
    q_vals = np.zeros(m)
    for rank_idx, p in enumerate(sorted_p, start=1):
        q_vals[rank_idx - 1] = min(1.0, p * (m / rank_idx))
    for i in range(m - 2, -1, -1):
        if q_vals[i] > q_vals[i + 1]:
            q_vals[i] = q_vals[i + 1]
    
    final_q = np.zeros(m)
    final_q[order] = q_vals
    for i, r in enumerate(valid_computed):
        r["adj_p_value"] = float(final_q[i])
        r["is_significant"] = bool(r["adj_p_value"] <= FDR_THRESHOLD)

# 4. Save CSV results
results_df = pd.DataFrame(records)
results_df.sort_values(by=["adj_p_value"], na_position="last", inplace=True)
results_df.to_csv("/workspace/differential_expression_results.csv", index=False)
print("Saved differential_expression_results.csv")

# 5. Save JSON summary & manifest
sig_df = results_df[results_df["is_significant"] == True] if "is_significant" in results_df else pd.DataFrame()
up_df = sig_df[sig_df["log2_fc"] > 0] if len(sig_df) > 0 and "log2_fc" in sig_df else pd.DataFrame()
down_df = sig_df[sig_df["log2_fc"] < 0] if len(sig_df) > 0 and "log2_fc" in sig_df else pd.DataFrame()

manifest = {{
    "dataset_id": DATASET_ID,
    "dataset_hash": DATASET_HASH,
    "experiment_type": "differential_expression_welch",
    "statistical_method": "Welch's independent two-sample t-test (two-sided, unequal variances)",
    "group_a_name": GROUP_A,
    "group_b_name": GROUP_B,
    "group_a_count": len(group_a_cols),
    "group_b_count": len(group_b_cols),
    "total_features_tested": len(records),
    "significant_features_count": len(sig_df),
    "upregulated_count": len(up_df),
    "downregulated_count": len(down_df),
    "constant_features_count": constant_count,
    "fdr_threshold": FDR_THRESHOLD,
    "alpha": ALPHA,
    "multiple_testing_correction": "Benjamini-Hochberg (1995) False Discovery Rate (FDR)",
    "effect_size_convention": "Hedges' g with pooled variance and small-sample correction factor J(df)",
    "preprocessing_configuration": {{
        "imputation": "feature_wise_median_for_pca",
        "standardization": "feature_wise_unit_variance_where_nonzero",
        "log2_fold_change_rule": "difference_of_means_if_log2_else_log2_ratio_if_positive",
    }},
    "software_versions": {{
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
    }},
    "timestamp": datetime.now(timezone.utc).isoformat(),
}}

with open("/workspace/reproducibility_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

with open("/workspace/differential_expression_results.json", "w") as f:
    json.dump({{
        "manifest": manifest,
        "top_features": records[:100],
    }}, f, indent=2)

# 6. Render genuine Volcano Plot
if len(results_df) > 0 and "log2_fc" in results_df and results_df["log2_fc"].notna().any():
    valid_plot = results_df[results_df["log2_fc"].notna() & results_df["adj_p_value"].notna()].copy()
    if len(valid_plot) > 0:
        valid_plot["neg_log10_q"] = -np.log10(np.maximum(valid_plot["adj_p_value"], 1e-300))
        
        plt.figure(figsize=(8, 6))
        sig_mask = valid_plot["adj_p_value"] <= FDR_THRESHOLD
        
        plt.scatter(
            valid_plot.loc[~sig_mask, "log2_fc"],
            valid_plot.loc[~sig_mask, "neg_log10_q"],
            c="#64748b", alpha=0.5, s=20, label=f"Non-significant (N={{sum(~sig_mask)}})"
        )
        plt.scatter(
            valid_plot.loc[sig_mask, "log2_fc"],
            valid_plot.loc[sig_mask, "neg_log10_q"],
            c="#06b6d4", alpha=0.85, s=35, edgecolors="#0891b2", label=f"Significant (FDR <= {{FDR_THRESHOLD}}, N={{sum(sig_mask)}})"
        )
        
        plt.axhline(-math.log10(FDR_THRESHOLD), color="#f43f5e", linestyle="--", linewidth=1.2, label=f"FDR = {{FDR_THRESHOLD}} threshold")
        plt.axvline(1.0, color="#94a3b8", linestyle=":", linewidth=1)
        plt.axvline(-1.0, color="#94a3b8", linestyle=":", linewidth=1)
        
        plt.xlabel(f"Log2 Fold Change ({{GROUP_B}} vs {{GROUP_A}})")
        plt.ylabel("-Log10 Adjusted P-Value (FDR)")
        plt.title(f"Volcano Plot: {{GROUP_B}} vs {{GROUP_A}}")
        plt.legend(loc="upper right", fontsize=8)
        plt.grid(True, linestyle="--", alpha=0.2)
        plt.tight_layout()
        plt.savefig("/workspace/volcano_plot.png", dpi=180)
        plt.close()
        print("Rendered genuine volcano_plot.png")

# 7. Render PCA Plot (Safe, non-crashing preprocessing)
try:
    sample_df = df[group_a_cols + group_b_cols].T
    imputer = SimpleImputer(strategy="median")
    imputed = imputer.fit_transform(sample_df.values)
    
    feat_stds = np.std(imputed, axis=0, ddof=0)
    zero_mask = feat_stds <= 1e-12
    feat_means = np.mean(imputed, axis=0)
    scaled = np.zeros_like(imputed)
    for j in range(imputed.shape[1]):
        if not zero_mask[j]:
            scaled[:, j] = (imputed[:, j] - feat_means[j]) / feat_stds[j]
    
    n_comp = min(2, len(sample_df), len(sample_df.columns))
    if n_comp >= 1:
        pca = PCA(n_components=n_comp)
        coords = pca.fit_transform(scaled)
        
        plt.figure(figsize=(7, 5))
        for grp_label, col_list, color in [(GROUP_A, group_a_cols, "#3b82f6"), (GROUP_B, group_b_cols, "#a855f7")]:
            idxs = [sample_df.index.get_loc(c) for c in col_list]
            plt.scatter(coords[idxs, 0], coords[idxs, 1], c=color, label=f"{{grp_label}} (N={{len(col_list)}})", s=50, edgecolors="white", alpha=0.9)
            
        var1 = round(float(pca.explained_variance_ratio_[0]) * 100, 1)
        var2 = round(float(pca.explained_variance_ratio_[1]) * 100, 1) if n_comp > 1 else 0.0
        
        plt.xlabel(f"PC1 ({{var1}}% variance)")
        plt.ylabel(f"PC2 ({{var2}}% variance)")
        plt.title("Principal Component Analysis (Sample Projection)")
        plt.legend(loc="best", fontsize=8)
        plt.grid(True, linestyle="--", alpha=0.2)
        plt.tight_layout()
        plt.savefig("/workspace/pca_plot.png", dpi=180)
        plt.close()
        print("Rendered genuine pca_plot.png")
except Exception as e:
    print(f"PCA generation notice: {{e}}")

print("Scientific computation completed successfully.")
'''
    return script

