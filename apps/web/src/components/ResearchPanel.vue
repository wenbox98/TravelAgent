<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request, type View, type Job, type Workbench } from '../api'
const props = defineProps<{view: View}>()
const emit = defineEmits<{adopt: [view: View]}>()
const workbench = ref<Workbench | null>(null)
const busy = ref(false)
const error = ref('')
const destination = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let requestKey = crypto.randomUUID()
const job = computed(() => workbench.value?.jobs.find(j => j.session_id === props.view.session_id))
const active = (j: Job | undefined) => !!j && ['QUEUED','RUNNING','WAITING_LOGIN'].includes(j.status)
const labels: Record<string,string> = {QUEUED:'已排队', RUNNING:'正在研究', WAITING_LOGIN:'等待你正常登录', VERIFICATION_REQUIRED:'页面要求验证，已停止自动访问', PARTIAL:'获得部分材料，缺口仍保留', COMPLETED:'材料处理完成', NEEDS_REVIEW:'本轮没有可采用的新材料', FAILED:'本轮未完成', CANCELED:'已取消后续步骤', INTERRUPTED:'进程已中断，未自动重试'}
async function refresh() {
  try { workbench.value = await request<Workbench>('/api/v1/preview/workbench') }
  catch (e) { error.value = e instanceof Error ? e.message : '状态读取失败；未重新派发。' }
  finally {
    if (!disposed && workbench.value?.jobs.some(active)) timer = setTimeout(refresh, 1500)
  }
}
async function start() {
  if (busy.value || !workbench.value?.enabled) return
  busy.value = true; error.value = ''
  try {
    await request<Job>('/api/v1/preview/jobs', {session_id: props.view.session_id, expected_revision: props.view.revision,
      destination: props.view.research_id ? null : destination.value.trim() || null}, requestKey)
    requestKey = crypto.randomUUID()
  } catch (e) { error.value = e instanceof Error ? e.message : '派发状态不明，请先查看本地任务，勿重试。' }
  finally { busy.value = false; await refresh() }
}
async function act(action: 'cancel' | 'adopt') {
  if (!job.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const result = await request<Job | View>('/api/v1/preview/jobs/' + job.value.job_id, {action, expected_revision: props.view.revision})
    if (action === 'adopt') emit('adopt', result as View)
  } catch (e) { error.value = e instanceof Error ? e.message : '本地操作未提交。' }
  finally { busy.value = false; await refresh() }
}
onMounted(refresh)
onUnmounted(() => {disposed = true; clearTimeout(timer)})
</script>
<template>
  <section class="card live-research" aria-label="有限研究" data-testid="research-panel">
    <p class="eyebrow">主动补充 · 一次有界研究</p><h2>{{ view.research_id ? '根据当前缺口补充研究' : '从明确目的区域开始研究' }}</h2>
    <p>查看缓存、刷新和修改条件均不联网。只有下方研究按钮会启动授权范围内的新资料研究。</p>
    <template v-if="workbench">
      <p class="muted">{{ workbench.data_use }}</p>
      <p>本轮剩余额度：搜索 {{ workbench.budget.remaining.search }} 次、详情 {{ workbench.budget.remaining.detail }} 篇、模型 {{ workbench.budget.remaining.model }} 次。失败也消耗已派发额度。</p>
      <p v-if="!workbench.configured" class="warning">模型配置或本轮许可不可用；本地资料仍可浏览。</p>
      <p v-else-if="workbench.budget.gate !== 'PASS'" class="warning">缓存自动审核门槛尚未通过；真实研究未开放。</p>
      <p v-else-if="workbench.budget.closed" class="muted">本轮验证已结束，保留材料和未用额度记录，不再派发。</p>
      <template v-if="!view.research_id"><label for="destination">确认要研究的目的区域（仅此项决定搜索目标）</label><input id="destination" v-model="destination" maxlength="80" placeholder="输入明确目的区域" /></template>
      <button data-testid="start-research" :disabled="busy || !workbench.enabled || view.stale || (!view.research_id && !destination.trim())" @click="start">{{ view.research_id ? '补充研究（最多读一篇）' : '开始研究（最多读一篇）' }}</button>
      <div v-if="job" class="job-result" aria-live="polite">
        <h3>{{ labels[job.status] || job.status }}</h3>
        <p v-if="job.status === 'WAITING_LOGIN'" class="warning">现在请在打开的小红书官方页面完成正常登录。页面会观察同一个会话；不要提供 Cookie 或 token。</p>
        <p v-if="job.status === 'VERIFICATION_REQUIRED'" class="warning">请保留实际页面状态；本轮不会继续访问或尝试规避。</p>
        <p>新增合格材料 {{ job.new_evidence_count }} 条 · 待审 {{ job.pending }} 条 · 拒绝 {{ job.rejected }} 条。</p>
        <p class="muted">模型检查了原文支持关系，未核实当前可行性。未采用前保留当前兴趣和条件。</p>
        <button v-if="job.can_adopt" data-testid="adopt-materials" :disabled="busy" @click="act('adopt')">采用新材料，保留我的条件</button>
        <button v-if="active(job)" class="quiet" :disabled="busy || job.cancel_requested" @click="act('cancel')">{{ job.cancel_requested ? '正在停止后续派发' : '取消后续研究' }}</button>
        <p v-if="job.cancel_requested" class="muted">已发出的请求不能撤回，仍计入额度；不会自动重试。</p>
      </div>
    </template>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
  </section>
</template>
