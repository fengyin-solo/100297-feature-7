<template>
  <section class="page" data-module="elevator">
    <header class="page-head">
      <div>
        <h2>电梯管理</h2>
        <p class="page-desc">
          困人救援按到场、解困、复核分段记录，哪段没填完都不能收口；
          列表与详情的困人状态来自同一口径。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记电梯</button>
        <button class="btn" type="button" @click="exportRows">导出电梯清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in summary" :key="item.key" class="stat-card">
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
        <span>运行状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="status in runningStatuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>电梯编号</th>
          <th>电梯类型</th>
          <th>额定载重</th>
          <th>层站数</th>
          <th>维保单位</th>
          <th>运行状态</th>
          <th>困人状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['电梯编号'] ?? '—' }}</td>
          <td>{{ row['电梯类型'] || '—' }}</td>
          <td>
            <span v-if="row['额定载重']">{{ row['额定载重'] }}</span>
            <span v-else class="error-text">未登记<span class="missing-tag">缺资料</span></span>
          </td>
          <td>{{ row['层站数'] || '—' }}</td>
          <td>
            <span v-if="row['维保单位']">{{ row['维保单位'] }}</span>
            <span v-else class="error-text">未登记<span class="missing-tag">缺资料</span></span>
          </td>
          <td><span class="badge" :class="runningBadgeClass(row['运行状态'])">{{ row['运行状态'] }}</span></td>
          <td>
            <!-- 没有困人记录显示「暂无」，不与「正常运行」混为一谈 -->
            <span v-if="row['困人状态'] === '暂无'" class="badge gray">暂无</span>
            <span v-else class="badge red">{{ row['困人状态'] }}</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openRescue(row)">
              {{ row['待处置'] ? `继续救援（${row['困人状态']}）` : '困人救援' }}
            </button>
            <button
              class="link"
              type="button"
              :disabled="row['待处置']"
              :title="row['待处置'] ? '有进行中的困人救援，请先完成救援' : ''"
              @click="runLedgerAction('安排维保', row)"
            >
              安排维保
            </button>
            <button
              class="link"
              type="button"
              :disabled="row['待处置']"
              :title="row['待处置'] ? '有进行中的困人救援，请先完成救援' : ''"
              @click="runLedgerAction('故障检修', row)"
            >
              故障检修
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="8" class="empty-state">暂无电梯管理数据，可先登记电梯</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条电梯记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <RescueDrawer
      v-if="rescueEntryId !== null"
      :entry-id="rescueEntryId"
      @close="rescueEntryId = null"
      @changed="onRescueChanged"
    />
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import RescueDrawer from './RescueDrawer.vue'

type ElevatorRow = {
  id: number
  电梯编号: string
  电梯类型: string
  额定载重: string
  层站数: string
  维保单位: string
  运行状态: string
  困人状态: string
  缺资料: string[]
  待处置: boolean
  [key: string]: unknown
}
type SummaryItem = { key: string; label: string; value: number }

const ENDPOINT = '/api/elevator'
const runningStatuses = ['正常运行', '维保中', '困人', '检修中']

const rows = ref<ElevatorRow[]>([])
const total = ref(0)
const summary = ref<SummaryItem[]>([])
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const rescueEntryId = ref<number | null>(null)

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

function openRescue(row: ElevatorRow) {
  rescueEntryId.value = row.id
}

async function onRescueChanged() {
  // 救援每保存一段就同步列表与看板卡，待处置台数跟着进度变
  await Promise.all([reload(), loadSummary()])
}

async function runLedgerAction(action: string, row: ElevatorRow) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json()) as { ok: boolean; message: string }
    if (!payload.ok) {
      // 业务失败要把后端的具体原因显示出来，而不是统一弹一句「操作失败」
      errorMessage.value = payload.message
      return
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作请求未送达，请稍后重试'
  }
}

function runningBadgeClass(status: string): string {
  if (status === '正常运行') return 'green'
  if (status === '困人') return 'red'
  if (status === '维保中') return 'amber'
  return 'blue'
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (response.ok) {
      const payload = (await response.json()) as { items: SummaryItem[] }
      summary.value = payload.items
    }
  } catch {
    // 统计卡读不出来不阻塞列表操作，保留上次数据
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  query.set('size', '100')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('电梯列表读取失败')
    }
    const payload = (await response.json()) as { items?: ElevatorRow[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '电梯列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
