export type ProfileType = "weak_foundation" | "exam_sprint" | "algorithm_practice" | string;

export interface DemoDataStatus {
  is_loaded: boolean;
  course_title: string;
  concept_slugs: string[];
  profile_types: ProfileType[];
  course_id: number | null;
  concept_count: number;
  profile_count: number;
  document_count: number;
  chunk_count: number;
}

export interface StudentProfile {
  id: number;
  user_id: number | null;
  profile_type: ProfileType;
  goal: string;
  level: string;
  preferences: Record<string, unknown>;
  time_budget: string;
  created_at: string | null;
}

export interface StudentProfileDialogueCreate {
  dialogue: string;
  profile_type?: ProfileType | null;
  user_id?: number | null;
}

export interface Concept {
  id: number;
  course_id: number;
  slug: string;
  name: string;
  chapter: string | null;
  description: string | null;
  difficulty: string;
}

export interface ConceptRelation {
  id: number;
  source_concept_id: number;
  target_concept_id: number;
  relation_type: string;
}

export interface ConceptGraph {
  course_id: number;
  course_title: string | null;
  concepts: Concept[];
  relations: ConceptRelation[];
}

export interface DocumentChunk {
  id: number;
  document_id: number;
  concept_id: number | null;
  content: string;
  vector_ref: string | null;
  metadata: Record<string, unknown>;
  source_ref: string | null;
}

export interface DocumentIngestionRequest {
  title: string;
  source_type: "text" | "markdown";
  content: string;
  visibility?: "course" | "demo" | "private";
  owner_user_id?: number | null;
}

export interface StudentProfileHistory {
  id: number;
  student_profile_id: number;
  event_key: string;
  trigger_type: string;
  before_dimensions: Record<string, string>;
  after_dimensions: Record<string, string>;
  changed_dimensions: string[];
  reason: string;
  evidence_refs: Array<Record<string, unknown>>;
  agent_run_id: number | null;
  created_at: string | null;
}

export interface DocumentIngestionResponse {
  document: {
    id: number;
    course_id: number;
    title: string;
    source_type: string;
    status: string;
    created_at: string | null;
    visibility: string;
    owner_user_id: number | null;
    file_name: string | null;
    mime_type: string | null;
    file_size: number | null;
    parser_name: string | null;
  };
  chunks: DocumentChunk[];
  chunk_count: number;
}

export interface ManagedDocument {
  id: number;
  course_id: number;
  title: string;
  source_type: string;
  status: string;
  created_at: string | null;
  chunk_count: number;
  visibility: string;
  owner_user_id: number | null;
  file_name: string | null;
  mime_type: string | null;
  file_size: number | null;
  parser_name: string | null;
}

export interface DocumentReindexResponse {
  document_id: number;
  indexed: number;
  skipped: number;
  failed: number;
  enabled: boolean;
  message: string;
}

export interface KnowledgeSearchResult {
  chunk_id: number | null;
  content: string;
  score: number | null;
  source_ref: string | null;
  metadata: Record<string, unknown>;
}

export interface KnowledgeSearchResponse {
  results: KnowledgeSearchResult[];
}

export interface LearningPathItem {
  id: number;
  path_id: number;
  concept_id: number;
  order_index: number;
  title: string;
  objective: string;
  rationale: string | null;
  status: string;
  recommended_resource_type?: string | null;
  recommendation_reason?: string | null;
    priority?: number | null;
    node_role: "target" | "prerequisite";
    activity_type: string;
    estimated_minutes: number;
    success_criterion: string;
}

export interface LearningPathMilestone {
  milestone_type: "mock_assessment";
  title: string;
  objective: string;
  covered_concept_ids: number[];
  estimated_minutes: number;
  success_criterion: string;
}

export interface LearningPath {
  id: number;
  student_profile_id: number;
  course_id: number;
  goal: string;
  rationale: string | null;
  status: string;
  items: LearningPathItem[];
  created_at: string | null;
  execution_mode?: string | null;
  provider?: string | null;
  model?: string | null;
  fallback_used?: boolean;
  fallback_reason?: string | null;
  planner_duration_ms?: number | null;
  provider_duration_ms?: number;
  retry_count?: number;
    token_usage?: Record<string, number>;
    learning_intent?: Record<string, unknown>;
    target_concept_ids?: number[];
    intent_confidence?: number;
    milestones?: LearningPathMilestone[];
}

export interface AgentExecutionMetadata {
  execution_mode: "llm" | "rule_based" | "rule_based_fallback";
  provider: string;
  model: string;
  fallback_used: boolean;
  fallback_reason: string | null;
  source_refs: string[];
  duration_ms: number;
  provider_duration_ms: number;
  retry_count: number;
  token_usage: Record<string, number>;
}

export interface AgentRunStep {
  id: number;
  agent_run_id: number;
  agent_type: string;
  step_order: number;
  status: string;
  input_summary: string;
  output_summary: string;
  decision_basis: string;
  duration_ms: number | null;
  error: string | null;
  execution_metadata: AgentExecutionMetadata;
}

export interface AgentRun {
  id: number;
  run_type: string;
  status: string;
  input_summary: string | null;
  output_summary: string | null;
  final_summary: string | null;
  steps: AgentRunStep[];
}

export interface LearningFlow {
  learning_path: LearningPath;
  agent_run: AgentRun;
}

export interface GeneratedResource {
  id: number;
  path_item_id: number;
  resource_type: string;
  content: string;
  source_refs: Array<Record<string, unknown>>;
  agent_run_id: number | null;
  safety_status: "passed" | "blocked" | "degraded";
  safety_message: string | null;
  postprocessing_task_id: number | null;
  postprocessing_status: string;
  animation_spec: AnimationSpec | null;
}

export interface AnimationNode {
  id: string;
  label: string;
  x: number;
  y: number;
  value: number | null;
  kind: string;
}

export interface AnimationEdge {
  source: string;
  target: string;
  label: string | null;
}

export interface AnimationTimelineStep {
  at_ms: number;
  action: "visit" | "highlight" | "compare" | "swap" | "push" | "pop" | "enqueue" | "dequeue" | "relax" | "select" | "complete";
  target: string;
  caption: string;
  values: Record<string, number>;
  labels: Record<string, string>;
  frontier: string[];
  visited: string[];
  range_start: number | null;
  range_end: number | null;
}

export interface AnimationVariant {
  id: "bfs" | "dfs";
  label: string;
  structure_label: string;
  timeline: AnimationTimelineStep[];
}

export type AnimationTemplateId =
  | "binary_tree_traversal"
  | "complexity_visualizer"
  | "linear_structure"
  | "stack_queue_operations"
  | "tree_visualizer"
  | "graph_visualizer"
  | "search_visualizer"
  | "sorting_visualizer"
  | "algorithm_workflow"
  | "concept_fallback";

export interface AnimationSpec {
  version: "1.0";
  template_id: AnimationTemplateId;
  title: string;
  description: string;
  duration_ms: number;
  data: {
    mode: string;
    structure_label: string;
    traversal_type: "PRE_ORDER" | "IN_ORDER" | "POST_ORDER" | "LEVEL_ORDER" | null;
    nodes: AnimationNode[];
    edges: AnimationEdge[];
    sequence: string[];
    variants: AnimationVariant[];
  };
  timeline: AnimationTimelineStep[];
}

export interface TutorAnswer {
  answer: string;
  source_refs: Array<Record<string, unknown>>;
  agent_run_id: number | null;
  safety_status: "passed" | "blocked" | "degraded";
  safety_message: string | null;
  postprocessing_task_id: number | null;
  postprocessing_status: string;
}

export interface QuizItem {
  id: number | null;
  question: string;
  answer: string;
  explanation: string;
  difficulty: string;
  concept_tags: string[];
  question_type?: string | null;
  options?: string[];
  source_refs?: Array<Record<string, unknown>>;
}

export interface Quiz {
  id: number;
  student_profile_id: number;
  concept_id: number;
  difficulty: string;
  status: string;
  items: QuizItem[];
  agent_run_id: number | null;
  execution_mode?: string | null;
  provider?: string | null;
  model?: string | null;
  fallback_used?: boolean;
  fallback_reason?: string | null;
  quiz_duration_ms?: number | null;
  safety_status: "passed" | "blocked" | "degraded";
  safety_message: string | null;
}

export interface EvaluationResult {
  attempt_id: number | null;
  score: number;
  feedback: string;
  mastery_updates: Array<Record<string, unknown>>;
  agent_run_id: number | null;
  postprocessing_task_id: number | null;
  postprocessing_status: "not_requested" | "pending" | "running" | "completed" | "failed";
}

export interface Task {
  id: number;
  task_type: string;
  status: "pending" | "running" | "completed" | "failed" | "deleted";
  result_ref: string | null;
  error: string | null;
  created_at: string | null;
}
