<script setup lang="ts">
import { ref } from 'vue'
const health = ref('尚未检查')
async function checkHealth() {
  try {
    const response = await fetch('/health')
    const body = await response.json()
    health.value = response.ok && body.status === 'ok' ? '本地服务运行正常' : '本地服务暂不可用'
  } catch { health.value = '无法连接本地服务' }
}
</script>
<template>
  <main>
    <header><span class="brand">TravelAgent</span><strong class="badge">合成演示 · 离线</strong></header>
    <section class="intro"><p class="eyebrow">旅行规划助手 / 工程预览</p><h1>旅行，从一个想法开始。</h1><p>离线骨架已就绪。后续将从大致路线开始，逐步确认天数、交通和预算。</p></section>
    <section class="card"><h2>当前可用</h2><p>本页面用于检查本地服务。尚未生成真实攻略，也未进行小红书研究。</p><button @click="checkHealth">检查本地服务</button><p role="status">{{ health }}</p></section>
    <section class="grid" aria-label="服务状态"><article v-for="item in [['小红书', '真实访问已关闭'], ['模型', '未配置'], ['高德地图', '未配置'], ['交通与住宿报价', '暂不支持 · 价格未知']]" :key="item[0]"><h2>{{ item[0] }}</h2><p>{{ item[1] }}</p></article></section>
    <footer>合成演示不代表真实登录、研究或发行验收通过。</footer>
  </main>
</template>
