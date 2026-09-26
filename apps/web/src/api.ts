export type Evidence = {
  claim_id: string; source_id: string; source_title: string; text: string; topic: string;
  locator: string; reference_kind: string; duration_scope: string | null; conditions: string[];
  block_locators: string[]; span_ids: string[]; completeness: string; review_status: string;
  travel_time: string | null; retrieved_at: string; source_url: string | null
}
export type Option = {
  option_id: string; label: string; reference_kinds: string[]; source_count: number;
  independent_source_count: number | null; opinion_count: number; evidence: Evidence[];
  route_evidence_ids: string[]; experience_evidence_ids: string[];
  source_transport_conditions: {text: string; evidence_ids: string[]}[];
  source_time_conditions: {text: string; evidence_ids: string[]}[];
  source_schedule: {entries: {day: number; text: string; evidence_ids: string[]}[]; day_count: number | null; basis: string};
  verified_duration_days: number | null; cost_cny_fen: number | null; feasibility: string; unknown: string[]
}
export type View = {
  session_id: string; revision: number; research_id: string | null; research_revision: number | null;
  mode: string; input_text: string; options: Option[]; other_clues: Evidence[]; evidence_count: number; source_count: number;
  preferences: {days: number | null; driving: string; budget_cny_fen: number | null; traveler_count: number | null; time_hint: string | null; travel_date: null; charter: string; answered: string[]};
  confirmed_option_id: string | null; preview: {option_id: string; added: string[]; removed: string[]; retained: string[]; gaps_added: string[]; gaps_removed: string[]; gaps_retained: string[]} | null;
  gaps: string[]; questions: {field: string; title: string; advice: string; choices: string[]}[];
  clarification: string | null; stale: boolean; cache_message: string | null; feasibility: string
}
export type Research = {research_id: string; research_revision: number; label: string; evidence_count: number}
export type Index = {mode: string; csrf_token: string; researches: Research[]; session: View | null}
let csrf = ''
export async function readIndex(): Promise<Index> {
  const result = await request<Index>('/api/v1/preview'); csrf = result.csrf_token; return result
}
export async function request<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store',
    ...(body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json',
      'X-CSRF-Token': csrf, 'Idempotency-Key': crypto.randomUUID()}, body: JSON.stringify(body)})})
  const result = await response.json()
  if (!response.ok) throw new Error(result.error?.message || '本地服务暂不可用，操作未确认。')
  return result as T
}
export const roleLabel = (value: string): string => ({AUTHOR_PROPOSED_PLAN: '作者未出行的计划',
  GUIDE_SUGGESTION: '攻略建议 · 未确认亲历', AUTHOR_RECORDED_TRIP: '作者记载的历史经历', UNKNOWN: '来源性质未知'}[value] || '来源性质未知')
