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
  interest_needs_confirmation: boolean; previous_interest: string | null
}
export type Research = {research_id: string; research_revision: number; label: string; evidence_count: number}
export type Index = {mode: string; csrf_token: string; researches: Research[]; session: View | null; workbench_available: boolean; replay_available: boolean; route_check_available: boolean; product_flow_available: boolean}
export type Job = {job_id: string; session_id: string; status: string; request_revision: number; cancel_requested: boolean; new_evidence_count: number; reviewed: number; pending: number; rejected: number; reason: string | null; can_adopt: boolean}
export type Workbench = {enabled: boolean; configured: boolean; budget: {used: Record<string, number>; remaining: Record<string, number>; gate: string; closed: boolean}; jobs: Job[]; data_use: string}
let csrf = ''
export class RequestError extends Error {
  constructor(message:string, public code:string, public status:number=0){super(message);this.name='RequestError'}
}
export async function readIndex(): Promise<Index> {
  const result = await request<Index>('/api/v1/preview')
  if(!result||typeof result.csrf_token!=='string'||typeof result.product_flow_available!=='boolean')throw new RequestError('本机服务响应不完整；输入已保留，请重新连接工作台。','INVALID_RESPONSE')
  csrf = result.csrf_token; return result
}
export async function request<T>(url: string, body?: unknown, key?: string, options?:{timeoutMs:number}): Promise<T> {
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),options?.timeoutMs??15000)
  try {
  const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal:controller.signal,
    ...(body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json',
      'X-CSRF-Token': csrf, 'Idempotency-Key': key || crypto.randomUUID()}, body: JSON.stringify(body)})})
  const result = await response.json().catch(()=>({}))
  if (!response.ok) throw new RequestError(result.error?.message || '本地服务暂不可用，操作未确认。',result.error?.code||'SERVICE_ERROR',response.status)
  return result as T
  } catch(e) {
    if(e instanceof RequestError) throw e
    throw new RequestError(controller.signal.aborted?'本机请求等待超时；结果可能已保存，请先读取状态，勿重复派发。':'暂时连接不到本机服务；输入已保留，请确认工作台已启动。',controller.signal.aborted?'TIMEOUT':'OFFLINE')
  } finally {clearTimeout(timer)}
}
export const roleLabel = (value: string): string => ({AUTHOR_PROPOSED_PLAN: '作者未出行的计划',
  GUIDE_SUGGESTION: '攻略建议 · 未确认亲历', AUTHOR_RECORDED_TRIP: '作者记载的历史经历', UNKNOWN: '来源性质未知'}[value] || '来源性质未知')

export type ReviewItem = {source_label: string; candidate_index: number; topic: string; origin: string; rule_version: number; action: string; reason_code: string; category: string; explanation: string; next_action: string; quote: string | null; locator: string | null; conversion: string | null}
export type ReviewUpdate = {revalidation_id: string; research_id: string; evidence_count: number; added: number}
export type ReviewIndex = {items: ReviewItem[]; updates: ReviewUpdate[]; message: string}
