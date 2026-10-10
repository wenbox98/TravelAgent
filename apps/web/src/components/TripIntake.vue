<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {readIdea,storeIdea,submitShortcut} from '../intake'
const props=defineProps<{busy:boolean;ready:boolean;reason?:string;submitting?:boolean;feedback?:string;failure?:string;unconfirmed?:boolean;resumable?:boolean}>()
const emit=defineEmits<{start:[idea:string,destination:string,kind:string,mapConsent:boolean];local:[idea:string,destination:string,kind:string];recover:[];resume:[]}>()
const idea=ref(readIdea()),destination=ref(''),kind=ref('CITY'),mapConsent=ref(false)
const attempted=ref(''),composing=ref(false)
const blocked=computed(()=>!props.ready?(props.reason||'请先连接本机工作台。'):props.submitting?'正在提交，请稍候；不要重复发送。':props.busy?'正在处理上一项操作，完成后再提交。':props.unconfirmed?'上次提交结果尚未确认，请先读取已保存状态。':!idea.value.trim()?'请先写下旅行想法。':'')
const buttonLabel=computed(()=>!props.ready?'连接后才能提交':props.submitting?'正在提交…':props.busy?'正在处理…':props.unconfirmed?'提交结果待确认':'查资料并生成旅行建议')
watch(idea,storeIdea,{flush:'sync'})
watch(()=>[props.ready,props.busy,props.unconfirmed,idea.value],()=>attempted.value='')
function start(local=false){if(blocked.value){attempted.value='未提交：'+blocked.value;return}attempted.value='';if(local)emit('local',idea.value,destination.value,kind.value);else emit('start',idea.value,destination.value,kind.value,mapConsent.value)}
function keyboard(e:KeyboardEvent){if(!composing.value&&submitShortcut(e)){e.preventDefault();start()}}
</script>
<template>
  <form class="card trip-intake" @submit.prevent="start()" :aria-busy="submitting||false">
    <label for="trip-idea">你想去哪里，怎么玩？</label>
    <textarea id="trip-idea" v-model="idea" maxlength="500" rows="3" placeholder="例如：我想去东北玩7天，想轻松一点" aria-describedby="intake-hint intake-reason" @keydown="keyboard" @compositionstart="composing=true" @compositionend="composing=false" />
    <p id="intake-hint" class="muted">先写一句想法即可。天数、交通、预算和人数可暂未定。{{!blocked?'Ctrl / ⌘ + Enter 提交。':'当前暂不能提交；原因和下一步见下方。'}}</p>
    <p v-if="failure" class="warning" role="alert">{{failure}}</p>
    <div v-if="failure||unconfirmed"><button type="button" class="quiet" :disabled="busy||!ready" @click="emit('recover')">读取已保存状态</button><button v-if="resumable" type="button" :disabled="busy||!ready" @click="emit('resume')">继续确认原提交</button></div>
    <p v-if="feedback" role="status" aria-live="polite">{{feedback}}</p>
    <details><summary>补充或修正目的区域（可选）</summary><label>目的城市或区域<input v-model="destination" maxlength="80" placeholder="只在识别不清楚时填写" /></label><label>旅行类型<select v-model="kind"><option value="CITY">先从同一目的区域比较</option><option value="REGIONAL">跨地区旅行</option></select></label></details>
    <p>点击下方按钮即启动本次有限任务：先让模型理解本条原话，再复核缓存、按缺口决定研究或生成建议。必要时正常登录小红书并阅读少量公开笔记；每轮真实结果会进入下一次决策。每来源最多6000字，不发送凭据、私址或地图返回。</p>
    <label><input type="checkbox" v-model="mapConsent" />允许为本次一段关键公共衔接查询高德（最多2个地点和1段路径；不发送私址，地点候选仍需确认；可不选）</label>
    <button type="submit" :disabled="Boolean(blocked)" aria-describedby="intake-reason">{{buttonLabel}}</button>
    <p id="intake-reason" role="status" aria-live="polite">{{attempted||blocked||'无需先填写人数、预算或日期；只有采用时才覆盖你的版本。'}}</p>
    <details><summary>高级：执行范围与本地模式</summary><p>本次最多连接1次、搜索5次、读取20篇正文；模型调用次数不限，逐次记账，四小时内有效。会结合实际缺口开展正面玩法与侧面交通、住宿研究，同一搜索列表可择读多篇。适用缓存优先，问题或假设不查新资料。每来源每次最多6000字发给既定DeepSeek，不发送凭据、私址或地图返回。取消、无进展、明确服务故障或登录验证会停止；失败不自动重试，旧许可与用量不变。次数不是费用承诺。</p><button type="button" :disabled="Boolean(blocked)" @click="start(true)">只建立本地旅行</button></details>
    <p class="muted">尚未提交的想法仅保留在当前浏览器本机，恢复连接后可以继续。</p>
  </form>
</template>
<style scoped>button[type=submit]{margin-top:1rem;min-width:10rem}@media(max-width:650px){button[type=submit]{width:100%}}</style>
