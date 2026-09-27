<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PlanView } from '../planning-api'
import PlanPlaces from './PlanPlaces.vue'
const props = defineProps<{plan: PlanView; busy: boolean}>()
const emit = defineEmits<{action:[action:string, patch:Record<string, unknown>]; refresh:[]}>()
const selected = ref<string[]>([])
watch(() => props.plan.session_id, () => {selected.value=[]})
const reason = (v:string) => ({PRIVATE_OR_IDENTIFIER:'含私人信息',UNSAFE_INSTRUCTION:'不安全内容',FICTION_OR_EXAMPLE:'虚构或示例',ACCESS_RESTRICTION:'存在访问限制',FILTERED_CONTEXT:'必要上下文未通过过滤',NEGATIVE_CONTEXT:'含否定评价',HYPOTHETICAL:'含假设或计划',AUTHOR_ROLE_UNVERIFIED:'作者角色未核实'}[v] || '需核实')
</script>
<template>
  <section class="card stage"><h2>从缓存发现待核实地点</h2>
    <p>先核对公开地点，再安排临时草案。名称被提及不等于作者推荐、已审核证据或当前可游玩；原审核结果保留。</p>
    <button v-if="!plan.place_leads.length" :disabled="busy || !plan.discovery_available" @click="emit('action','discover_places',{})">从当前缓存识别公共地点（本地）</button>
    <article v-for="lead in plan.place_leads" :key="lead.lead_id" class="lead">
      <label class="check"><input v-model="selected" type="checkbox" :value="lead.lead_id" :disabled="busy || lead.quarantined || lead.identity_status !== 'CHECKED' || lead.spatial_status === 'MISMATCH'" />{{ lead.public_name }}</label>
      <p>{{ lead.identity_status === 'CHECKED' ? '地点身份曾匹配；实时地图在下方查看' : '地点身份待检查' }} · {{ lead.spatial_status === 'MISMATCH' ? '来源指向当前范围以外' : '市区范围待核实' }} · 可游玩性未知</p>
      <p v-if="lead.identity_origin === 'PROGRAM_SUGGESTED_MATCH'">程序建议：名称、地区和对象类型唯一匹配，可在地点列表展开修改。</p>
      <p v-if="lead.quarantined" class="warning">已隔离：{{ lead.quarantine_reasons.map(reason).join('、') }}；不发送查询。</p>
      <details><summary>查看发现依据与原审核状态</summary><p>仅证明原文提及名称；精确位置 {{ lead.start }}–{{ lead.end }}。</p><blockquote v-for="b in lead.parent_blocks" :key="b.block_index">{{ b.text }}</blockquote><p>{{ lead.context_flags.map(reason).join('；') }}</p><p>原候选：{{ lead.claim_references.filter(r=>r.context_status==='PENDING').length }} 待审 / {{ lead.claim_references.filter(r=>r.context_status==='REJECTED').length }} 拒绝 / {{ lead.claim_references.filter(r=>r.context_status==='ACCEPTED').length }} 已接纳。地点发现不会改变它们。</p></details>
    </article>
    <p v-if="plan.place_leads.length">建议先核对最感兴趣的少量地点。接受下列暂定项目只表示它们符合你这次的范围意图，不是地理证明；未核实条件继续保留。</p>
    <button v-if="plan.place_leads.length" :disabled="busy || !selected.length" @click="emit('action','use_leads',{activity_ids:selected})">接受所选地点作为暂定项目</button>
    <PlanPlaces v-if="plan.place_leads.length" :plan="plan" @refresh="emit('refresh')" />
  </section>
</template>
<style scoped>.lead{border-top:1px solid #d7dfd5;padding:1rem 0}.check{display:flex;align-items:center;gap:.6rem}.check input{width:auto}</style>
