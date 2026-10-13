// Typed client for the query API. Types mirror the pydantic models in
// pipeline/brokeberg/graph/views.py and pipeline/brokeberg/api/{app,rsch,refs}.py.

export type TrustTier = "T1" | "T2" | "T3" | "T4";

export interface FeedRow {
  event_id: number;
  headline: string;
  event_type: string;
  event_time: string;
  topics: string[];
  source_count: number;
  verification_status: string;
  confidence: number;
  salience: number;
  components: Record<string, number>;
  source_url: string;
  span: string;
  trust_tier: TrustTier;
}
export interface FeedResponse { window_days: number; rows: FeedRow[] }

export interface StanceFlip {
  prior_event_id: number;
  prior_event_time: string;
  prior_stance: string;
  prior_span: string;
  prior_source_url: string | null;
}

export interface EntityRef {
  entity_id: number;
  canonical_id: string;
  name: string;
  entity_type: string;
  roles: string[];
}
export interface Reaction {
  entity_id: number;
  canonical_id: string;
  name: string;
  topic: string;
  stance: string;
  intensity: number | null;
  span: string;
  source_url: string;
  trust_tier: TrustTier;
  confidence: number;
  flip: StanceFlip | null;
}
export interface RelatedEvent {
  event_id: number;
  relation: string;
  direction: "prior" | "later";
  headline: string;
  event_time: string;
  confidence: number;
}
export interface SourceRef { url: string; span: string; trust_tier: TrustTier; raw_item_id: number | null }
export interface AffectedElection {
  race_id: string;
  rating: string | null;
  confidence: number;
  rationale: string;
  matched_topics: string[];
}
export interface EventObject {
  id: number;
  event_type: string;
  headline: string;
  what_happened: string | null;
  why_it_matters: string | null;
  event_time: string;
  ingest_time: string;
  confidence: number;
  verification_status: string;
  topics: string[];
  policy_areas: string[];
  jurisdiction: string | null;
  member_event_ids: number[];
  entities: EntityRef[];
  political_reactions: Reaction[];
  related_events: RelatedEvent[];
  sources: SourceRef[];
  affected_elections: AffectedElection[];
  verification: Record<string, unknown>;
}

export interface EntityInfo { entity_id: number; canonical_id: string; name: string; entity_type: string }
export interface StanceRow {
  event_id: number;
  event_time: string;
  entity_id: number;
  topic: string;
  stance: string;
  intensity: number | null;
  confidence: number;
  span: string;
  source_url: string;
  trust_tier: TrustTier;
  verification_status: string;
  flip: StanceFlip | null;
}
export interface RecentEvent {
  event_id: number;
  headline: string;
  event_type: string;
  event_time: string;
  roles: string[];
  verification_status: string;
  source_url: string;
  span: string;
  trust_tier: TrustTier;
}
export interface Neighbor {
  entity_id: number;
  canonical_id: string;
  name: string;
  entity_type: string;
  relation: string;
  direction: "in" | "out";
  edge_count: number;
  confidence: number;
  rationale: string | null;
  event_id: number;
  event_time: string;
  source_url: string;
  span: string;
}
export interface EntityDossier {
  entity: EntityInfo;
  stances: StanceRow[];
  recent_events: RecentEvent[];
  relationships: Neighbor[];
}
export interface StanceResponse { entity: EntityInfo; topic: string; rows: StanceRow[] }

export interface RatingRow { rater: string; rating: string; asof: string; source_url: string }
export interface CandidateRow {
  fec_candidate_id: string;
  entity_id: number | null;
  canonical_id: string | null;
  name: string | null;
  finance: Record<string, unknown> | null;
}
export interface PollRow { value: string; asof: string; source_url: string; meta: Record<string, unknown> }
export interface LinkedEvent {
  event_id: number;
  headline: string;
  event_time: string;
  verification_status: string;
  confidence: number;
  rationale: string;
  matched_topics: string[];
  source_url: string;
  span: string;
  trust_tier: TrustTier;
}
export interface RaceDossier {
  race_id: string;
  state_fips: string;
  office: string;
  cycle: number;
  election_day: string;
  rating: string | null;
  rating_history: RatingRow[];
  incumbent: EntityInfo | null;
  candidates: CandidateRow[];
  finance_asof: string | null;
  finance_source_url: string | null;
  poll_average: PollRow | null;
  linked_events: LinkedEvent[];
}

export interface TickerRow {
  series_id: string;
  label: string;
  transform: "level" | "yoy" | "change";
  value: number;
  delta: number | null;
  asof: string;
  source: string;
  source_url: string;
  span: string;
}

export interface Claim { text: string; cited: number[] }
export interface QueryRecord {
  n: number;
  event_id: number;
  headline: string;
  event_time: string;
  event_confidence: number;
  url: string;
  span: string;
  trust_tier: TrustTier;
  speaker: string | null;
}
export interface QueryResponse {
  question: string;
  refused: boolean;
  message: string | null;
  claims: Claim[];
  sources: QueryRecord[];
  confidence: number;
  dropped_claims: { text: string; problems: string[] }[];
}

export interface Option { label: string; command: string }

/** A non-2xx answer. `options` are runnable commands that narrow an ambiguous reference. */
export class ApiError extends Error {
  constructor(public status: number, message: string, public options: Option[] = []) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { "content-type": "application/json" } });
  } catch {
    throw new ApiError(0, "API unreachable — start it with `make api`.");
  }
  if (res.ok) return res.json() as Promise<T>;
  let body: { detail?: unknown; options?: Option[] } = {};
  try {
    body = await res.json();
  } catch {
    // proxy error pages are not JSON
  }
  if (res.status >= 500 && typeof body.detail !== "string") {
    throw new ApiError(res.status, "API unreachable or failing — check the `make api` terminal.");
  }
  const detail = typeof body.detail === "string" ? body.detail : `Request failed (${res.status}) — retry, or type HELP.`;
  throw new ApiError(res.status, detail, body.options ?? []);
}

const enc = encodeURIComponent;

export const api = {
  feed: () => request<FeedResponse>("/api/feed"),
  event: (id: string) => request<EventObject>(`/api/event/${enc(id)}`),
  race: (id: string) => request<RaceDossier>(`/api/race/${enc(id)}`),
  entity: (ref: string) => request<EntityDossier>(`/api/entity/${enc(ref)}`),
  stance: (entity: string, topic: string) =>
    request<StanceResponse>(`/api/stance?entity=${enc(entity)}&topic=${enc(topic)}`),
  indicators: () => request<TickerRow[]>("/api/indicators"),
  query: (question: string) =>
    request<QueryResponse>("/api/query", { method: "POST", body: JSON.stringify({ question }) }),
};
