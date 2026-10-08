<script setup lang="ts">
import {ref,watch} from 'vue'
import {readIdea,storeIdea,submitShortcut} from '../intake'
const props=defineProps<{busy:boolean;ready:boolean;reason?:string}>()
const emit=defineEmits<{start:[idea:string,destination:string,kind:string];local:[idea:string,destination:string,kind:string]}>()
const idea=ref(readIdea()),destination=ref(''),kind=ref('CITY')
watch(idea,storeIdea,{flush:'sync'})
function start(){if(props.ready&&!props.busy&&idea.value.trim())emit('start',idea.value,destination.value,kind.value)}
function keyboard(e:KeyboardEvent){if(submitShortcut(e)){e.preventDefault();start()}}
</script>
<template>
  <form class="card trip-intake" @submit.prevent="start">
    <label for="trip-idea">你想去哪里，怎么玩？</label>
    <textarea id="trip-idea" v-model="idea" maxlength="500" rows="3" placeholder="例如：我想去东北玩7天，想轻松一点" @keydown="keyboard" />
    <p class="muted">先写一句想法即可。天数、交通、预算和人数可暂未定。Ctrl / ⌘ + Enter 提交。</p>
    <details><summary>补充或修正目的区域（可选）</summary><label>目的城市或区域<input v-model="destination" maxlength="80" placeholder="只在识别不清楚时填写" /></label><label>旅行类型<select v-model="kind"><option value="CITY">先从同一目的区域比较</option><option value="REGIONAL">跨地区旅行</option></select></label></details>
    <p>点击下方按钮即启动本次有限任务：先用适用缓存，不足时查小红书、阅读少量公开笔记，并将过滤后的必要文字交给已配置的 DeepSeek 生成建议。每来源最多6000字，不发送凭据、私址或地图返回。</p>
    <button type="submit" :disabled="busy||!ready||!idea.trim()" aria-describedby="intake-reason">{{busy?'正在启动本次任务…':'查资料并生成旅行建议'}}</button>
    <p id="intake-reason" role="status">{{!ready?reason:!idea.trim()?'写下旅行想法后，即可开始。':'无需先填写人数、预算或日期；只有采用时才覆盖你的版本。'}}</p>
    <details><summary>高级：执行范围与本地模式</summary><p>默认最多连接1次、搜索1次、正文2篇、模型5次，一小时内有效；有合格材料就提前停止，不自动重试。适用缓存已足够时只用1次模型，不访问小红书。次数上限不是费用承诺。</p><button type="button" :disabled="busy||!ready||!idea.trim()" @click="emit('local',idea,destination,kind)">只建立本地旅行</button></details>
    <p class="muted">尚未提交的想法仅保留在当前浏览器本机，恢复连接后可以继续。</p>
  </form>
</template>
<style scoped>button[type=submit]{margin-top:1rem;min-width:10rem}@media(max-width:650px){button[type=submit]{width:100%}}</style>
