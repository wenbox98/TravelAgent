<script setup lang="ts">
import { roleLabel, type Evidence } from '../api'
defineProps<{ rows: Evidence[] }>()
</script>
<template>
  <article v-for="row in rows" :key="row.claim_id" class="evidence-item">
    <p class="eyebrow">{{ roleLabel(row.reference_kind) }} · {{ row.completeness === 'FULL_TEXT' ? '当前可访问正文' : '部分文字资料' }}</p>
    <blockquote>{{ row.text }}</blockquote>
    <p v-if="row.duration_scope === 'DAY_SEGMENT'" class="warning">这是日段线索，不是整趟天数或实际耗时。</p>
    <p class="muted">以下为原来源适用条件，疑问和计划保持原意，不代表已核实结论：</p>
    <ul><li v-for="condition in row.conditions" :key="condition">{{ condition }}</li></ul>
    <p>来源：{{ row.source_title }} · 旅行时间：{{ row.travel_time || '未知' }}</p>
    <a v-if="row.source_url" :href="row.source_url" target="_blank" rel="noreferrer noopener">手动查看公开来源（外部页面）</a>
    <details class="lineage"><summary>查看引用定位与审核记录</summary>
      <p>审核：{{ row.review_status }}（开发 Work 辅助审核，非自动语义审核）</p>
      <p>证据 {{ row.claim_id }} · 来源 {{ row.source_id }}</p><p>{{ row.locator }}</p>
      <p v-for="span in row.span_ids" :key="span">{{ span }}</p>
      <p v-for="locator in row.block_locators" :key="locator">{{ locator }}</p>
    </details>
  </article>
</template>
