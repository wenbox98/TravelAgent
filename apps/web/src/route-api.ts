import type { View } from './api'
export type PlaceInput = {place_id: string; name: string; region: string; evidence_ids: string[]; provenance: string; object_type: string; private_address: boolean}
export type TripInputs = {depart_at: string | null; return_by: string | null; origin: string; destination: string; same_return: boolean; endpoints_private: boolean; charter: string; mode: string; activity_start: string | null; activity_end: string | null; stay_minutes: number | null; rest_minutes: number | null; buffer_minutes: number | null; transfer_minutes: number | null; places: PlaceInput[]}
export type MapCandidate = {candidate_id: string; name: string; type: string; address: string; pname: string; cityname: string; adname: string; object_type: string; uri: string; location: string; coordinate_system: string; relation?: string}
export type MapPlace = PlaceInput & {raw_name: string; status: string; candidates: MapCandidate[]; confirmed: MapCandidate | null}
export type MapLeg = {leg_id: string; from_name: string; to_name: string; from_id: string; to_id: string; kind: string; status: string; mode: string; duration_seconds: number | null; distance_meters: number | null; queried_at: string | null; date_applicability: string; requested_depart_at: string | null; endpoint_confidence: string; availability: string; basis: string; gaps: string[]; stale: boolean; result_endpoint_names: string[]}
export type MapView = {session_id: string; revision: number; preview_revision: number; interest: string; evidence_count: number; inherited: View['preferences']; inputs: TripInputs; adopted_inputs: TripInputs | null; has_changes: boolean; places: MapPlace[]; legs: MapLeg[]; configured: boolean; configuration_status: string; source_route_fragments: string[]; source_reference_kinds: string[]; map_result_state: string; message: string; last_action: string | null; budget: {used: Record<string, number>; remaining: Record<string, number>; total_used: number; total_limit: number}; time_check: {scenario: string; completeness: string; executable: string; known_movement_minutes: number; known_components_minutes: number; available_minutes: number | null; assumptions: string[]; unknown_legs: string[]; missing_inputs: string[]; checked_scope: string; meaning: string}}
export const mapLabel = (s: string): string => ({UNKNOWN: '未知', COMPARE: '愿意比较', NO: '不接受',
  TRANSIT: '公共交通参考', DRIVING: '驾车道路参考（非公交）', WALKING: '步行接驳参考',
  OK: '已返回参考', PARTIAL: '部分信息', NOT_QUERIED: '尚未查询', STALE: '已失效，保留旧参考',
  UNRESOLVED: '待检索与确认', MULTIPLE_CANDIDATES: '多个候选，请确认', AWAITING_CONFIRMATION: '请确认具体对象',
  CONFIRMED: '已确认地图对象', NO_PLACE_RETURNED: '本次未返回地点', NO_ROUTE_RETURNED: '本次接口未返回方案，不代表现实无交通',
  NOT_CONFIGURED: '高德 Web 服务 Key 待配置', AUTH_OR_QUOTA_ERROR: '账户权限或配额受限', UPSTREAM_ERROR: '本次接口失败，未自动重试',
  BUDGET_OR_DUPLICATE_DENIED: '相同查询已经尝试，或额度不足；不会再次派发', RUNNING: '正在查询，刷新只读取本地状态',
  LATE_RESULT_DISCARDED: '条件已变化，旧查询结果未采用', GENERAL_REFERENCE_ONLY: '一般路程参考，未核实未来日期',
  TIME_WINDOW_UNCONFIRMED: '具体出发与返回时间未确认', REQUESTED_TRANSIT_TIME_NOT_GUARANTEED: '已传该段日期时间；班次及未来适用性仍待核实',
  AREA: '区域中心', TOWN: '城镇', STATION: '车站', SCENIC: '景区/景点', ENTRANCE: '入口', PARKING: '停车场', VISITOR_CENTER: '游客中心',
  COMPLETE: '当前数据齐全', FITS_UNDER_STATED_ASSUMPTIONS: '在所填假设下容得下，仍不可视为可执行',
  EXCEEDS_UNDER_STATED_ASSUMPTIONS: '按当前估算情景超出窗口，不证明所有现实路线都不可行',
  STAY_UNKNOWN: '停留时间未知', REST_UNKNOWN: '活动窗口内休息时间未知', BUFFER_UNKNOWN: '缓冲时间未知', ACCESS_TRANSFER_UNKNOWN: '末端接驳假设未知',
  ENDPOINTS_UNKNOWN: '门到门起终点未确认', ACTIVITY_WINDOW_UNKNOWN: '每日可活动窗口未知，不能把五天当120小时',
  ROUTE_NOT_CHECKED: '尚无可计算路段', UNCHECKED_LEGS: '部分路段未核实', LOCAL_SCOPE_NOT_WHOLE_TRIP: '只覆盖当前日段，不代表五天全程',
  LOCAL_DAY_SEGMENT: '当前来源日段', WHOLE_SELECTED_OBJECT: '当前选中对象', OUTBOUND: '出发接入', RETURN: '最终返程', BETWEEN_SOURCE_PLACES: '来源相邻地点',
  SAME_OBJECT: '与来源/输入为同一对象', REGIONAL_REFERENCE: '只作区域参考', ACCESS_POINT: '用户选择的接入点，接驳待核实'}[s] || s)
