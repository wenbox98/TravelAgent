<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request } from '../api'
import PlanPlaces from './PlanPlaces.vue'
import { originLabel, transportLabel, type Draft, type PlanView, type PlanIndex } from '../planning-api'
const data = ref<PlanView | null>(null), form = ref<Draft | null>(null)
const index = ref<PlanIndex | null>(null)
const destination = ref(''), requestText = ref(''), kind = ref('CITY')
const busy = ref(false), error = ref(''), status = ref('')
const creating = ref(false)
let generation = 0, poll: ReturnType<typeof setInterval> | undefined
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T
const edited = computed(() => JSON.stringify(form.value) !== JSON.stringify(data.value?.draft))
const label = computed(() => data.value?.directions.find(d => d.id === form.value?.direction)?.label || '尚未选择')
const readable = (s: string) => (data.value?.draft.activities || []).reduce((text, a) => text.replaceAll(a.activity_id, a.name), s)
const deltaLabel = (s: string) => ({activities: '活动顺序或停留', direction: '兴趣方向', inputs: '时间/往返条件', days: '可用天数', transport: '交通意向', driving: '驾驶意愿', return_deadline: '返回硬约束', first_day: '开始日序', first_period: '开始时段', anchor_origin: '开始时间'}[s] || '本行程条件')
function apply(v: PlanView) { data.value = v; form.value = clone(v.draft); localStorage.setItem('ta-current-trip', v.session_id) }
async function refreshIndex() { index.value = await request<PlanIndex>('/api/v1/preview/planning') }
async function load(sid?: string) {
  const ticket = ++generation
  try {
    await refreshIndex()
    const selected = sid || localStorage.getItem('ta-current-trip')
    const next = selected && index.value?.trips.some(t => t.session_id === selected) ? await request<PlanView>('/api/v1/preview/planning/' + selected) : index.value?.current
    if (ticket === generation && next) apply(next)
  } catch(e) { error.value = e instanceof Error ? e.message : '本地读取失败' }
}
async function create(demo: string | null = null) {
  if (busy.value) return
  busy.value = true; error.value = ''; ++generation
  try {
    const destinationName = demo === 'CITY' ? '成都城市观光（合成）' : demo === 'REGIONAL' ? '成都到川西（合成）' : demo === 'OTHER_CITY' ? '苏州两日（合成）' : destination.value
    apply(await request<PlanView>('/api/v1/preview/planning', {destination: destinationName, request: demo ? '自编活动交互测试，不是私人旅行计划' : requestText.value, travel_kind: demo === 'REGIONAL' ? 'REGIONAL' : demo ? 'CITY' : kind.value, demo}))
    creating.value = false; await refreshIndex(); status.value = '新旅行独立建立；没有继承历史测试偏好。'
  } catch(e) { error.value = e instanceof Error ? e.message : '未创建' }
  finally { busy.value = false }
}
async function act(action: string, extra: Record<string, unknown> = {}) {
  if (!data.value || !form.value || busy.value) return
  busy.value = true; error.value = ''; status.value = ''; ++generation
  try {
    if (edited.value && !['save', 'cancel', 'collapse', 'cancel_job'].includes(action)) {
      apply(await request<PlanView>('/api/v1/preview/planning/' + data.value.session_id, {action: 'save', expected_revision: data.value.revision, draft: form.value}))
    }
    apply(await request<PlanView>('/api/v1/preview/planning/' + data.value.session_id, {action, expected_revision: data.value.revision, ...(action === 'save' ? {draft: form.value} : {}), ...extra}))
    if (action === 'suggest') await refreshIndex()
    status.value = action === 'adopt' ? '已采用这版；尚未核实的交通和预约继续保留。' : action === 'cancel' ? '已恢复采用版。' : action === 'suggest' ? 'AI正在生成建议；原草稿和采用版保留。' : action === 'use_proposal' ? 'AI建议已放入可编辑草稿，尚未覆盖采用版。' : '已保存到本机，没有发起地图或研究请求。'
  } catch(e) { error.value = e instanceof Error ? e.message : '操作未完成，草稿保留' }
  finally { busy.value = false }
}
async function choose(id: string) { if (form.value) { form.value.direction = id; await act('save') } }
async function toggle(section: string) { await act('collapse', {section, collapsed: !data.value?.collapsed[section]}) }
async function addActivity() {
  if (!form.value || form.value.activities.length >= 12) return
  form.value.activities.push({activity_id: 'user-' + crypto.randomUUID(), name: '新活动（请修改）', region: data.value?.destination || '', evidence_ids: [], conditions: [], provenance: 'USER_INPUT', day: 1, stay_min: null, stay_max: null, rest_minutes: null, locked_start: null, timing_origin: 'UNKNOWN'})
  await act('save')
}
function number(e: Event): number | null { const v = (e.target as HTMLInputElement).value; return v === '' ? null : Number(v) }
function text(e: Event): string | null { return (e.target as HTMLInputElement).value || null }
onMounted(async () => {
  await load()
  poll = setInterval(async () => {
    if (!busy.value && !edited.value && data.value?.job && ['QUEUED', 'RUNNING'].includes(data.value.job.status)) {
      const ticket = generation, sid = data.value.session_id
      try { const next = await request<PlanView>('/api/v1/preview/planning/' + sid); if (ticket === generation && sid === data.value?.session_id) apply(next) } catch { /* explicit refresh remains available */ }
    }
  }, 1000)
})
onUnmounted(() => { ++generation; clearInterval(poll) })
</script>
<template>
  <section class="planning-flow">
    <div class="trip-toolbar"><div><p class="eyebrow">一个想法，逐步成为你的安排</p><h1>{{ data && !creating ? data.destination : '想去哪里走走？' }}</h1></div><button class="quiet" :disabled="busy" @click="creating = !creating">{{ creating ? '回到当前旅行' : '新建独立旅行' }}</button></div>
    <p v-if="error" class="warning" role="alert">{{ error }}</p><p v-if="status" role="status">{{ status }}</p>
    <section v-if="creating || !data" class="card">
      <form @submit.prevent="create()"><label>目的城市或区域<input v-model="destination" maxlength="80" placeholder="例如：苏州" required /></label><label>旅行想法（可留空）<textarea v-model="requestText" maxlength="500" placeholder="想玩几天、想做什么；不确定的可以以后再选" /></label><label>这次更接近<select v-model="kind"><option value="CITY">城市观光</option><option value="REGIONAL">跨地区旅行</option></select></label><button :disabled="busy || !destination.trim()">先看可比较的方向</button></form>
      <p>新旅行的天数、驾驶和包车意愿保持未知。仅使用当前目的地的本机资料。</p>
    </section>
    <details class="card"><summary>历史旅行与合成场景</summary><label>恢复本次旅行<select :value="data?.session_id || ''" @change="load(($event.target as HTMLSelectElement).value)"><option value="">请选择</option><option v-for="t in index?.trips" :key="t.session_id" :value="t.session_id">{{ t.destination }} · {{ t.demo ? '合成测试' : '本机私人草稿' }}</option></select></label><p>以下仅用虚构活动，测试输入不作为你的真实旅行偏好。</p><div class="actions"><button class="quiet" :disabled="busy" @click="create('CITY')">成都城市公交 · 合成</button><button class="quiet" :disabled="busy" @click="create('REGIONAL')">区域交通未定 · 合成</button><button class="quiet" :disabled="busy" @click="create('OTHER_CITY')">苏州两日 · 合成</button></div></details>
    <template v-if="data && form && !creating">
      <p class="notice">{{ data.demo ? '合成测试：全部项目为自编虚构活动；不是你的真实行程。' : '本机私人草案：本次旅行的选择不会成为长期偏好。' }} {{ data.cache_message }}</p>
      <section class="card stage"><div class="stage-title"><h2>1 · 大致方向</h2><button class="quiet" :disabled="busy" @click="toggle('direction')">{{ data.collapsed.direction ? '修改方向' : '收起' }}</button></div><p v-if="data.collapsed.direction">{{ label }} · 兴趣选择，可随时改选</p><div v-else class="suggestion-grid"><article v-for="d in data.directions" :key="d.id" class="direction"><small>{{ originLabel(d.origin) }}</small><h3>{{ d.label }}</h3><p>{{ d.advice }}</p><button :disabled="busy" @click="choose(d.id)">{{ form.direction === d.id ? '保留这个方向' : '选择这个方向' }}</button><button v-if="d.origin === 'SOURCE_REFERENCE'" class="quiet" :disabled="busy" @click="act('add_source', {option_id:d.id})">加入草稿作为组合建议</button></article></div><div v-if="data.direction_change_pending"><p>当前改选：{{ label }}；原方向仍可恢复，其他偏好保留。</p><div class="actions"><button :disabled="busy" @click="act('confirm_direction')">采用这个方向</button><button class="quiet" :disabled="busy" @click="act('cancel_direction')">取消方向改选</button></div></div></section>
      <section class="card stage"><div class="stage-title"><h2>2 · 想做的项目</h2><button class="quiet" :disabled="busy" @click="toggle('activities')">{{ data.collapsed.activities ? '修改项目' : '完成项目，继续时间' }}</button></div><p v-if="data.collapsed.activities">{{ form.activities.map(a => a.name).join(' → ') || '项目待选择' }}</p><template v-else><p>先排感兴趣的项目。日序和停留是可修改安排，来源条件会单独保留。</p><fieldset :disabled="busy" @change="act('save')"><article v-for="(a, i) in form.activities" :key="a.activity_id" class="activity-edit"><div class="input-grid"><label>项目名称<input v-model="a.name" maxlength="120" /></label><label>第几天<input v-model.number="a.day" type="number" min="1" max="90" /></label><label>建议停留最少（分钟）<input :value="a.stay_min ?? ''" type="number" min="0" max="720" @input="a.stay_min = number($event); if (a.stay_max === null) a.stay_max = a.stay_min" /></label><label>建议停留最多（分钟）<input :value="a.stay_max ?? ''" type="number" min="0" max="720" @input="a.stay_max = number($event)" /></label><label>活动后休息（分钟）<input :value="a.rest_minutes ?? ''" type="number" min="0" max="180" @input="a.rest_minutes = number($event)" /></label><label>已确定预约时间（可留空）<input :value="a.locked_start || ''" type="time" @input="a.locked_start = text($event)" /></label></div><p>{{ originLabel(a.provenance) }} · 时间：{{ originLabel(a.timing_origin) }}</p><details v-if="a.conditions.length || a.evidence_ids.length"><summary>来源条件与引用</summary><p v-for="c in a.conditions" :key="c">{{ c }}</p><p>引用：{{ a.evidence_ids.join('、') }}。组合顺序是系统/用户草案，不代表作者走过完整安排。</p></details><div class="actions"><button v-if="i > 0" type="button" class="quiet" @click="[form.activities[i-1], form.activities[i]] = [form.activities[i]!, form.activities[i-1]!]; act('save')">上移</button><button type="button" class="quiet" @click="form.activities.splice(i, 1); act('save')">移出草稿</button></div></article></fieldset><p v-if="!form.activities.length">尚无具体活动资料。可以先添加想做的项目；不会填入其他城市的景点。</p><button class="quiet" :disabled="busy || form.activities.length >= 24" @click="addActivity">添加想做的项目</button></template></section>
      <section class="card stage"><div class="stage-title"><h2>3 · 从几点开始，怎样安排</h2><button class="quiet" :disabled="busy" @click="toggle('conditions')">{{ data.collapsed.conditions ? '修改条件' : '收起' }}</button></div><p v-if="data.collapsed.conditions">首项 {{ form.inputs.activity_start || '时间未定' }} · {{ transportLabel(form.transport) }} · {{ form.inputs.planning_scope === 'ACTIVITY_WINDOW' ? '往返自行安排' : '包含门到门' }}</p><fieldset v-else :disabled="busy" @change="act('save')"><div class="input-grid"><label>规划范围<select v-model="form.inputs.planning_scope"><option value="ACTIVITY_WINDOW">我自行到达，从首个项目开始排</option><option value="DOOR_TO_DOOR">也帮我规划门到门往返</option></select></label><label>首个项目开始时间<input :value="form.inputs.activity_start || ''" type="time" @input="form.inputs.activity_start = text($event)" /></label><label>活动结束窗口（可留空）<input :value="form.inputs.activity_end || ''" type="time" @input="form.inputs.activity_end = text($event)" /></label><label>可用天数（可留空）<input :value="form.days ?? ''" type="number" min="1" max="90" @input="form.days = number($event)" /></label><label>从第几天开始<input v-model.number="form.first_day" type="number" min="1" max="90" /></label><label>只知道大致时段<select v-model="form.first_period"><option value="UNDECIDED">未定</option><option value="MORNING">上午</option><option value="AFTERNOON">下午</option><option value="EVENING">晚上</option></select></label><label>出行意向<select v-model="form.transport"><option value="UNKNOWN">还没想好，先比较建议</option><option value="PUBLIC_TRANSIT">公共交通优先</option><option value="SELF_DRIVE">自己驾驶</option><option value="LOCAL_SERVICE">比较当地服务（未落实）</option><option value="WALKING">步行优先</option></select></label><label>愿意自己开车吗<select v-model="form.driving"><option value="UNKNOWN">未定</option><option value="YES">愿意</option><option value="NO">不愿意</option></select></label></div><p>{{ data.travel_kind === 'CITY' ? '建议先比较公共交通加步行；交通意向由你决定。' : '可比较自驾/租车、到集散地后接当地服务、其他非自驾方式。这里只是类别，具体交通待核实。' }}</p><details><summary>包车意向、返回硬约束及路段参考模式</summary><label>单独的路段参考模式（不改变交通意向）<select v-model="form.inputs.mode"><option value="UNKNOWN">未决定</option><option value="TRANSIT">公共交通参考</option><option value="DRIVING">驾车道路参考</option><option value="WALKING">步行参考</option></select></label><label>包车意向<select v-model="form.inputs.charter"><option value="UNKNOWN">未定</option><option value="COMPARE">愿意比较</option><option value="NO">不接受</option></select></label><label>最晚到家时间（硬约束，可留空）<input :value="form.return_deadline || ''" type="time" @input="form.return_deadline = text($event)" /></label><p>即使自行安排往返，这个约束也会保留，未核实返程时不会宣称已经满足。</p></details><template v-if="form.inputs.planning_scope === 'DOOR_TO_DOOR'"><h3>往返细节</h3><label>出发公共地点<input v-model="form.inputs.origin" maxlength="80" placeholder="先用公共站点或地标" /></label><label class="check"><input v-model="form.inputs.same_return" type="checkbox" />返回出发点（可修改的产品假设）</label><label v-if="!form.inputs.same_return">异地结束地点<input v-model="form.inputs.destination" maxlength="80" /></label><label>出发日期时间<input type="datetime-local" :value="form.inputs.depart_at?.slice(0,16) || ''" @input="form.inputs.depart_at = text($event)" /></label><label>最晚返回日期时间<input type="datetime-local" :value="form.inputs.return_by?.slice(0,16) || ''" @input="form.inputs.return_by = text($event)" /></label><p>同一已确认地点可复用身份；往返两个方向的路程仍须分别核实。本批不查询地图。</p></template></fieldset></section>
      <section class="card stage"><h2>4 · 可编辑的时间草案</h2><div class="actions"><button :disabled="busy || !data.model_available || !form.activities.length" @click="act('suggest')">让AI比较两种安排</button><button v-if="data.job && ['QUEUED','RUNNING'].includes(data.job.status)" class="quiet" :disabled="busy" @click="act('cancel_job')">停止本次建议</button></div><p class="muted">AI建议仅在点击时生成。本批只允许两个合成场景；普通草稿、刷新、修改和折叠不调用模型。生成失败仍保留草稿。休息时间不会抵扣未知通行时间。</p><p v-if="data.job && ['QUEUED','RUNNING'].includes(data.job.status)" role="status">正在生成可修改建议，原采用版保留……</p><p v-if="data.job?.reason" class="warning">本次未生成可采用建议：{{ data.job.reason === 'STALE_PROPOSAL' ? '条件已变化，旧建议未采用' : '模型未完成或输出未通过约束检查' }}。不会自动重试。</p><details v-if="data.job?.proposals.length" :open="data.job.request_revision === data.revision"><summary>查看AI提议与取舍</summary><div class="suggestion-grid"><article v-for="(p, i) in data.job.proposals" :key="i" class="direction"><small>AI提议 · 未核实事实</small><h3>{{ p.title }}</h3><p>{{ readable(p.reason) }}</p><ol><li v-for="a in p.activities" :key="a.activity_id">第 {{ a.day }} 天 {{ form.activities.find(x => x.activity_id === a.activity_id)?.name || a.activity_id }} · 建议停留 {{ a.stay_min }}–{{ a.stay_max }} 分钟</li></ol><p>交通建议：{{ transportLabel(p.transport) }}，不自动改偏好。</p><details><summary>假设、未知与取舍</summary><p v-for="s in [...p.assumptions, ...p.unknowns, ...p.impacts]" :key="s">{{ readable(s) }}</p></details><button :disabled="busy || data.job.request_revision !== data.revision" @click="act('use_proposal', {proposal_index: i})">将此建议放入草稿</button><p v-if="data.job.request_revision !== data.revision" class="muted">当前条件已变化，旧建议不再覆盖草稿。</p></article></div></details><ol class="timeline"><li v-for="a in data.timeline" :key="a.activity_id"><strong>第 {{ a.day }} 天 · {{ a.start }}　{{ a.name }}</strong><p>结束：{{ a.end }}；{{ a.rest_minutes === null ? '休息待定' : `活动后休息建议 ${a.rest_minutes} 分钟` }}。{{ a.locked ? '预约锁定。' : '' }}{{ originLabel(a.timing_origin) }}</p></li></ol><ul class="warning"><li v-for="g in data.gaps" :key="g">{{ g }}</li></ul><p v-if="data.differences.length">与采用版相比：{{ data.differences.map(deltaLabel).join('、') }}发生变化；原采用版未覆盖。</p><div class="actions"><button :disabled="busy" @click="act('adopt')">采用这版草案</button><button class="quiet" :disabled="busy || !data.adopted" @click="act('cancel')">恢复已采用版</button><button class="quiet" :disabled="busy" @click="load(data.session_id)">刷新本地状态</button></div><details v-if="data.adopted"><summary>已采用版本</summary><p>{{ data.adopted.activities.map(a => a.name).join(' → ') || '尚未选项目' }}；首项 {{ data.adopted.inputs.activity_start || '未定' }}；{{ transportLabel(data.adopted.transport) }}。</p><p>采用是本次行程的选择，不证明交通、预约或整趟可行。</p></details></section>
      <PlanPlaces :plan="data" @refresh="load(data.session_id)" />
      <details class="card"><summary>依据与诊断</summary><p>当前目的地关联 {{ data.evidence_count }} 条已审核资料。模型额度累计 {{ index?.model_used ?? 0 }}/2（失败同样计数）。</p><p>新旅行默认：交通未知、返回同点为可修改假设；AI停留/顺序标建议，来源条件留在引用处。测试不进入长期偏好。</p><p>本批没有小红书和高德请求；真实交通可行性未测。G1 保持 NOT PASS。</p></details>
    </template>
  </section>
</template>
<style scoped>
.trip-toolbar,.stage-title { display:flex; align-items:center; justify-content:space-between; gap:1rem; } .stage { margin:1.1rem 0; } .stage h2 { margin:.3rem 0; } .suggestion-grid,.input-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem} .direction {border:1px solid #cbd4ca;border-radius:12px;padding:1rem} fieldset {border:0;padding:0;min-width:0} .activity-edit {border-bottom:1px solid #d7dfd5;padding:1rem 0} .check {display:flex;gap:.5rem;align-items:center} .check input {width:auto} .timeline li {padding:.6rem 0} details.card {margin:1rem 0} @media(max-width:650px){.suggestion-grid,.input-grid{grid-template-columns:1fr}.trip-toolbar{align-items:start}}
</style>
