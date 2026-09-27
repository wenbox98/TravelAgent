<script setup lang="ts">
import { ref, watch } from 'vue'
import { request } from '../api'
import { mapLabel, type MapView } from '../route-api'
import type { PlanView } from '../planning-api'
import PlaceChoices from './PlaceChoices.vue'
const props=defineProps<{plan:PlanView}>()
const emit=defineEmits<{refresh:[]}>()
const data=ref<MapView|null>(null),busy=ref(false),error=ref('')
let generation=0
async function load(){const t=++generation;try{const next=await request<MapView>('/api/v1/preview/planning-maps/'+props.plan.session_id);if(t===generation)data.value=next}catch{error.value='地点状态暂不可用，活动草稿保留。'}}
async function act(action:string,patch:Record<string,unknown>){if(!data.value||busy.value)return;busy.value=true;error.value='';const t=++generation;try{const next=await request<MapView>('/api/v1/preview/planning-maps',{action,session_id:props.plan.session_id,expected_revision:data.value.revision,expected_preview_revision:data.value.preview_revision,send_confirmed:true,...patch});if(t===generation){data.value=next;emit('refresh')}}catch(e){error.value=e instanceof Error?e.message:'未完成'}finally{busy.value=false}}
watch(()=>[props.plan.session_id,props.plan.revision],load,{immediate:true})
</script>
<template><details class="card"><summary>地点确认与相邻路段{{ plan.demo ? ' · 合成测试' : '' }}</summary><p>{{ data?.message }}</p><p v-if="error" role="alert">{{ error }}</p><template v-if="data"><PlaceChoices :places="data.places" :busy="busy" :can-query="data.configured && (!!plan.demo || (plan.private_budget?.remaining.map_place ?? 0) > 0)" :same-return="data.inputs.same_return" :synthetic="!!plan.demo" @action="act" /><h3>相邻路段</h3><p>查询模式是道路/公交/步行参考，不会替你改变交通意向。未决定则不派发。仅查询已采用顺序的相邻路段；地点/模式/日期变更使旧结果失效。</p><article v-for="leg in data.legs" :key="leg.leg_id"><h4>{{ leg.from_name }} → {{ leg.to_name }}</h4><p>{{ mapLabel(leg.kind) }} · {{ mapLabel(leg.mode) }} · {{ mapLabel(leg.status) }}</p><p v-if="leg.duration_seconds !== null">约 {{ Math.ceil(leg.duration_seconds/60) }} 分钟（{{ plan.demo ? '自编测试数据' : '高德临时估算，未保证班次与开放' }}）</p><p v-if="leg.mode === 'TRANSIT' && leg.status === 'OK'">接口方案总耗时只计算一次；班次、实际等候和入口接驳未逐项核实。</p><button class="quiet" :disabled="busy || !data.configured || (!plan.demo && ((plan.private_budget?.remaining.map_route ?? 0) <= 0 || !plan.adopted)) || data.inputs.mode === 'UNKNOWN' || leg.endpoint_confidence !== 'USER_CONFIRMED_MAP_OBJECTS'" @click="act('route',{leg_id:leg.leg_id})">{{ plan.demo ? '查看此段合成返回' : '查询此段移动参考' }}</button></article><p v-if="data.map_result_state === 'EXPIRED_OR_NOT_QUERIED'">地图临时结果未查询或已随进程过期。活动和选择保留，不会自动重新查询。</p></template></details></template>
