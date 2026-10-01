<template>
  <teleport to="body">
    <div class="drawer-mask" @click="close" />
    <aside class="drawer" role="dialog" aria-label="困人救援记录">
      <header class="drawer-head">
        <h3>
          困人救援 · {{ detail?.电梯编号 ?? '加载中' }}
          <span v-if="detail" class="badge" :class="rescueBadgeClass(detail['困人状态'])">
            {{ detail['困人状态'] }}
          </span>
        </h3>
        <button class="btn ghost" type="button" @click="close">关闭</button>
      </header>

      <div class="drawer-body">
        <p v-if="loading" class="page-desc">正在读取救援记录…</p>
        <template v-else-if="detail">
          <dl class="info-grid">
            <div><dt>电梯类型</dt><dd>{{ detail['电梯类型'] || '—' }}</dd></div>
            <div><dt>运行状态</dt><dd><span class="badge" :class="runningBadgeClass(detail['运行状态'])">{{ detail['运行状态'] }}</span></dd></div>
            <div>
              <dt>额定载重</dt>
              <dd>
                {{ detail['额定载重'] || '—' }}
                <span v-if="(detail['缺资料'] || []).includes('额定载重')" class="missing-tag" title="额定载重未登记，请尽快补全">缺资料</span>
              </dd>
            </div>
            <div>
              <dt>维保单位</dt>
              <dd>
                {{ detail['维保单位'] || '—' }}
                <span v-if="(detail['缺资料'] || []).includes('维保单位')" class="missing-tag" title="维保单位未登记，请尽快补全">缺资料</span>
              </dd>
            </div>
          </dl>

          <p v-if="message" :class="succeeded ? 'success-text' : 'error-text'" style="font-size:13px">{{ message }}</p>

          <!-- 没有进行中的救援：先建单，不许凭空填段落 -->
          <div v-if="!active" class="stage">
            <p class="page-desc">
              当前没有进行中的困人救援。确认该电梯发生困人后先建单，
              再按「到场 → 解困 → 复核」分段记录；任何一段没填完都不能收口。
            </p>
            <button class="btn primary" type="button" :disabled="busy" @click="startRescue">发起困人救援</button>
          </div>

          <!-- 进行中的救援：三段顺序记录 -->
          <template v-else>
            <p class="page-desc">
              救援单号 #{{ active.id }}，建单时间 {{ active.started_at }}。
              每段保存后立即落库，中途断线或关闭页面，已填段落不会丢失，重新打开即可接着填。
            </p>
            <section
              v-for="item in stageDefs"
              :key="item.stage"
              class="stage"
              :class="stageClass(item.stage)"
            >
              <div class="stage-title">
                <span>{{ stageIndex[item.stage] }}. {{ item.stage }}</span>
                <span class="stage-hint">{{ stageHint(item.stage) }}</span>
              </div>

              <!-- 已填段落：回显落库内容，不允许再改 -->
              <ul v-if="savedStages[item.stage]" class="stage-values">
                <li v-for="field in item.fields" :key="field.key">
                  <span class="k">{{ field.label }}</span>
                  <span>{{ savedStages[item.stage][field.key] || '—' }}</span>
                </li>
                <li><span class="k">落库时间</span><span>{{ savedStages[item.stage].saved_at }}</span></li>
              </ul>

              <!-- 当前该填的段落：表单内容先存本地草稿，网络断了也不白填 -->
              <form v-else-if="active.next_stage === item.stage" class="field-grid" @submit.prevent="saveStage(item.stage)">
                <label v-for="field in item.fields" :key="field.key" :class="{ full: field.full }">
                  {{ field.label }}
                  <textarea
                    v-if="field.textarea"
                    v-model="draft[field.key]"
                    :placeholder="`请填写${field.label}`"
                  />
                  <input
                    v-else
                    v-model="draft[field.key]"
                    :type="field.type || 'text'"
                    :placeholder="`请填写${field.label}`"
                  />
                </label>
                <div class="full" style="grid-column:1/-1;display:flex;gap:8px;align-items:center">
                  <button class="btn primary" type="submit" :disabled="busy">保存本段</button>
                  <span class="stage-hint">本段全部填齐才能保存，保存后才能进入下一段</span>
                </div>
              </form>

              <p v-else class="stage-hint">需先完成上一段记录</p>
            </section>
          </template>

          <!-- 历史救援：已完成的记录仍可追溯 -->
          <div v-if="history.length" class="history-block">
            <h4 style="margin:0 0 6px;font-size:13px">历史困人记录（{{ history.length }}）</h4>
            <ul class="stage-values" v-for="rescue in history" :key="rescue.id">
              <li><span class="k">单号 #{{ rescue.id }}</span><span>{{ rescue.started_at }} 建单 · {{ rescue.completed_at }} 收口</span></li>
            </ul>
          </div>
        </template>
      </div>

      <footer v-if="detail" class="drawer-foot">
        <span class="stage-hint">
          {{ active
            ? (active.next_stage ? `下一段：${active.next_stage}；三段齐全后才可复核收口` : '三段已填齐，请尽快复核收口')
            : '无进行中的救援' }}
        </span>
        <button
          v-if="active"
          class="btn primary"
          type="button"
          :disabled="busy || active.next_stage !== null"
          :title="active.next_stage ? `还有「${active.next_stage}」段落未完成` : ''"
          @click="completeRescue"
        >
          复核收口
        </button>
      </footer>
    </aside>
  </teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'

type FieldDef = { key: string; label: string; full?: boolean; textarea?: boolean; type?: string }
type StageDef = { stage: string; fields: FieldDef[] }
type SavedStage = Record<string, string>
type Rescue = {
  id: number
  started_at: string
  completed_at: string | null
  stages: Record<string, SavedStage>
  rescue_status: string
  next_stage: string | null
}
type ElevatorDetail = {
  id: number
  电梯编号: string
  电梯类型: string
  额定载重: string
  维保单位: string
  运行状态: string
  困人状态: string
  缺资料: string[]
  rescues: Rescue[]
  active_rescue: Rescue | null
  [key: string]: unknown
}

const props = defineProps<{ entryId: number }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const stageDefs: StageDef[] = [
  {
    stage: '到场',
    fields: [
      { key: 'arrived_at', label: '到场时间', type: 'datetime-local' },
      { key: 'rescuers', label: '到场救援人员', full: true },
    ],
  },
  {
    stage: '解困',
    fields: [
      { key: 'released_at', label: '解困时间', type: 'datetime-local' },
      { key: 'trapped_count', label: '被困人数' },
      { key: 'resolution', label: '现场处置情况', full: true, textarea: true },
    ],
  },
  {
    stage: '复核',
    fields: [
      { key: 'reviewed_at', label: '复核时间', type: 'datetime-local' },
      { key: 'reviewer', label: '复核人' },
      { key: 'review_note', label: '复核意见', full: true, textarea: true },
    ],
  },
]
const stageIndex: Record<string, string> = { 到场: '一', 解困: '二', 复核: '三' }

const detail = ref<ElevatorDetail | null>(null)
const loading = ref(true)
const busy = ref(false)
const succeeded = ref(false)
const message = ref('')
const draft = reactive<Record<string, string>>({})

const active = computed<Rescue | null>(() => detail.value?.active_rescue ?? null)
const savedStages = computed(() => active.value?.stages ?? {})
const history = computed(() => (detail.value?.rescues ?? []).filter((item) => item.completed_at))

const draftKey = computed(() =>
  active.value ? `elevator-rescue-draft-${props.entryId}-${active.value.id}-${active.value.next_stage ?? ''}` : '',
)

function restoreDraft() {
  Object.keys(draft).forEach((key) => delete draft[key])
  if (!draftKey.value) return
  try {
    const saved = JSON.parse(localStorage.getItem(draftKey.value) || '{}') as Record<string, string>
    Object.assign(draft, saved)
  } catch {
    // 草稿损坏不影响正式记录，忽略即可
  }
}

watch(draft, (value) => {
  if (!draftKey.value) return
  localStorage.setItem(draftKey.value, JSON.stringify(value))
}, { deep: true })

watch(active, () => {
  message.value = ''
  restoreDraft()
})

async function refresh() {
  loading.value = true
  try {
    const response = await request(`/api/elevator/${props.entryId}`)
    if (!response.ok) throw new Error(`接口返回 ${response.status}`)
    detail.value = (await response.json()) as ElevatorDetail
  } catch (error) {
    message.value = error instanceof Error ? error.message : '电梯详情读取失败'
  } finally {
    loading.value = false
  }
}

async function callAction(url: string, init?: RequestInit): Promise<{ ok: boolean; message: string }> {
  busy.value = true
  succeeded.value = false
  try {
    const response = await request(url, init)
    const payload = (await response.json()) as { ok: boolean; message: string; entry?: ElevatorDetail }
    if (payload.entry) detail.value = payload.entry
    succeeded.value = payload.ok
    message.value = payload.message
    if (payload.ok) {
      emit('changed')
    }
    return { ok: payload.ok, message: payload.message }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '请求未送达，请检查网络后重试'
    return { ok: false, message: message.value }
  } finally {
    busy.value = false
  }
}

async function startRescue() {
  await callAction(`/api/elevator/${props.entryId}/rescue`, { method: 'POST' })
  await refresh()
}

function missingLabels(stage: string): string[] {
  const def = stageDefs.find((item) => item.stage === stage)
  if (!def) return []
  return def.fields.filter((field) => !String(draft[field.key] ?? '').trim()).map((field) => field.label)
}

async function saveStage(stage: string) {
  const missing = missingLabels(stage)
  if (missing.length) {
    succeeded.value = false
    message.value = `「${stage}」段落未填完：${missing.join('、')}，已填写的内容保留在表单里`
    return
  }
  const values: Record<string, string | number> = { ...draft }
  if (active.value) values.rescue_id = active.value.id
  // 先记下当前草稿键，落库成功后清掉，避免换段后旧键成为读不到的孤儿草稿
  const keyBefore = draftKey.value
  const result = await callAction(`/api/elevator/${props.entryId}/rescue/stages/${encodeURIComponent(stage)}`, {
    method: 'PUT',
    body: JSON.stringify({ values }),
  })
  if (result.ok) {
    if (keyBefore) localStorage.removeItem(keyBefore)
    Object.keys(draft).forEach((fieldKey) => delete draft[fieldKey])
    await refresh()
  }
}

async function completeRescue() {
  await callAction(`/api/elevator/${props.entryId}/rescue/complete`, {
    method: 'POST',
    body: JSON.stringify({ values: { rescue_id: active.value?.id } }),
  })
  await refresh()
}

function close() {
  emit('close')
}

function stageClass(stage: string): string {
  if (!active.value) return 'todo'
  if (savedStages.value[stage]) return 'done'
  if (active.value.next_stage === stage) return 'active'
  return 'todo'
}

function stageHint(stage: string): string {
  if (!active.value) return ''
  if (savedStages.value[stage]) return '已记录'
  if (active.value.next_stage === stage) return '待填写'
  return '未开始'
}

function rescueBadgeClass(status: string): string {
  if (status === '暂无') return 'gray'
  if (status === '已完成') return 'green'
  return 'red'
}

function runningBadgeClass(status: string): string {
  if (status === '正常运行') return 'green'
  if (status === '困人') return 'red'
  if (status === '维保中') return 'amber'
  return 'blue'
}

onMounted(refresh)
</script>
