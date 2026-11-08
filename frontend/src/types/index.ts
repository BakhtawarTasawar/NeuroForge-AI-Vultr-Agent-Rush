export type UserRole = 'ADMIN' | 'RESEARCHER' | 'VIEWER';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface Project {
  id: string;
  title: string;
  description: string | null;
  domain: string;
  status: 'Active' | 'Archived' | 'Draft';
  owner_id: string;
  owner_name?: string;
  created_at: string;
  updated_at: string;
}

export interface Dataset {
  id: string;
  project_id: string | null;
  owner_id: string;
  filename: string;
  original_name: string;
  file_size_bytes: number;
  file_format: string;
  status: string;
  sample_count: number | null;
  feature_count: number | null;
  content_hash?: string | null;
  matrix_orientation?: string;
  feature_id_column?: string | null;
  sample_id_column?: string | null;
  title?: string | null;
  domain?: string;
  organism?: string | null;
  tissue?: string | null;
  experimental_condition?: string | null;
  control_group?: string | null;
  treatment_group?: string | null;
  measurement_type?: string | null;
  data_source?: string | null;
  publication_reference?: string | null;
  is_synthetic?: boolean;
  created_at: string;
}

export interface DatasetInspection {
  id: string;
  filename: string;
  original_name: string;
  file_format: string;
  file_size_bytes: number;
  content_hash: string | null;
  matrix_orientation: string;
  orientation_confidence: number | null;
  orientation_reasoning: string | null;
  feature_count: number;
  sample_count: number;
  feature_id_column: string | null;
  sample_id_column: string | null;
  sample_identifiers: string[];
  feature_identifiers_sample: string[];
  metadata_columns: string[];
  warnings: string[];
}

export interface DatasetPreview {
  total_rows: number;
  total_cols: number;
  row_page: number;
  row_page_size: number;
  col_page: number;
  col_page_size: number;
  columns: string[];
  rows: Record<string, any>[];
}

export interface DistributionStats {
  min_val: number;
  max_val: number;
  mean_val: number;
  median_val: number;
  q25_val: number;
  q75_val: number;
  std_val: number;
  sparsity_percent: number;
  scale_inference: string;
  scale_explanation: string;
}

export interface SampleQualitySummary {
  sample_id: string;
  mean_val: number;
  median_val: number;
  std_val: number;
  missing_count: number;
  zero_count: number;
  mean_cohort_correlation: number | null;
  is_potential_outlier: boolean;
  outlier_reason: string | null;
}

export interface PCACoordinate {
  sample_id: string;
  pc1: number;
  pc2: number;
  group: string | null;
}

export interface PCAResult {
  pc1_variance_ratio: number;
  pc2_variance_ratio: number;
  total_explained_variance: number;
  coordinates: PCACoordinate[];
}

export type ReadinessState =
  | 'metadata_incomplete'
  | 'unsupported_data_type'
  | 'unsupported_design'
  | 'insufficient_samples'
  | 'ready_for_exploratory_analysis'
  | 'analysis_completed';

export interface GroupValidationResult {
  readiness_state: ReadinessState;
  is_ready_for_testing: boolean;
  groups: Record<string, number>;
  control_group: string | null;
  treatment_group: string | null;
  assigned_samples_count: number;
  unassigned_samples_count: number;
  sample_counts_valid: boolean;
  data_scale_valid_for_welch: boolean;
  warnings: string[];
  recommendations: string[];
  caveats?: string[];
}

export interface QualityAssessmentResult {
  total_features: number;
  total_samples: number;
  total_cells: number;
  missing_cells_count: number;
  missing_cells_percent: number;
  features_with_missing_count: number;
  samples_with_missing_count: number;
  constant_features_count: number;
  constant_features_sample: string[];
  distribution: DistributionStats;
  samples_summary: SampleQualitySummary[];
  cohort_mean_correlation: number | null;
  potential_outliers: string[];
  pca: PCAResult | null;
  group_validation: GroupValidationResult | null;
  overall_health_status: string;
  summary_notes: string[];
}

export interface ArtifactInfo {
  filename: string;
  size_bytes: number;
  content_type: string;
  download_url: string;
}

export type ExperimentStatus = 'Queued' | 'Running' | 'Completed' | 'Failed' | 'Timed out';

export interface Experiment {
  id: string;
  project_id: string;
  dataset_id: string | null;
  owner_id: string;
  owner_name?: string;
  title: string;
  description: string | null;
  experiment_type?: string;
  dataset_hash?: string | null;
  status: ExperimentStatus;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  exit_code: number | null;
  stdout: string | null;
  stderr: string | null;
  result_summary: string | null;
  artifacts?: ArtifactInfo[];
  statistical_summary?: any | null;
  reproducibility_manifest?: any | null;
  failure_reason: string | null;
  created_at: string;
}

export interface FeatureResult {
  feature_id: string;
  n_a: number;
  n_b: number;
  mean_a: number;
  mean_b: number;
  mean_diff: number;
  log2_fc: number | null;
  t_stat: number | null;
  df: number | null;
  p_value: number | null;
  adj_p_value: number | null;
  ci_lower: number | null;
  ci_upper: number | null;
  hedges_g: number | null;
  is_significant: boolean;
}

export interface ExperimentResultsDetail {
  experiment_id: string;
  status: string;
  dataset_id: string | null;
  dataset_hash: string | null;
  reproducibility_manifest: any | null;
  statistical_summary: any | null;
  artifacts: ArtifactInfo[];
  features: FeatureResult[];
  total_features: number;
  page: number;
  limit: number;
}

export interface OverviewStats {
  projects_count: number;
  datasets_count: number;
  experiments_count: number;
  reports_count: number;
  active_role: UserRole;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
}

export interface ResearchSession {
  id: string;
  project_id: string;
  dataset_id: string;
  owner_id: string;
  owner_name?: string;
  title: string;
  objective: string;
  dataset_hash?: string | null;
  status: string;
  current_step: string;
  approval_state: string;
  approval_notes?: string | null;
  approved_at?: string | null;
  research_plan?: any | null;
  experiment_ids: string[];
  tool_history: any[];
  evidence_store: any[];
  final_summary?: any | null;
  failure_reason?: string | null;
  iteration_count: number;
  max_iterations: number;
  retry_count: number;
  max_retries: number;
  created_at: string;
  updated_at: string;
}

export interface ResearchEvent {
  id: string;
  session_id: string;
  event_type: string;
  step_name: string;
  message: string;
  payload?: any;
  created_at: string;
}

export interface ResearchSessionCreate {
  dataset_id: string;
  title: string;
  objective: string;
  group_a_name?: string;
  group_b_name?: string;
  group_mappings?: Record<string, string>;
}

export interface ComparisonFeatureItem {
  feature_id: string;
  log2_fc_1?: number | null;
  log2_fc_2?: number | null;
  adj_p_value_1?: number | null;
  adj_p_value_2?: number | null;
  concordant?: boolean | null;
}

export interface ExperimentComparison {
  exp1: Experiment;
  exp2: Experiment;
  shared_dataset: boolean;
  dataset_hash_match: boolean;
  exp1_significant_count: number;
  exp2_significant_count: number;
  shared_significant_count: number;
  concordance_rate?: number | null;
  shared_features: ComparisonFeatureItem[];
  exp1_unique_features: Record<string, any>[];
  exp2_unique_features: Record<string, any>[];
}

// =============================================================================
// Scientific Knowledge & Vector RAG Types
// =============================================================================

export interface DocumentChunk {
  id: string;
  document_id: string;
  project_id: string;
  chunk_index: number;
  chunk_text: string;
  token_count: number;
  metadata_json?: string | null;
  created_at: string;
}

export interface KnowledgeDocument {
  id: string;
  project_id: string;
  owner_id: string;
  title: string;
  filename: string;
  file_format: string;
  file_size_bytes: number;
  content_hash?: string | null;
  chunk_count: number;
  source_type: string;
  doi?: string | null;
  authors?: string | null;
  publication_year?: number | null;
  journal?: string | null;
  source_url?: string | null;
  tags?: string | null;
  custom_metadata?: string | null;
  created_at: string;
  updated_at: string;
  chunks?: DocumentChunk[] | null;
}

export interface KnowledgeCitation {
  chunk_id: string;
  document_id: string;
  document_title: string;
  source_filename: string;
  chunk_index: number;
  relevance_score: number;
  chunk_text: string;
  metadata?: Record<string, any> | null;
}

export interface KnowledgeSearchResponse {
  query: string;
  project_id: string;
  total_results: number;
  citations: KnowledgeCitation[];
}
