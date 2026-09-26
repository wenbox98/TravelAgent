<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request, type View, type ReviewIndex, type ReviewUpdate } from '../api'
const props = defineProps<{view: View}>()
const emit = defineEmits<{adopt: [view: View]}>()
const data = ref<ReviewIndex | null>(null)
const error = ref('')
const busy = ref(false)
const proposed = ref<ReviewUpdate | null>(null)
async function load() {
  error.value = ''
  try { data.value = await request<ReviewIndex>('/api/v1/preview/reviews') }
  catch (e) { error.value = e instanceof Error ? e.message : '待审说明暂不可用。' }
}
async function adopt() {
  if (!proposed.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    const result = await request<View>('/api/v1/preview/review-update', {
      session_id: props.view.session_id, expected_revision: props.view.revision,
      revalidation_id: proposed.value.revalidation_id
    })
    emit('adopt', result); proposed.value = null; await load()
  } catch (e) { error.value = e instanceof Error ? e.message : '更新未采用，请重新读取状态。' }
  finally { busy.value = false }
}
const actionLabel = (s: string) => ({ACCEPT: '条件参考', NEEDS_REVIEW: '待审', REJECT: '拒绝'}[s] || '未知')
onMounted(load)
</script>
<template>
  <section class="card" aria-label="待审理由与本地更新">
    <h2>资料审核说明</h2>
    <p>{{ data?.message || '正在读取本机审核记录…' }}</p>
    <p v-if="error" role="alert">{{ error }} <button @click="load">重新读取审核说明</button></p>
    <p v-if="data && !data.items.length">暂无可展示的审核记录；不会自动发起审核。</p>
    <details v-if="data?.items.length" data-testid="pending-reasons">
      <summary>展开待审原因及逐条对照（{{ data.items.filter(i => i.action === 'NEEDS_REVIEW').length }} 条待审记录，含历史与新版本）</summary>
      <article v-for="(item, i) in data.items" :key="i" class="evidence-item">
        <p><strong>{{ item.source_label }} · 候选 {{ item.candidate_index }} · {{ item.topic }} · {{ actionLabel(item.action) }}</strong></p>
        <p>{{ item.origin }} · 规则 v{{ item.rule_version }}</p>
        <p>{{ item.category }}：{{ item.explanation }}</p>
        <blockquote v-if="item.quote">{{ item.quote }}</blockquote>
        <p v-if="item.locator" class="muted">引用片段：{{ item.locator }}</p>
        <p v-if="item.conversion">{{ item.conversion }}</p>
        <p>后续建议：{{ item.next_action }}</p>
        <details><summary>查看原因代码</summary>{{ item.reason_code }}</details>
      </article>
    </details>
    <template v-for="update in data?.updates || []" :key="update.revalidation_id">
      <p v-if="view.research_id === update.research_id">已采用本地更新：{{ update.evidence_count }} 条参考。模型没有重新作答。</p>
      <div v-else>
        <p>本地校验新增 {{ update.added }} 条带条件参考；可查看 {{ update.evidence_count }} 条资料。原选择尚未改变。</p>
        <button :disabled="busy" @click="proposed = update">预览本地更新</button>
      </div>
    </template>
    <div v-if="proposed" class="proposal" data-testid="replay-preview">
      <h3>采用前确认</h3>
      <p>资料从当前 {{ view.evidence_count }} 条更新至 {{ proposed.evidence_count }} 条；保持当前兴趣与用户偏好。若原兴趣依据变化，将保留记录并提示重新确认。</p>
      <p>天数：{{ view.preferences.days ?? '未知' }}；驾驶：{{ view.preferences.driving === 'NO' ? '不自驾' : '沿用当前选择' }}。新增资料仍不能证明完整可行路线。</p>
      <button :disabled="busy" @click="adopt">采用本地更新</button>
      <button class="quiet" :disabled="busy" @click="proposed = null">取消本地更新</button>
    </div>
  </section>
</template>
