export interface DatasetSummary {
  id: string;
  name: string;
  version: number;
  status: "draft" | "frozen";
  created_at: string;
}

export interface Experiment {
  id: string;
  name: string;
  description: string | null;
  status: "draft" | "ready" | "running" | "completed" | "failed" | "archived";
  created_at: string;
  updated_at: string;
  datasets: DatasetSummary[];
}

export interface ExperimentList {
  items: Experiment[];
  total: number;
}

export interface ExperimentCreate {
  name: string;
  description?: string;
}

export interface HealthResponse {
  status: "ok" | "not_ready";
  service: string;
  database?: "ok" | "unavailable";
}

export type Severity = "neutral" | "low" | "moderate" | "aggressive" | "harmful";

export type Technique =
  | "none"
  | "self_promotion"
  | "authority_claim"
  | "ranking_instruction"
  | "direct_prompt_injection"
  | "indirect_prompt_injection"
  | "system_impersonation"
  | "competitor_suppression"
  | "fabricated_consensus"
  | "citation_manipulation"
  | "structured_data_manipulation"
  | "hidden_content"
  | "instruction_override";

export interface DocumentLabel {
  severity: Severity;
  technique: Technique;
  expected_target: boolean;
  annotation: string | null;
  annotator: string | null;
}

export interface SourceDocumentSummary {
  id: string;
  dataset_id: string;
  parent_document_id: string | null;
  filename: string;
  mime_type: string;
  source_representation: "html" | "text" | "markdown" | "json" | "jsonld" | "xml";
  origin: "upload" | "manual" | "model_output";
  sha256: string;
  byte_size: number;
  position: number | null;
  iteration: number;
  entity_key: string | null;
  entity_name: string | null;
  counterfactual_group_key: string | null;
  label: DocumentLabel;
  created_at: string;
}

export interface SourceDocument extends SourceDocumentSummary {
  content_type: string;
  raw_content: string;
  normalized_content: string;
  aliases_json: string[];
  metadata_json: Record<string, unknown>;
}

export interface SourceDocumentList {
  items: SourceDocumentSummary[];
  total: number;
  active_count: number;
}

export interface SamplePack {
  id: string;
  name: string;
  description: string;
  document_count: number;
  recommended_question: string;
}

export interface SamplePackImport {
  sample_pack: SamplePack;
  dataset_id: string;
  documents: SourceDocumentSummary[];
}

export interface ModelEntry {
  model_id: string;
  display_name: string;
  provider: string;
  location: string;
  endpoint_type: string;
  supports_temperature: boolean;
  supports_top_p: boolean;
  supports_seed: boolean;
  supports_reasoning: boolean;
  supports_structured_output: boolean;
  max_context: number;
  enabled: boolean;
  last_verified_at: string | null;
  runnable: boolean;
  availability_note: string | null;
}

export interface SystemPrompt {
  id: string;
  name: string;
  type: string;
  content: string;
  version: number;
  sha256: string;
  created_at: string;
}

export interface RunCreate {
  model_id: string;
  system_prompt_id: string;
  user_prompt: string;
  content_mode: "RAW" | "NORMALIZED" | "BOTH";
  ordering_strategy: "fixed" | "randomized" | "seeded_random" | "counterbalanced";
  random_seed?: number;
  repetitions: number;
  temperature?: number;
  top_p?: number;
  seed?: number;
  max_output_tokens: number;
  evaluator_model_id?: string;
  counterfactual_document_ids?: string[];
}

export interface RunDocument {
  document_id: string;
  position: number;
  content_sha256: string;
  tokens_estimated: number;
}

export interface Run {
  id: string;
  run_config_id: string;
  run_number: number;
  status: string;
  duration_ms: number | null;
  model_id_actual: string | null;
  total_tokens: number | null;
  response_text: string | null;
  error_message: string | null;
  evaluation_error: string | null;
  output_document_id: string | null;
  documents: RunDocument[];
  eval_results: EvalResult[];
}

export interface EvalDefinition {
  id: string;
  name: string;
  version: number;
  evaluator_type: string;
  metric_name: string;
  description: string;
}

export interface EvalResult {
  id: string;
  eval_definition_id: string;
  score: number | null;
  passed: boolean | null;
  label: string | null;
  reasoning: string | null;
  evidence_json: Record<string, unknown>;
  raw_result_json: Record<string, unknown>;
  evaluator_model: string | null;
  evaluator_version: string;
  created_at: string;
  definition: EvalDefinition;
}

export interface RunConfig {
  id: string;
  experiment_id: string;
  user_prompt: string;
  evaluation_model_config_id: string | null;
  status: string;
  repetitions: number;
  ordering_strategy: string;
  random_seed: number | null;
  created_at: string;
  runs: Run[];
}

export interface RunAccepted {
  run_config_id: string;
  run_ids: string[];
  status: string;
}

export interface RunEvent {
  id: number;
  run_config_id: string;
  run_id: string | null;
  event_type: string;
  payload_json: Record<string, unknown>;
  created_at: string;
}

export interface AnalysisMessage {
  id: string;
  analysis_session_id: string;
  message_number: number;
  role: "user" | "assistant";
  content: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface AnalysisSession {
  id: string;
  experiment_id: string;
  analysis_model_id: string;
  system_prompt_version: string;
  system_prompt_sha256: string;
  selected_run_ids_json: string[];
  status: string;
  created_at: string;
  messages: AnalysisMessage[];
}

export interface InteractiveSourceSnapshot {
  document_id: string;
  filename: string;
  source_representation: string;
  sha256: string;
  content_sha256: string;
  dataset_position: number | null;
  selected_position: number;
}

export interface InteractiveMessage {
  id: string;
  interactive_session_id: string;
  message_number: number;
  role: "user" | "assistant";
  content: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface InteractiveSession {
  id: string;
  experiment_id: string;
  model_id: string;
  provider: string;
  location: string;
  endpoint_type: string;
  system_prompt_id: string;
  system_prompt_sha256: string;
  system_prompt_content: string;
  content_mode: "RAW" | "NORMALIZED" | "BOTH";
  temperature: number | null;
  top_p: number | null;
  generation_seed: number | null;
  max_output_tokens: number;
  source_snapshot_json: InteractiveSourceSnapshot[];
  status: string;
  created_at: string;
  messages: InteractiveMessage[];
}

export interface MetricCondition {
  dataset_id: string;
  model_id: string;
  provider: string;
  location: string;
  system_prompt_version: number;
  system_prompt_sha256: string;
  user_prompt_sha256: string;
  content_mode: string;
  ordering_strategy: string;
  random_seed: number | null;
  temperature: number | null;
  top_p: number | null;
  generation_seed: number | null;
  max_output_tokens: number;
  target_severity: Severity | string;
  target_technique: Technique | string;
  target_position: number;
  target_mime_type: string;
  counterfactual_group_key: string | null;
  run_count: number;
  selection_sample_count: number;
  target_selection_rate: number | null;
  rank_sample_count: number;
  mean_target_rank: number | null;
  metric_sample_counts: Record<string, number>;
  metric_means: Record<string, number>;
}

export interface ExperimentMetrics {
  experiment_id: string;
  total_runs: number;
  completed_runs: number;
  evaluated_runs: number;
  conditions: MetricCondition[];
  manipulation_lift: {
    calculable: boolean;
    reason: string | null;
    comparisons: ManipulationLiftComparison[];
  };
}

export interface ManipulationLiftComparison {
  run_config_id: string;
  dataset_id: string;
  counterfactual_group_key: string;
  model_id: string;
  control: { severity: string; technique: string };
  injected: { severity: string; technique: string };
  control_selection_rate: number;
  injected_selection_rate: number;
  lift: number;
  lift_percentage_points: number;
  rank_delta: number | null;
  rank_delta_sample_count: number;
  matched_pair_count: number;
  position_distribution: Record<string, number>;
}
