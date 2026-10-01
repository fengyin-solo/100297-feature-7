<template>
  <section class="page" data-module="elevator">
    <header class="page-head">
      <div>
        <h2>电梯管理</h2>
        <p class="page-desc">围绕电梯编号、额定载重、维保单位做登记筛选；困人救援按报警、到场、解困、复核分段记录，段段留痕、复核收口。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记电梯</button>
        <button class="btn" type="button" @click="exportRows">导出电梯清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>电梯编号</span>
        <input v-model="keyword" placeholder="按电梯编号检索" />
      </label>
      <label class="filter-item">
        <span>困人状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in rescueStatusOptions" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>资料完整度</th>
          <th>处置</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['电梯编号'] ?? '—' }}</td>
          <td>{{ row['电梯类型'] ?? '—' }}</td>
          <td>{{ row['额定载重'] || '未填' }}</td>
          <td>{{ row['层站数'] ?? '—' }}</td>
          <td>{{ row['维保单位'] || '未填' }}</td>
          <td>{{ row['上次维保'] ?? '—' }}</td>
          <td>{{ row['下次维保日'] ?? '—' }}</td>
          <td>
            <!-- 困人状态只有一个口径：后端按进行中的救援记录派生，列表与详情共用 -->
            <span class="tag" :class="rescueTagClass(row)">{{ row['困人状态'] ?? '暂无' }}</span>
          </td>
          <td>
            <span v-if="missingFields(row).length" class="tag tag-warn">
              资料待补：{{ missingFields(row).join('、') }}
            </span>
            <span v-else class="tag tag-ok">资料齐全</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情/救援</button>
            <button
              v-if="!row['困人中']"
              class="link"
              type="button"
              @click="runAction('安排维保', row)"
            >
              安排维保
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无电梯数据，可先登记电梯</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条电梯记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>

    <RescueModal
      v-if="modalEntryId !== null"
      :entry-id="modalEntryId"
      @close="closeModal"
      @saved="handleSaved"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import RescueModal from './RescueModal.vue'

type Row = Record<string, string | number | boolean | null | string[]>

const ENDPOINT = '/api/elevator'
const columns = ['电梯编号', '电梯类型', '额定载重', '层站数', '维保单位', '上次维保', '下次维保日', '困人状态']
const rescueStatusOptions = ['暂无', '已报警·待到场', '救援中·已到场', '已解困·待复核']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const modalEntryId = ref<number | null>(null)
const board = ref<{ 待处置台数: number; 资料待补台数: number; 分段台数: Record<string, number> }>({
  待处置台数: 0,
  资料待补台数: 0,
  分段台数: {},
})

const stats = computed(() => [
  { label: '困人救援待处置（台）', value: board.value.待处置台数 },
  { label: '待到场（台）', value: board.value.分段台数['到场'] ?? 0 },
  { label: '待解困（台）', value: board.value.分段台数['解困'] ?? 0 },
  { label: '待复核收口（台）', value: board.value.分段台数['复核'] ?? 0 },
  { label: '资料待补（台）', value: board.value.资料待补台数 },
])

function missingFields(row: Row): string[] {
  const value = row['待补资料']
  return Array.isArray(value) ? (value as string[]) : []
}

function rescueTagClass(row: Row): string {
  switch (row['困人状态']) {
    case '已报警·待到场':
      return 'tag-danger'
    case '救援中·已到场':
      return 'tag-warn'
    case '已解困·待复核':
      return 'tag-info'
    default:
      return 'tag-muted'
  }
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '电梯登记入口尚未接入审批流'
}

function openDetail(row: Row) {
  modalEntryId.value = Number(row.id)
}

function closeModal() {
  modalEntryId.value = null
}

async function handleSaved(message: string) {
  successMessage.value = message
  await Promise.all([reload(), loadBoard()])
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '电梯动作未生效，请稍后重试')
    }
    successMessage.value = payload.message
    await Promise.all([reload(), loadBoard()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电梯操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value) params.set('keyword', keyword.value)
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('电梯列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电梯列表读取失败'
  }
}

async function loadBoard() {
  try {
    const response = await request(`${ENDPOINT}/rescue/board`)
    if (response.ok) {
      board.value = await response.json()
    }
  } catch {
    // 看板读不出来不阻塞列表，保留上一次的数字
  }
}

onMounted(() => {
  void reload()
  void loadBoard()
})
</script>
