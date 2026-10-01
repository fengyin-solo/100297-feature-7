<template>
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>困人救援 · {{ entry?.['电梯编号'] ?? `电梯 ${entryId}` }}</h3>
        <button class="modal-close" type="button" @click="$emit('close')">×</button>
      </div>

      <p v-if="loadError" class="error-text">{{ loadError }}</p>

      <template v-else-if="entry">
        <section class="stage-panel" style="background: #fff">
          <div class="stage-readonly">
            <div><span class="k">电梯类型</span>{{ entry['电梯类型'] || '未填' }}</div>
            <div><span class="k">额定载重</span>{{ entry['额定载重'] || '未填' }}</div>
            <div><span class="k">维保单位</span>{{ entry['维保单位'] || '未填' }}</div>
            <div>
              <span class="k">当前困人状态</span>
              <span class="tag" :class="rescueTagClass">{{ entry['困人状态'] }}</span>
            </div>
          </div>
          <p v-if="missingFields.length" class="error-text" style="margin-bottom: 0">
            资料待补：{{ missingFields.join('、') }}，请同步联系使用单位补齐。
          </p>
        </section>

        <!-- 没有进行中的救援：给出立案入口；困人状态此时是「暂无」而不是「正常」 -->
        <section v-if="!rescue" class="stage-panel">
          <h4>当前没有进行中的困人救援记录</h4>
          <p class="page-desc">立案后系统自动记录报警时间，处置人依次填写到场、解困、复核三段；任何一段没填完都不能收口。</p>
          <button class="btn primary" type="button" :disabled="saving" @click="startRescue">困情立案（自动记录报警）</button>
        </section>

        <template v-else>
          <!-- 段进度条：已完成段 / 当前段一目了然 -->
          <div class="stage-track">
            <div
              v-for="(stage, idx) in stages"
              :key="stage"
              class="stage-node"
              :class="stageNodeClass(stage, idx)"
            >
              {{ idx + 1 }}.{{ stage }}
            </div>
          </div>

          <!-- 已封存段只读展示，断点回来也看得到之前填了什么 -->
          <section v-for="stage in doneStages" :key="`done-${stage}`" class="stage-panel">
            <h4>{{ stage }}段 <span class="tag tag-ok">已完成</span></h4>
            <div class="stage-readonly">
              <div v-for="field in stageFields(stage)" :key="field">
                <span class="k">{{ field }}</span>{{ stageValue(stage, field) || '—' }}
              </div>
            </div>
          </section>

          <!-- 当前段：边填边存，提交缺项只暂存不收口 -->
          <section class="stage-panel">
            <h4>
              {{ currentStage }}段 <span class="tag tag-danger">处置中</span>
              <span class="page-desc">必填：{{ requiredFields.join('、') }}；未补齐前只能暂存，不会推进到下一段。</span>
            </h4>
            <div class="form-grid">
              <label v-for="field in requiredFields" :key="field">
                <span>{{ field }}<em v-if="field !== '复核结论'"> *</em></span>
                <textarea
                  v-if="field === '复核结论'"
                  v-model="form[field]"
                  :placeholder="`请填写${field}`"
                ></textarea>
                <input
                  v-else
                  v-model="form[field]"
                  :placeholder="`请填写${field}`"
                  @blur="draftSave"
                />
              </label>
            </div>
          </section>

          <p v-if="actionError" class="error-text">{{ actionError }}</p>

          <footer class="modal-foot">
            <span class="modal-tip">每段保存即时生效，断线或关闭页面后重新打开可从本段继续。</span>
            <button class="btn" type="button" :disabled="saving" @click="draftSave">暂存本段</button>
            <button class="btn primary" type="button" :disabled="saving" @click="submitStage">
              {{ currentStage === '复核' ? '完成复核并收口' : `保存${currentStage}段并继续` }}
            </button>
          </footer>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type StageState = {
  fields: Record<string, string>
  required: string[]
  missing: string[]
  completed: boolean
}
type Rescue = {
  stage: string
  started_at: string
  finished_at: string
  stages: Record<string, StageState>
  阶段顺序: string[]
}
type Entry = {
  id: number
  '困人状态': string
  '电梯编号'?: string
  '电梯类型'?: string
  '额定载重'?: string
  '维保单位'?: string
  '困人中'?: boolean
  '待补资料'?: string[]
  active_rescue?: Rescue
}

const props = defineProps<{ entryId: number }>()
const emit = defineEmits<{
  close: []
  saved: [message: string]
}>()

const ENDPOINT = '/api/elevator'
const stages = ['报警', '到场', '解困', '复核']

const entry = ref<Entry | null>(null)
const loadError = ref('')
const actionError = ref('')
const saving = ref(false)
const form = reactive<Record<string, string>>({})

const rescue = computed(() => entry.value?.active_rescue ?? null)
const currentStage = computed(() => rescue.value?.stage ?? '到场')
const requiredFields = computed(() => rescue.value?.stages[currentStage.value]?.required ?? [])
const missingFields = computed(() => entry.value?.['待补资料'] ?? [])

const doneStages = computed(() => {
  if (!rescue.value) return []
  const currentIndex = stages.indexOf(rescue.value.stage)
  return stages.slice(0, currentIndex)
})

const rescueTagClass = computed(() => {
  switch (entry.value?.['困人状态']) {
    case '已报警·待到场':
      return 'tag-danger'
    case '救援中·已到场':
      return 'tag-warn'
    case '已解困·待复核':
      return 'tag-info'
    default:
      return 'tag-muted'
  }
})

function stageFields(stage: string): string[] {
  return rescue.value?.stages[stage]?.required ?? []
}

function stageValue(stage: string, field: string): string {
  return rescue.value?.stages[stage]?.fields?.[field] ?? ''
}

function stageNodeClass(stage: string, index: number): string {
  if (!rescue.value) return ''
  const currentIndex = stages.indexOf(rescue.value.stage)
  if (index < currentIndex) return 'done'
  if (index === currentIndex) return 'current'
  return ''
}

function syncForm() {
  Object.keys(form).forEach((key) => delete form[key])
  if (!rescue.value) return
  const fields = rescue.value.stages[rescue.value.stage]?.fields ?? {}
  Object.entries(fields).forEach(([key, value]) => {
    form[key] = value
  })
}

async function loadEntry() {
  loadError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${props.entryId}`)
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string } | null
      throw new Error(payload?.detail ?? '电梯明细读取失败')
    }
    entry.value = await response.json()
    syncForm()
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '电梯明细读取失败'
  }
}

async function startRescue() {
  actionError.value = ''
  saving.value = true
  try {
    const response = await request(`${ENDPOINT}/${props.entryId}/rescue/start`, {
      method: 'POST',
      body: JSON.stringify({ values: {} }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!payload.ok) throw new Error(payload.message)
    await loadEntry()
    emit('saved', payload.message)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '困情立案失败'
  } finally {
    saving.value = false
  }
}

// 暂存与提交走同一个分段接口：后端按必填项是否齐全决定只暂存还是推进。
async function postStage(): Promise<string> {
  const response = await request(
    `${ENDPOINT}/${props.entryId}/rescue/stages/${encodeURIComponent(currentStage.value)}`,
    {
      method: 'POST',
      body: JSON.stringify({ values: { ...form } }),
    },
  )
  const payload = (await response.json()) as { ok: boolean; message: string }
  if (!payload.ok) throw new Error(payload.message)
  return payload.message
}

async function draftSave() {
  if (!rescue.value || saving.value) return
  actionError.value = ''
  saving.value = true
  try {
    const message = await postStage()
    await loadEntry()
    emit('saved', message)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '暂存失败'
  } finally {
    saving.value = false
  }
}

async function submitStage() {
  if (!rescue.value) return
  actionError.value = ''
  const blank = requiredFields.value.filter((field) => !form[field]?.trim())
  if (blank.length) {
    // 缺项也先保住已填内容，再明确告诉处置人还差什么。
    await draftSave()
    actionError.value = `「${currentStage.value}」段尚未填完，缺少：${blank.join('、')}，不能进入下一段`
    return
  }
  saving.value = true
  try {
    const message = await postStage()
    await loadEntry()
    emit('saved', message)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : '分段保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(loadEntry)
</script>
