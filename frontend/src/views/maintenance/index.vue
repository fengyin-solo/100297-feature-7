<template>
  <section class="page" data-module="maintenance">
    <header class="page-head">
      <div>
        <h2>维保记录管理</h2>
        <p class="page-desc">维护维保记录，围绕维保编号、维保设备、维保单位、维保内容做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记维保记录</button>
        <button class="btn" type="button" @click="exportRows">导出维保记录清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section v-if="rescuePendingIds.length" class="rescue-banner">
      困人救援待处置 {{ rescuePendingIds.length }} 台（
      待到场 {{ stageCount('到场') }} ·
      待解困 {{ stageCount('解困') }} ·
      待复核 {{ stageCount('复核') }}），
      电梯编号：{{ rescuePendingIds.join('、') }}。请到「电梯管理 - 详情/救援」继续分段处置。
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无维保记录数据，可先登记维保记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条维保记录记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type PendingElevator = { id: number; 电梯编号: string; 当前段: string; 困人状态: string }
type RescueBoard = {
  待处置台数: number
  待处置电梯: PendingElevator[]
  分段台数: Record<string, number>
  资料待补台数: number
}

const ENDPOINT = '/api/maintenance'
const columns = ["维保编号", "维保设备", "维保单位", "维保内容", "维保日期", "维保人员", "更换部件", "维保状态"]
const actions = ["安排维保", "开始维保", "返工登记"]
const statuses = ["待维保", "维保中", "已完成", "需返工"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

// 维保看板：待处置台数直接取电梯困人救援看板，随到场/解困/复核推进实时变化。
const board = ref<RescueBoard>({
  待处置台数: 0,
  待处置电梯: [],
  分段台数: {},
  资料待补台数: 0,
})

const stats = computed(() => [
  { label: '待维保设备', value: rows.value.filter((row) => row.status === '待维保').length },
  { label: '维保中设备', value: rows.value.filter((row) => row.status === '维保中').length },
  { label: '困人救援待处置（台）', value: board.value.待处置台数 },
  { label: '电梯资料待补（台）', value: board.value.资料待补台数 },
])
const rescuePendingIds = computed(() => board.value.待处置电梯.map((item) => item.电梯编号))

function stageCount(stage: string): number {
  return board.value.分段台数[stage] ?? 0
}

async function loadRescueBoard() {
  try {
    const response = await request('/api/elevator/rescue/board')
    if (response.ok) {
      board.value = await response.json()
    }
  } catch {
    // 救援看板暂时读不出来不影响维保记录列表
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '维保记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '维保记录动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维保记录操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('维保记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadRescueBoard()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维保记录列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.rescue-banner {
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 12px;
}
</style>
