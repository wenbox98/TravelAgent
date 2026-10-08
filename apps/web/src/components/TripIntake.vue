<script setup lang="ts">
import {ref,watch} from 'vue'
import {readIdea,storeIdea,submitShortcut} from '../intake'
const props=defineProps<{busy:boolean;ready:boolean;reason?:string}>()
const emit=defineEmits<{start:[idea:string,destination:string,kind:string]}>()
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
    <button type="submit" :disabled="busy||!ready||!idea.trim()" aria-describedby="intake-reason">{{busy?'正在准备本地草稿…':'开始规划'}}</button>
    <p id="intake-reason" role="status">{{!ready?reason:!idea.trim()?'写下旅行想法后，即可开始。':'先读取适用的本机资料；不会自动联网。'}}</p>
    <p class="muted">尚未提交的想法仅保留在当前浏览器本机，恢复连接后可以继续。</p>
  </form>
</template>
<style scoped>button[type=submit]{margin-top:1rem;min-width:10rem}@media(max-width:650px){button[type=submit]{width:100%}}</style>
