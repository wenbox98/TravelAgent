<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { request, roleLabel, type View } from '../api'
import { mapLabel, type MapView, type TripInputs } from '../route-api'
const props = defineProps<{session: View}>()
const data = ref<MapView | null>(null)
const form = ref<TripInputs | null>(null)
const busy = ref(false), error = ref(''), status = ref('')
const consent = ref(false), privateConsent = ref(false)
const relations = ref<Record<string, string>>({}), times = ref<Record<string, string>>({})
const objectTypes = ['UNKNOWN', 'AREA', 'TOWN', 'STATION', 'SCENIC', 'ENTRANCE', 'PARKING', 'VISITOR_CENTER']
const edited = computed(() => JSON.stringify(form.value) !== JSON.stringify(data.value?.inputs))
const localDate = (s: string | null) => s?.slice(0, 16) || ''
const value = (e: Event) => (e.target as HTMLInputElement).value
const emptyNull = (e: Event) => value(e) || null
const numeric = (e: Event) => value(e) === '' ? null : Number(value(e))
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T
let generation = 0
function apply(next: MapView, ticket: number) {
  if (ticket !== generation || (data.value?.session_id === next.session_id && data.value.revision > next.revision)) return
  data.value = next; form.value = clone(next.inputs)
}
async function load() {
  const ticket = ++generation
  try { apply(await request<MapView>('/api/v1/preview/routes/' + props.session.session_id), ticket); error.value = '' }
  catch (e) { error.value = e instanceof Error ? e.message : '路程模块暂不可用；原草案保留。' }
}
async function act(action: string, patch: Record<string, unknown> = {}) {
  if (busy.value || !data.value) return
  const before = data.value, ticket = ++generation
  busy.value = true; error.value = ''; status.value = ''
  try {
    const result = await request<MapView>('/api/v1/preview/routes', {action, session_id: before.session_id,
      expected_revision: before.revision, expected_preview_revision: before.preview_revision,
      send_confirmed: consent.value, private_send_confirmed: privateConsent.value, ...patch})
    apply(result, ticket)
    status.value = action === 'save' ? '已保存修改预览；未发起地图查询，原采用条件保留。' : action === 'cancel' ? '已取消修改，恢复已采用条件；地图参考需重新核实。' : action === 'adopt' ? '已采用当前条件；没有改变原兴趣或审核资料。' : mapLabel(result.last_action || 'UNKNOWN')
  } catch (e) { error.value = e instanceof Error ? e.message : '操作未完成，请先刷新本地状态。' }
  finally { busy.value = false }
}
function addPlace() {
  form.value?.places.push({place_id: 'u' + crypto.randomUUID().replaceAll('-', ''), name: '', region: '', provenance: 'USER_INPUT', evidence_ids: [], object_type: 'UNKNOWN', private_address: false})
}
watch(() => [props.session.session_id, props.session.revision], load, {immediate: true})
</script>
<template>
  <section class="card route-panel" id="route-check" aria-labelledby="route-title">
    <p class="eyebrow">P03 · 从兴趣到出行条件</p><h2 id="route-title">路程与时间</h2>
    <p v-if="error" role="alert" class="warning">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <template v-if="data && form">
      <h3>{{ data.interest }}</h3><p>{{ data.evidence_count }} 条已审核资料保留 · 继承 {{ data.inherited.days ?? '未知' }} 天 / {{ data.inherited.driving === 'NO' ? '不自驾' : '驾驶偏好见已保存条件' }}。预算、人数未知也可以继续。</p>
      <p>{{ data.source_reference_kinds.map(roleLabel).join(' / ') }}。日序不代表实测小时；本模块只核实当前选中对象。</p>
      <p v-if="!data.configured" class="warning" data-testid="amap-unconfigured">高德待配置（AMAP_LIVE_BLOCKED_NOT_CONFIGURED）。先完成本机条件预览；目前没有真实地图距离或耗时。</p>
      <p v-if="!data.configured">在本机“用户环境变量”中配置 Web 服务类型的 AMAP_WEB_SERVICE_KEY，重新打开终端并重启本 P03 服务。不要把 Key 发到聊天或填在页面；不会自动读取 .env。</p>
      <fieldset :disabled="busy"><legend>1 · 时间与起终点</legend><p>决定门到门窗口。请优先填公共车站或地标；“国庆”不会自动填日期，“五天”不会换成120小时。</p>
        <div class="route-input-grid"><label>出发日期时间（北京时间）<input type="datetime-local" aria-label="出发日期时间" :value="localDate(form.depart_at)" @input="form.depart_at = emptyNull($event)" /></label>
          <label>最晚返回日期时间（北京时间）<input type="datetime-local" aria-label="最晚返回日期时间" :value="localDate(form.return_by)" @input="form.return_by = emptyNull($event)" /></label>
          <label>出发公共地点<input v-model="form.origin" maxlength="80" placeholder="公共车站或地标；暂不明确可留空" /></label>
          <label>最终返回公共地点<input v-model="form.destination" :disabled="form.same_return" maxlength="80" placeholder="不能用城市中心替代家门口" /></label></div>
        <label class="check-label"><input type="checkbox" v-model="form.same_return" />明确返回同一地点</label>
        <label class="check-label"><input type="checkbox" v-model="form.endpoints_private" />我填写的是精确私址（查询前另行确认发送）</label>
      </fieldset>
      <fieldset :disabled="busy"><legend>2 · 交通偏好与时间假设</legend><p>不自驾不等于只接受公交。愿意比较包车不代表已预订，也不证明有车可用。</p>
        <div class="route-input-grid"><label>包车 / 拼车倾向<select v-model="form.charter" aria-label="包车倾向"><option value="UNKNOWN">暂未决定</option><option value="COMPARE">愿意比较</option><option value="NO">不接受</option></select></label>
          <label>本次路段参考方式<select v-model="form.mode" aria-label="路段参考方式"><option value="TRANSIT">公共交通</option><option value="DRIVING">驾车道路参考（包车比较）</option><option value="WALKING">步行接驳参考</option></select></label></div>
        <details><summary>可选：我自己决定的活动窗口、停留与缓冲</summary><p>留空就是未知。活动窗口之外作为夜间休息；下列总分钟数只计窗口内休息、停留和接口未含的末端接驳。公交总耗时已含等车，不再次叠加。</p>
          <div class="route-input-grid"><label>每天活动开始<input type="time" :value="form.activity_start || ''" @input="form.activity_start = emptyNull($event)" /></label><label>每天活动结束<input type="time" :value="form.activity_end || ''" @input="form.activity_end = emptyNull($event)" /></label>
            <label>活动停留合计（分钟）<input type="number" min="0" :value="form.stay_minutes ?? ''" @input="form.stay_minutes = numeric($event)" /></label>
            <label>窗口内休息合计（分钟）<input type="number" min="0" :value="form.rest_minutes ?? ''" @input="form.rest_minutes = numeric($event)" /></label>
            <label>额外缓冲合计（分钟）<input type="number" min="0" :value="form.buffer_minutes ?? ''" @input="form.buffer_minutes = numeric($event)" /></label>
            <label>未含末端接驳的假设（分钟）<input type="number" min="0" :value="form.transfer_minutes ?? ''" @input="form.transfer_minutes = numeric($event)" /></label></div>
        </details>
      </fieldset>
      <details><summary>从来源片段确认 / 编辑相邻地点</summary><p v-for="fragment in data.source_route_fragments" :key="fragment">{{ fragment }}</p><p>只有当前对象的片段。文字拆分仅为建议，请确认名称与入口；自行补充的地点标为用户输入。</p>
        <div v-for="p in form.places" :key="p.place_id" class="place-edit"><label>地点名称<input v-model="p.name" maxlength="80" /></label><label>检索城市（可留空）<input v-model="p.region" maxlength="80" /></label><label>希望核实的对象<select v-model="p.object_type"><option v-for="t in objectTypes" :key="t" :value="t">{{ mapLabel(t) }}</option></select></label><p>{{ p.provenance === 'USER_INPUT' ? '用户补充' : '来自当前方向已审核片段，原证据不改写' }}</p><label class="check-label"><input type="checkbox" v-model="p.private_address" />包含精确私址</label></div>
        <button class="quiet" :disabled="busy || form.places.length >= 12" @click="addPlace">补充一个相邻地点</button>
      </details>
      <div class="actions"><button :disabled="busy || !edited" @click="act('save', {inputs: form})">保存修改预览（零外部调用）</button><button class="quiet" :disabled="busy" @click="act('cancel')">取消本次条件修改</button><button :disabled="busy || edited || !data.has_changes" @click="act('adopt')">采用当前条件</button></div>
      <p v-if="edited" class="warning">有未保存修改；先保存预览，再查询。输入本身不会触发外部调用。</p>
      <p v-if="data.has_changes">当前为条件预览，原采用条件保留。采用后仍不代表路线可执行。</p>
      <details v-if="data.adopted_inputs"><summary>已采用条件（修改预览不会覆盖）</summary><p>{{ data.adopted_inputs.depart_at || '出发时间未知' }} → {{ data.adopted_inputs.return_by || '返回时间未知' }}</p><p>{{ data.adopted_inputs.origin || '起点未知' }} → {{ data.adopted_inputs.destination || '终点未知' }}；包车：{{ mapLabel(data.adopted_inputs.charter) }}</p></details>
      <h3>地点确认与有限查询</h3><p>高德地图额度：地点 {{ data.budget.used.map_place }}/8，路径 {{ data.budget.used.map_route }}/8，总计 {{ data.budget.total_used }}/16。失败也占额度，不自动重试。</p>
      <label class="check-label"><input type="checkbox" v-model="consent" />本次点击查询时，允许把显示的必要地点名称、区域、已确认坐标和我填的该段时刻发给高德；不发送笔记正文。</label>
      <label v-if="form.endpoints_private || form.places.some(p => p.private_address)" class="check-label"><input type="checkbox" v-model="privateConsent" />我明确允许本次把上述精确私址及其坐标发给高德</label>
      <article v-for="p in data.places" :key="p.place_id" class="map-place"><h4>{{ p.name }} · {{ mapLabel(p.status) }}</h4><p>{{ mapLabel(p.object_type) }} · {{ p.provenance === 'USER_INPUT' ? '用户输入或修改' : '当前方向来源片段' }}</p><p v-if="p.raw_name !== p.name">原来源名称：{{ p.raw_name }}；当前检索名称由用户修改，不改变原证据。</p>
        <button class="quiet" :disabled="busy || edited || !consent || !data.configured || data.budget.remaining.map_place === 0" @click="act('resolve', {place_id: p.place_id})">查询这个地点（1次）</button>
        <div v-for="c in p.candidates" :key="c.candidate_id" class="map-candidate"><strong>{{ c.name }}</strong><p>{{ c.pname }} {{ c.cityname }} {{ c.adname }} · {{ c.type }} · {{ c.address }}</p><p>地图对象：{{ mapLabel(c.object_type) }}，GCJ-02 经度在前。入口与区域中心不能互换。</p>
          <label>这个对象与原地点的关系<select v-model="relations[c.candidate_id]" :aria-label="c.name + '关系'"><option value="">请选择关系</option><option value="SAME_OBJECT">同一对象</option><option value="REGIONAL_REFERENCE">仅区域参考</option><option value="ACCESS_POINT">接入点，接驳仍待核实</option></select></label>
          <button :disabled="busy || edited || !relations[c.candidate_id]" @click="act('confirm_place', {place_id: p.place_id, candidate_id: c.candidate_id, relation: relations[c.candidate_id]})">确认这个地图对象</button> <a :href="c.uri" target="_blank" rel="noopener noreferrer">在高德查看（手动打开）</a>
        </div><p v-if="p.confirmed">已选：{{ p.confirmed.name }} · {{ mapLabel(p.confirmed.relation || 'UNKNOWN') }}。实际入口、下车点与接驳仍待核实。</p>
      </article>
      <h3>核实选中路段</h3><p>只查明确相邻地点。各段日期时间单独填写，留空即一般参考，不推算中间到达或发车时刻。</p>
      <article v-for="leg in data.legs" :key="leg.leg_id" class="map-leg"><h4>{{ leg.from_name }} → {{ leg.to_name }}</h4><p>{{ mapLabel(leg.kind) }} · {{ mapLabel(leg.mode) }} · {{ mapLabel(leg.status) }}</p>
        <p>{{ leg.distance_meters === null ? '距离未知' : (leg.distance_meters / 1000).toFixed(1) + ' 公里' }} / {{ leg.duration_seconds === null ? '耗时未知' : (leg.duration_seconds / 60).toFixed(0) + ' 分钟（估算）' }} · {{ leg.basis }}</p>
        <p v-if="leg.stale" class="warning">条件已变化，上述旧参考不计入当前情景；原查询端点：{{ leg.result_endpoint_names.join(' → ') }}</p>
        <p>{{ mapLabel(leg.date_applicability) }}；实际交通落实：未知。{{ leg.queried_at ? '查询时间：' + leg.queried_at : '' }}</p>
        <ul><li v-for="gap in leg.gaps" :key="gap">{{ gap }}</li></ul>
        <label v-if="data.inputs.mode === 'TRANSIT'">该段明确出发时刻（可留空）<input type="datetime-local" v-model="times[leg.leg_id]" /></label>
        <button :disabled="busy || edited || !consent || !data.configured || data.budget.remaining.map_route === 0 || leg.endpoint_confidence !== 'USER_CONFIRMED_MAP_OBJECTS'" @click="act('route', {leg_id: leg.leg_id, leg_depart_at: times[leg.leg_id] || null})">核实此路段（1次）</button>
      </article>
      <h3>当前时间参考与缺口</h3><p data-testid="time-conclusion">{{ mapLabel(data.time_check.completeness) }} · {{ mapLabel(data.time_check.scenario) }} · 可执行性仍未核实。</p>
      <p>已知移动估算：{{ data.time_check.known_movement_minutes.toFixed(0) }} 分钟；活动可用窗口：{{ data.time_check.available_minutes === null ? '未知' : data.time_check.available_minutes.toFixed(0) + ' 分钟' }}。未查询时0只是已知项之和，不代表行程耗时为0。</p>
      <p>检查范围：{{ mapLabel(data.time_check.checked_scope) }}。{{ data.time_check.meaning }}</p><ul><li v-for="gap in data.time_check.missing_inputs" :key="gap">{{ mapLabel(gap) }}</li></ul>
      <details v-if="data.time_check.assumptions.length"><summary>本次用户假设（不是来源事实）</summary><ul><li v-for="a in data.time_check.assumptions" :key="a">{{ a }}</li></ul></details>
      <p class="notice">{{ data.message }} 高德估算不保证国庆拥堵、景区开放、车次或可订性。G1 保持 NOT PASS。</p><p v-if="data.map_result_state === 'STALE'" class="warning">旧地图计算已失效（STALE）。原采用条件和兴趣方向保留。</p>
      <button class="quiet" :disabled="busy" @click="load">刷新本地状态（零外部调用）</button>
    </template>
  </section>
</template>
<style scoped>
.route-panel { margin-top: 2rem; }
fieldset { border: 1px solid #cbd4ca; border-radius: 12px; margin: 1rem 0; padding: 1rem; }
legend { font-weight: 700; padding: 0 .5rem; }
.route-input-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 1rem; }
.check-label { display: flex; align-items: start; gap: .6rem; margin: 1rem 0; }
.check-label input { width: auto; margin-top: .3rem; }
.map-place,.map-leg,.place-edit { border-top: 1px solid #d7dfd5; padding: 1rem 0; }
.map-candidate { border-left: 3px solid #8ea68b; padding: .7rem 1rem; margin: .6rem 0; }
.map-candidate a { display: inline-block; margin-top: .5rem; }
@media(max-width: 650px) { .route-input-grid { grid-template-columns: 1fr; } }
</style>
