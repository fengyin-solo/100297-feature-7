<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。电梯「待处理」即进行中、尚未复核收口的困人救援台数。</p>
      </div>
      <button class="btn" type="button" @click="load">刷新看板</button>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.label }}</td>
          <td>{{ row.created }}</td>
          <td>
            <span :class="row.pending > 0 ? 'badge red' : 'badge green'">{{ row.pending }}</span>
            <span v-if="row.name === 'elevator' && row.pending > 0" class="stage-hint">困人救援待处置</span>
          </td>
          <td>
            <span :class="row.abnormal > 0 ? 'badge amber' : 'badge gray'">{{ row.abnormal }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; label: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

async function load() {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{ label: '业务模块', value: 0 }, { label: '今日新增', value: 0 }]
    moduleRows.value = []
  }
}

onMounted(load)
</script>
