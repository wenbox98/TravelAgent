<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {PlanView} from '../planning-api'
import KnowledgeLibrary from './KnowledgeLibrary.vue'
const props=defineProps<{plan:PlanView;busy:boolean}>()
const emit=defineEmits<{action:[action:string,extra:Record<string,unknown>];refresh:[sid:string];newtrip:[]}>()
const opened=ref(!props.plan.draft.activities.length),choice=ref(''),selected=ref<string[]>([])
const chosen=computed(()=>props.plan.reuse_options?.find(o=>o.key===choice.value))
watch(choice,()=>{selected.value=chosen.value?.activities.map(a=>a.activity_id)||[]})
watch(()=>props.plan.session_id,()=>{choice.value='';selected.value=[];opened.value=!props.plan.draft.activities.length})
watch(()=>props.plan.draft.activities.length,n=>{opened.value=!n})
</script>
<template>
  <section v-if="plan.local_materials" id="local-materials" class="card local-materials">
    <div class="heading"><h2>先用已有资料</h2><button class="quiet" :disabled="busy" @click="opened=!opened">{{opened?'收起选材':'查看或修改选材'}}</button></div>
    <p>资料卡、历史组合或主动研究都从这里开始。本地浏览与选择不需要外部许可。</p>
    <p v-if="!opened">当前 {{plan.draft.activities.length}} 个项目；来源、条件与历史建议保留。需要时可展开修改。</p>
    <template v-if="opened">
      <p>{{plan.local_materials.message}}</p>
      <label class="check"><input type="checkbox" :checked="plan.local_materials.include_test" :disabled="busy" @change="emit('action','material_filter',{include_test:($event.target as HTMLInputElement).checked})" />包含开发测试资料（仅本次选材，不是长期偏好）</label>
      <KnowledgeLibrary :plan="plan" :busy="busy" :include-test="plan.local_materials.include_test" @refresh="emit('refresh',$event)" @newtrip="emit('newtrip')" />
      <h3>复用以前采用的活动或组合</h3>
      <p>只选当前目的地、同账号且来源仍有效的历史版本。停留标为历史建议；不复制旧偏好、预约、额度或采用状态。知识卡形成的安排请从资料库选择，仍需核对卡片版本。</p>
      <template v-if="plan.local_materials.can_select">
        <p v-if="!plan.reuse_options?.length">没有符合当前目的地、旅行类型与测试筛选的可用历史组合；未采用、来源变化或已撤销的材料不能复用。仍可选择资料卡，或需要时主动研究。</p>
        <template v-else>
          <label>选择历史活动组合<select v-model="choice"><option value="">请选择已有组合</option><option v-for="(o,i) in plan.reuse_options" :key="o.key" :value="o.key">组合 {{i+1}} · {{o.activities.map(a=>a.name).join(' → ')}} · {{o.test_input?'开发测试资料':'私人资料'}}</option></select></label>
          <label v-for="a in chosen?.activities" :key="a.activity_id" class="check"><input v-model="selected" type="checkbox" :value="a.activity_id" />{{a.name}} · {{a.timing_origin==='AI_PROPOSED'?'历史 AI 建议':'历史安排'}} · {{a.stay_min??'未定'}}–{{a.stay_max??'未定'}} 分钟 · {{a.spatial_status==='MATCH'?'原来源有范围依据，需适配本次需求':'范围待确认'}}</label>
          <button :disabled="busy||!selected.length" @click="emit('action','reuse_activities',{reuse_key:choice,activity_ids:selected})">预览所选历史活动</button>
        </template>
      </template>
      <p v-else>已有草稿不会被选材覆盖。下方可改变当前组合；更换资料类型请另建独立旅行，或取消尚未采用的本次选材。</p>
      <h3>本地资料不足时，主动查找新玩法</h3>
      <p>前往“查找新玩法”查看可用状态；需要本次旅行的有限操作许可，打开入口不会联网。</p>
      <a href="#find-play">查看查找新玩法入口</a>
    </template>
  </section>
</template>
<style scoped>.heading{display:flex;justify-content:space-between;align-items:center}.check{display:flex;gap:.5rem;align-items:center}.check input{width:auto}</style>
