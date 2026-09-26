<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import EvidenceList from './components/EvidenceList.vue'
import ResearchPanel from './components/ResearchPanel.vue'
import { readIndex, request, roleLabel, type View, type Research, type Option } from './api'
const view = ref<View | null>(null)
const researches = ref<Research[]>([])
const mode = ref('')
const workbenchAvailable = ref(false)
const input = ref('')
const researchId = ref('')
const busy = ref(false)
const error = ref('')
const status = ref('')
const days = ref<number | ''>('')
const driving = ref('UNKNOWN')
const preferenceText = ref('')
let generation = 0
const current = computed(() => view.value?.options.find(o => o.option_id === view.value?.confirmed_option_id))
const proposed = computed(() => view.value?.options.find(o => o.option_id === view.value?.preview?.option_id))
const routes = (o: Option) => o.evidence.filter(e => o.route_evidence_ids.includes(e.claim_id))
const experiences = (o: Option) => o.evidence.filter(e => o.experience_evidence_ids.includes(e.claim_id))
const driveLabel = (v: string) => ({YES: '愿意自己开车', NO: '不想自己开车', UNKNOWN: '驾驶意愿未知'}[v] || '未知')
const diffs = [['added', '新增兴趣'], ['removed', '移除兴趣'], ['retained', '保留兴趣'], ['gaps_added', '新增待核实'], ['gaps_removed', '不再属于本方向的缺口'], ['gaps_retained', '仍待核实']] as const
function apply(result: View, ticket: number) {
  if (ticket !== generation) return
  if (view.value?.session_id === result.session_id && view.value.revision > result.revision) return
  view.value = result; input.value = result.input_text
  researchId.value = result.research_id || ''
  days.value = result.preferences.days ?? ''; driving.value = result.preferences.driving
}
async function run(action: (ticket: number) => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; status.value = ''
  const ticket = ++generation
  try { await action(ticket) } catch (e) { error.value = e instanceof Error ? e.message : '本地操作失败，请刷新后查看。' }
  finally { if (ticket === generation) busy.value = false }
}
async function load() {
  await run(async ticket => {
    const result = await readIndex()
    if (ticket !== generation) return
    researches.value = result.researches; mode.value = result.mode; workbenchAvailable.value = result.workbench_available
    if (result.session) { apply(result.session, ticket); status.value = '已从本机恢复选择和资料。' }
  })
}
async function start() {
  await run(async ticket => {
    apply(await request<View>('/api/v1/preview/sessions', {research_id: researchId.value || null, text: input.value}), ticket)
    status.value = '已读取本机资料，没有发起新研究。'
  })
}
async function change(action: string, patch: Record<string, unknown> = {}) {
  if (!view.value) return
  const before = view.value
  await run(async ticket => {
    apply(await request<View>('/api/v1/preview/sessions/' + before.session_id, {action, expected_revision: before.revision, ...patch}), ticket)
    await nextTick()
    if (action === 'preview') document.querySelector('.proposal')?.scrollIntoView({block: 'start'})
    status.value = action === 'confirm' ? '兴趣方向已确认；路线可行性仍待核实。' : action === 'cancel' ? '已取消改选，保留原确认方向。' : '已保存本次选择。'
  })
}
onMounted(load)
</script>
<template>
  <main>
    <header><a class="brand" href="/">TravelAgent<span>先看方向，再做决定</span></a><span class="badge">{{ mode === 'SYNTHETIC_DEMO' ? 'SYNTHETIC_DEMO · 合成演示' : mode === 'CACHED_PRIVATE_PREVIEW' ? 'CACHED_PRIVATE_PREVIEW · 本机私人资料' : '本机开发预览' }}</span></header>
    <p class="notice">缓存驱动开发预览；尚未核实当前行程可行性。{{ workbenchAvailable ? '浏览资料保持零外部调用；只有主动研究并满足门槛时才访问授权服务。' : '本轮仅使用已审核的本地资料，不启动小红书、不调用模型。' }}</p>
    <section class="intro"><p class="eyebrow">从已知的线索，找想去的方向</p><h1>先有一个旅行想法。</h1><p>不用先填完问卷。先比较来源支持的草案，再补充天数和驾驶意愿。预算、人数与交通方式可以暂时未知。</p></section>
    <form class="intake card" @submit.prevent="start">
      <label for="request">你想怎样旅行？</label><textarea id="request" v-model="input" maxlength="500" rows="2" placeholder="说说目的区域或假期，也可以直接选择下面的已有研究。" />
      <div class="form-row"><div class="grow"><label for="research">继续已有研究</label><select id="research" v-model="researchId"><option value="">按输入匹配本机缓存（不启动新研究）</option><option v-for="r in researches" :key="r.research_id" :value="r.research_id">{{ r.label }} · {{ r.evidence_count }} 条审核记录 · {{ r.research_id }}</option></select></div><button type="submit" :disabled="busy || !mode">查看本地草案</button></div>
      <p class="muted">匹配仅识别明确的目的地区域；多个已有研究时请从列表选择。未命中不会使用合成资料替代。</p>
    </form>
    <p v-if="error" role="alert" class="error">{{ error }} <button class="quiet" :disabled="busy" @click="load">重新读取本机状态</button></p>
    <p role="status" aria-live="polite" class="status">{{ busy ? '正在读取本机状态…' : status }}</p>
    <ResearchPanel v-if="view && workbenchAvailable" :key="view.session_id" :view="view" @adopt="result => apply(result, ++generation)" />
    <div v-if="view" class="workspace">
      <section class="drafts" aria-label="路线草案">
        <div class="section-heading"><div><p class="eyebrow">已审核资料 · 图片未分析</p><h2>有依据的草案与日段</h2></div><span>{{ view.options.length }} 组</span></div>
        <p class="muted">{{ view.evidence_count }} 条审核记录来自 {{ view.source_count }} 个来源；记录数不是独立事实数。来源独立性未知。 <a href="#preferences">查看条件和待核实项 ↓</a></p>
        <p v-if="view.cache_message" class="card" data-testid="cache-miss">{{ view.cache_message }}</p>
        <p v-if="view.stale" class="warning">缓存依据已变化，已保留原选择记录。请重新选择已有研究后继续，不能确认过期预览。</p>
        <p v-if="view.interest_needs_confirmation" class="warning">原兴趣“{{ view.previous_interest || '已保存方向' }}”的依据或对象已变化；原记录保留。请预览并确认新的兴趣方向。</p>
        <article v-for="(o, index) in view.options" :key="o.option_id" class="option card" :data-option-id="o.option_id">
          <div class="option-top"><span class="option-number">{{ String(index + 1).padStart(2, '0') }}</span><span v-if="o.option_id === view.confirmed_option_id" class="badge">已确认兴趣</span><span v-else class="muted">适配待核实</span></div>
          <h3>{{ o.label }}</h3><p class="role">{{ o.reference_kinds.map(roleLabel).join(' / ') }}</p>
          <p class="schedule" v-if="o.source_schedule.day_count !== null">来源编排为 {{ o.source_schedule.day_count }} 个行程日；不是实测所需天数。</p><p class="schedule" v-else>当前对象只有局部或不连续日序；不推算整趟天数。</p>
          <ol class="route-list"><li v-for="row in routes(o)" :key="row.claim_id">{{ row.text }}</li></ol>
          <div class="source-conditions"><h4>来源交通条件（原文，非用户偏好）</h4><p v-for="row in o.source_transport_conditions.slice(0, 2)" :key="row.text">{{ row.text }}</p><p v-if="!o.source_transport_conditions.length">当前对象的交通条件未知。</p><h4>来源季节／时间条件（未核实当前适用性）</h4><p v-for="row in o.source_time_conditions.slice(0, 1)" :key="row.text">{{ row.text }}</p><p v-if="!o.source_time_conditions.length">季节及旅行时间未知。</p><p class="muted">摘要仅展示部分条件；全部条件和对应引用见下方证据依据。</p></div>
          <div v-if="experiences(o).length"><h4>同一对象的体验线索</h4><p v-for="row in experiences(o)" :key="row.claim_id">{{ row.text }}</p></div>
          <div class="unknown-grid"><p>用户实际耗时<strong>未知</strong></p><p>预算与价格<strong>未知</strong></p><p>交通与接驳适配<strong>待核实</strong></p></div>
          <p class="muted">{{ o.source_count }} 个来源 · {{ o.opinion_count }} 个同源去重观点。草案与日段不能直接拼成完整可行路线。</p>
          <details><summary>来源条件、交通及证据依据（{{ o.evidence.length }} 条）</summary><EvidenceList :rows="o.evidence" /></details>
          <div class="option-footer"><button :disabled="busy || view.stale" @click="change('preview', {option_id: o.option_id})">{{ view.confirmed_option_id ? '预览改选此方向' : '预览此方向' }}</button><span>确认兴趣后仍需核实可行性</span></div>
        </article>
        <details v-if="view.other_clues.length" class="card"><summary>其他兴趣线索（{{ view.other_clues.length }} 条，尚未关联成路线）</summary><EvidenceList :rows="view.other_clues" /></details>
      </section>
      <aside aria-label="选择与条件">
        <section id="preferences" class="card preferences"><p class="eyebrow">你的条件 · 可随时修改</p><h2>{{ view.questions.length ? '先确定两件事' : '已保存的条件' }}</h2>
          <p>时间表达：{{ view.preferences.time_hint || '未知' }}；具体日期、年份：{{ view.preferences.travel_date || '未确认' }}</p>
          <p>当前：{{ view.preferences.days ? view.preferences.days + ' 天' : '天数未知' }} · {{ driveLabel(view.preferences.driving) }}</p>
          <p class="muted">预算 {{ view.preferences.budget_cny_fen === null ? '未知' : view.preferences.budget_cny_fen / 100 + '元' }} · 人数 {{ view.preferences.traveler_count ?? '未知' }} · 包车偏好未知</p>
          <p v-if="view.clarification" class="warning">{{ view.clarification }}</p>
          <div v-for="q in view.questions" :key="q.field" class="guidance"><strong>{{ q.title }}</strong><p>{{ q.advice }}</p></div>
          <label for="days">可用天数</label><div class="day-buttons"><button v-for="n in [3, 5, 7]" :key="n" class="quiet" :aria-pressed="days === n" :disabled="busy" @click="days = n">{{ n }} 天</button><button class="quiet" :disabled="busy" @click="days = ''">暂不确定</button></div><input id="days" v-model="days" type="number" min="1" max="90" placeholder="自定义天数 / 留空未知" />
          <label for="driving">是否愿意自己开车</label><select id="driving" v-model="driving"><option value="UNKNOWN">暂不确定</option><option value="YES">愿意</option><option value="NO">不想开</option></select>
          <button :disabled="busy || view.stale || (days !== '' && (days < 1 || days > 90))" @click="change('preferences', {preferences: {days: days === '' ? null : Number(days), driving}})">保存条件</button>
          <details><summary>用一句话补充条件</summary><p class="muted">有限规则解析，只支持明确天数和驾驶意愿；歧义会请你确认。</p><label for="preference-text">例如：我只有五天，而且不想自驾</label><input id="preference-text" v-model="preferenceText" maxlength="500" /><button :disabled="busy || view.stale" @click="change('preferences', {text: preferenceText})">应用明确条件</button></details>
        </section>
        <section class="card selection"><p class="eyebrow">当前确认的兴趣方向</p><h2 data-testid="confirmed">{{ current?.label || (view.confirmed_option_id ? '原方向依据已变化，请重新选择' : '还未确认') }}</h2><p>兴趣选择 ≠ 路线可行性验证。</p></section>
        <section v-if="view.preview && proposed" class="card proposal" data-testid="proposal"><p class="eyebrow">更换前，先看变化</p><h2>{{ proposed.label }}</h2>
          <template v-for="[key, title] in diffs" :key="key"><h4>{{ title }}</h4><ul v-if="view.preview[key].length"><li v-for="item in view.preview[key]" :key="item">{{ item }}</li></ul><p v-else class="muted">无</p></template>
          <p class="muted">未确认前保持原方向；移除不表示长期不喜欢。价格和时间差未知。</p><div class="actions"><button :disabled="busy || view.stale" @click="change('confirm', {option_id: proposed.option_id})">确认兴趣方向</button><button class="quiet" :disabled="busy || view.stale" @click="change('cancel')">取消改选</button></div>
        </section>
        <section class="card gaps"><p class="eyebrow">下一步要核实什么</p><h2>保留这些缺口</h2><ul><li v-for="gap in view.gaps" :key="gap">{{ gap }}</li></ul><p class="muted">缺口保留；只有主动研究才可能补充资料。不会把来源七日草案删两天后当作五天可行行程。</p></section>
      </aside>
    </div>
    <section v-else-if="!busy && mode" class="card empty"><h2>先选一份已有研究</h2><p>页面将从数据库中的已审核证据生成草案。未给预算或人数，也能先看。</p></section>
    <footer>G0 仅保留历史验收；G1 仍 NOT PASS。此页面不是完整旅行产品或发布验收。缓存显示不会探测小红书或模型；地图与报价未接入。</footer>
  </main>
</template>
