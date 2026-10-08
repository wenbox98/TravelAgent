<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PlanView } from '../planning-api'
const props = defineProps<{ plan: PlanView; busy: boolean }>()
const emit = defineEmits<{action:[action:string, extra:Record<string,unknown>]}>()
const editing = ref(false), planning = ref(true), research = ref(false), maps = ref(false)
const limits = ref({model:2, connect:0, search:0, detail:0, map_place:0, map_route:0, hours:24})
watch(() => props.plan.session_id, () => {editing.value=false})
const names:Record<string,string> = {model:'模型', connect:'登录连接', search:'搜索', detail:'详情', map_place:'地点', map_route:'路径'}
const configuration = (s:string) => s === 'CONFIGURED_NOT_VERIFIED' ? '已配置，未额外测试凭证' : '未配置'
const availability = (s:string) => ({NOT_CONFIGURED:'未配置',NOT_AUTHORIZED:'未授权',CLOSED:'许可已关闭',EXPIRED:'许可已到期',BUDGET_EXHAUSTED:'剩余额度不足',RUNNING:'任务运行中',AVAILABLE:'已获准，可主动操作'}[s] || '请查看当前条件')
const permitState = (s:string) => ({ACTIVE:'许可有效',CLOSED:'本次许可已关闭',EXPIRED:'许可已到期'}[s] || '未授权')
function authorize() {
  const tasks = [...(planning.value ? ['PLANNING','REVISION'] : []), ...(research.value ? ['RESEARCH'] : []), ...(maps.value ? ['MAP'] : [])]
  const l = {...limits.value, ...(!research.value ? {connect:0,search:0,detail:0} : {}), ...(!maps.value ? {map_place:0,map_route:0} : {})}
  emit('action','authorize',{authorization:{confirm:true,tasks,...l}})
  editing.value = false
}
</script>
<template>
  <section v-if="plan.operation" id="operation-permission" class="card stage operation-panel">
    <div class="stage-title"><h2>本次旅行的外部操作</h2><button class="quiet" :disabled="busy" @click="editing = !editing">{{ plan.operation.history.length ? '明确追加额度' : '设置有限操作许可' }}</button></div>
    <p>模型：{{ configuration(plan.operation.model_configuration) }}；地图：{{ configuration(plan.operation.map_configuration) }}。配置存在不代表已授权。</p>
    <p>研究：{{ availability(plan.operation.research_status) }}；地图：{{ availability(plan.operation.map_status) }}。规划是否可执行还取决于当前项目和修改条件。</p>
    <p v-if="!plan.operation.current">尚未授权。新建、复用资料、编辑、刷新和采用已有结果都在本机完成。</p>
    <template v-else>
      <p>{{ permitState(plan.operation.status) }}；失败或超时也保留已派发次数，不自动重试。</p>
      <div class="quota"><span v-for="(value,key) in plan.operation.cumulative_used" :key="key">{{ names[key] }}累计 {{ value }} · 可用 {{ plan.operation.active ? plan.operation.current.remaining[key] : 0 }}</span></div>
      <button v-if="plan.operation.active" class="quiet" :disabled="busy" @click="emit('action','revoke_authorization',{})">关闭本次许可，保留记录</button>
    </template>
    <div v-if="editing" class="permission-form">
      <p>只授权当前旅行和本页选择的资料。确认后仍需主动点击研究、AI建议或地图查询；不会立刻发送。</p>
      <label class="check"><input v-model="planning" type="checkbox" />允许生成安排与改选（DeepSeek）</label>
      <label class="check"><input v-model="research" type="checkbox" />允许主动查找新资料及提取、审核（小红书与 DeepSeek）</label>
      <label class="check"><input v-model="maps" type="checkbox" />允许公共地点和分段路程查询（高德）</label>
      <div class="input-grid">
        <label>新增模型次数上限<input v-model.number="limits.model" type="number" min="0" max="20" /></label>
        <template v-if="maps"><label>新增地点查询上限<input v-model.number="limits.map_place" type="number" min="0" max="16" /></label><label>新增路径查询上限<input v-model.number="limits.map_route" type="number" min="0" max="16" /></label></template>
      </div>
      <details :open="research"><summary>数据范围与高级额度</summary>
        <p>必要公开名称、来源提及和过滤条件，每来源每次最多6000字发送至 api.deepseek.com；不发送私址、凭据或地图返回。高德仅接收确认的公共地点和适用参数（restapi.amap.com）。研究使用普通官方登录，遇验证停止。模型次数包含每次提取、独立审核、规划和改选，不仅最终建议。</p>
        <p>一次新研究至少留出提取、审核与最终规划的3次模型额度。达到足够资料时早停，不承诺用完上限。追加会关闭前许可的未来派发，旧用量和失败不改写；未用额度不转移。</p>
        <template v-if="research"><label>新增登录连接上限<input v-model.number="limits.connect" type="number" min="0" max="1" /></label><label>新增搜索上限<input v-model.number="limits.search" type="number" min="0" max="3" /></label><label>新增详情上限<input v-model.number="limits.detail" type="number" min="0" max="6" /></label></template>
        <label>本许可有效小时<input v-model.number="limits.hours" type="number" min="1" max="168" /></label>
      </details>
      <button :disabled="busy || (!planning && !research && !maps)" @click="authorize">{{ plan.operation.history.length ? '确认追加以上有限额度' : '确认以上用途与调用上限' }}</button>
    </div>
    <details v-if="plan.operation.history.length"><summary>查看累计许可与消耗</summary><article v-for="(grant,i) in plan.operation.history" :key="i"><p>第 {{ i+1 }} 次许可 · {{ grant.current ? '当前' : '历史' }} · {{ grant.closed ? '已关闭' : grant.expired ? '已到期' : '有效' }} · {{ grant.recipients.join('、') }}</p><p v-for="(limit,key) in grant.limits" :key="key">{{ names[key] }}：已用 {{ grant.used[key] }} / 上限 {{ limit }}</p></article></details>

  </section>
</template>
<style scoped>.quota{display:flex;flex-wrap:wrap;gap:.8rem}.permission-form{border:1px solid #cbd4ca;border-radius:12px;padding:1rem;margin:1rem 0}.input-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}.check{display:flex;align-items:center;gap:.6rem}.check input{width:auto}.stage-title{display:flex;justify-content:space-between;align-items:center;gap:1rem}details{margin:.8rem 0}</style>
