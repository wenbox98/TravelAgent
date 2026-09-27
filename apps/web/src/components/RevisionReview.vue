<script setup lang="ts">
import type { PlanView } from '../planning-api'
const props = defineProps<{job: NonNullable<PlanView['job']>; busy: boolean}>()
defineEmits<{action: [action: string, extra: Record<string, unknown> ]}>()
const name = (id: string) => props.job.base_activities?.find(a => a.activity_id === id)?.name || '原项目'
const field = (key: string) => ({stay_min:'停留下界',stay_max:'停留上界',rest_minutes:'活动后休息',day:'日序',activity:'项目'}[key] || '安排')
const reason = (s: string) => ({REVISION_NOT_LONGER:'目标停留没有按要求增加',REVISION_NOT_FEWER:'没有恰好减少一个项目',REVISION_TARGET_CHANGED:'改变了修改目标或原项目顺序',REVISION_UNREQUESTED_CHANGE:'修改了本次未请求调整的项目',REVISION_SCHEMA:'返回了协议不允许的字段或类型',REVISION_INTENT_MISMATCH:'没有执行本次修改意图',PLANNING_UNKNOWN_REFERENCE:'活动或引用不属于本次输入',PLANNING_LOCKED_CONSTRAINT:'违反预约或硬截止',PLANNING_INVALID_TIME:'停留区间或日序无效',REVISION_ENVELOPE:'响应结构或安全检查未通过'}[s] || '未通过约束检查')
</script>
<template>
  <section class="revision-review">
    <p>本次修改：{{ job.generated_count ?? 0 }} 个提议，{{ job.accepted_count }} 个通过结构与意图检查，{{ job.rejected_count }} 个拒绝；说明隔离 {{ job.isolated_count ?? 0 }} 个。</p>
    <p v-if="job.reason" class="warning">这次修改未采用，原版保留；{{ job.decisions.length ? reason(job.decisions[0].reason) : '模型未完成或条件已变化' }}。不会自动重试。</p>
    <details v-if="job.proposals.length" :open="job.can_preview"><summary>查看已存修改与前后差异</summary>
      <article v-for="(p,i) in job.proposals" :key="p.proposal_id || i" class="revision-choice">
        <h3>{{ p.title }}</h3><p>基于发起时采用版；首项 {{ p.first_start }}、原交通和其他固定条件保留。</p>
        <ul><li v-for="(c,j) in p.changes" :key="j">{{ name(c.activity_id) }} · {{ field(c.field) }}：{{ c.field === 'activity' ? '保留 → 本版移除' : `${c.before} → ${c.after}${c.field === 'day' ? '' : ' 分钟'}` }}</li></ul>
        <p>未列出的项目与停留保留；到达时间待交通核实。停留是 AI 建议，地点提及不是作者亲历。</p>
        <button :disabled="busy || !job.can_preview" @click="$emit('action','use_proposal',{proposal_index:i})">预览这版修改</button>
        <p v-if="!job.can_preview">当前正在预览或采用版已变化；取消预览可重新展示同一提议，无需再次生成。</p>
      </article>
    </details>
    <details><summary>本次修改诊断</summary><p>规则 {{ job.rule_version }}；基准修订 {{ job.base_revision }}。已返回：{{ job.returned ? '是' : '否' }}；已解析：{{ job.parsed ? '是' : '否' }}。原采用版不受任务失败影响。</p>
      <p v-for="d in job.decisions" :key="d.proposal_id">{{ d.status === 'ACCEPTED' ? '通过意图检查' : reason(d.reason) }} · {{ d.field || '结构差异' }} · {{ d.stage }} / {{ d.rule_id }}</p>
      <p>安全本地复核：{{ job.local_diagnostic?.replayable ? '可用，受限记录默认保留7天' : '不可用，不保存不安全内容' }}。被拒文字不在主页面展示。</p>
    </details>
  </section>
</template>
<style scoped>.revision-choice{border:1px solid #cbd4ca;border-radius:12px;padding:1rem;margin:.7rem 0}.revision-review li{margin:.4rem 0}</style>
