/**
 * contract-types.ts — GENERATED, DO NOT EDIT BY HAND.
 *
 * The TypeScript mirror of the Python/Node contract, generated from
 * verity-schema.json by `uv run python generate_ts_contract.py` (A6.3).
 * Edit the Pydantic models in verity/models/schemas.py, run export_schema.py,
 * then regenerate this. CI fails if this file is out of date — see
 * verity/tests/test_contract_drift.py.
 *
 * These are the shapes that cross the RPC boundary. A worker handler that
 * returns one of these can import the type here instead of re-declaring it,
 * so the two sides cannot drift without a red build.
 */


export interface AuditReport {
  target: string;
  standard: "WCAG2.2-AA" | "EN301549" | "508" | "INT";
  findings: Finding[];
  conformance: Record<string, unknown>;
  verity_version: string;
  ruleset_version: string;
  latency?: Latency | null;
}

export interface BackgroundSample {
  r: number;
  g: number;
  b: number;
  count: number;
}

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Confidence {
  score: number;
  method: string;
  model?: string | null;
  escape_used?: boolean;
}

export interface ElementCapture {
  selector: string;
  path: string;
  box_css: BoundingBox;
  box_device: BoundingBox;
  device_pixel_ratio: number;
}

export interface Evidence {
  dom_selector?: string | null;
  ax_node_id?: string | null;
  screenshot_path?: string | null;
  region?: BoundingBox | null;
  interaction_trace?: string[] | null;
  computed_values?: Record<string, unknown>;
}

export interface ExerciseResult {
  snapshots?: InteractionSnapshot[];
  steps_requested: number;
  steps_run: number;
  complete: boolean;
  incomplete_reason?: string | null;
}

export interface Finding {
  id: string;
  rule_id: string;
  sc: SuccessCriterion;
  provenance: Provenance;
  severity: Severity;
  confidence: Confidence;
  agent: string;
  engine?: string | null;
  outcome: "fail" | "cantTell" | "pass";
  message: string;
  remediation?: string | null;
  evidence: Evidence;
  page_state_hash: string;
  waived?: boolean;
}

export interface InteractionSnapshot {
  step_index: number;
  active?: string | null;
  states?: WidgetNode[];
  missing?: string[];
}

export interface InteractionStep {
  action: "focus" | "press";
  target?: string | null;
  key?: string | null;
}

export interface Latency {
  render_seconds: number;
  analysis_seconds: number;
  total_seconds: number;
}

export type Level = "A" | "AA" | "AAA";

export type Modality = "deterministic" | "partial" | "visual" | "interaction" | "audio" | "manual";

export interface PageState {
  url: string;
  state_label?: string;
  viewport: Record<string, unknown>[];
  media_emulation?: Record<string, unknown>;
  content_hash: string;
}

export type Provenance = "authoritative" | "ai assisted" | "needs review";

export interface RegionSample {
  selector: string;
  foreground: Rgb;
  device_pixel_ratio: number;
  background_samples?: BackgroundSample[];
  text_pixel_count?: number;
  background_pixel_count?: number;
  sampled: boolean;
  ambiguous?: boolean;
  font_size_px?: number | null;
  font_weight?: number | null;
  font_uniform?: boolean;
}

export interface RenderArtifact {
  page_state: PageState;
  dom_path: string;
  ax_tree_path: string;
  styles_path: string;
  screenshot_full: string;
  element_screenshots?: Record<string, unknown>;
  network_log_path: string;
}

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

export type Severity = "critical" | "serious" | "moderate" | "minor";

export interface SuccessCriterion {
  id: string;
  name: string;
  level: Level;
  modality: Modality;
  obsolete?: boolean;
  act_rule_ids?: string[];
  techniques?: string[];
}

export interface TabStop {
  order: number;
  selector: string;
  cycle: number;
  bbox?: BoundingBox | null;
  role?: string | null;
  accessible_name?: string | null;
  tabindex?: number | null;
  focus_visible?: boolean | null;
  dom_order?: number | null;
}

export interface TraversalResult {
  stops?: TabStop[];
  cycles_requested: number;
  cycles_completed: number;
  returned_to_origin?: boolean;
  trap_detected?: boolean;
  trap_selector?: string | null;
  unreached?: UnreachedRegion[];
  complete: boolean;
  incomplete_reason?: string | null;
}

export type UnreachedReason = "shadow-dom" | "iframe" | "not-focusable" | "obscured" | "arrow-navigable" | "unknown";

export interface UnreachedRegion {
  selector: string;
  reason: UnreachedReason;
  detail?: string | null;
}

export interface Widget {
  root: WidgetNode;
  items?: WidgetNode[];
  related?: WidgetNode[];
  positive_tabindex_descendants?: string[];
  roving_ancestor?: string | null;
}

export interface WidgetInventory {
  widgets?: Widget[];
  shadow_roots_skipped?: number;
  iframes_skipped?: number;
}

export interface WidgetNode {
  selector: string;
  tag: string;
  role?: string | null;
  accessible_name?: string | null;
  tabindex?: number | null;
  attributes?: Record<string, unknown>;
  hidden?: boolean;
  disabled?: boolean;
}
