<template>
  <!-- 注意：此处不能包裸 <template>（无指令）——Vue 3 会渲染为原生 template 元素，
       其 UA 样式 display:none 会让整页内容不参与布局（曾导致"统计看板打不开"） -->
  <div class="stats-page">
      <div class="toolbar">
        <span class="hint">数据窗口</span>
        <el-select v-model="days" size="small" style="width: 110px" @change="loadAssist">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="30" label="近 30 天" />
          <el-option :value="90" label="近 90 天" />
        </el-select>
        <div class="spacer"></div>
        <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
      </div>

      <!-- 指标卡 -->
      <div class="metric-row" v-loading="loading">
        <div class="metric">
          <div class="num">{{ kb.laws.toLocaleString() }}</div>
          <div class="label">法条总条数</div>
        </div>
        <div class="metric">
          <div class="num">{{ kb.synced.toLocaleString() }}</div>
          <div class="label">已入向量库</div>
        </div>
        <div class="metric">
          <div class="num">{{ assist.sessions }}</div>
          <div class="label">全局AI会话数</div>
        </div>
        <div class="metric">
          <div class="num">{{ assist.questions }}</div>
          <div class="label">全局提问次数</div>
        </div>
        <div class="metric">
          <div class="num">{{ pct(assist.adoption_rate) }}</div>
          <div class="label">采纳率</div>
        </div>
        <div class="metric">
          <div class="num">{{ pct(assist.no_evidence_rate) }}</div>
          <div class="label">无依据率</div>
        </div>
      </div>

      <!-- 图表区 -->
      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title">法条引用 Top10 <span class="sub">（AI 回答中被引用最多的法条）</span></div>
          <div v-if="assist.top_cited_laws.length" ref="citeRef" class="chart"></div>
          <el-empty v-else description="窗口内暂无引用记录" :image-size="70" />
        </div>
        <div class="chart-card">
          <div class="chart-title">提问趋势 <span class="sub">（{{ days }} 天内按天）</span></div>
          <div v-if="assist.daily.length" ref="trendRef" class="chart"></div>
          <el-empty v-else description="窗口内暂无提问" :image-size="70" />
        </div>
        <div class="chart-card">
          <div class="chart-title">法律部门分布 <span class="sub">（共 {{ kb.laws.toLocaleString() }} 条）</span></div>
          <div ref="deptRef" class="chart"></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">向量库覆盖率 <span class="sub">（已灌 / 全部）</span></div>
          <div ref="syncRef" class="chart"></div>
        </div>
      </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, PieChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchKbStats, fetchAssistStats } from '../api/stats.js'

echarts.use([BarChart, PieChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer])

// 统计看板对所有登录用户开放（运营数据，受理员/复核员同样可查）
const days = ref(30)
const loading = ref(false)
const kb = ref({ laws: 0, cases: 0, synced: 0, pending: 0, skipped: 0, categories: [] })
const assist = ref({ sessions: 0, questions: 0, answers: 0, adoptions: 0,
                     adoption_rate: 0, no_evidence_rate: 0, top_cited_laws: [], daily: [] })

const citeRef = ref(null), trendRef = ref(null), deptRef = ref(null), syncRef = ref(null)
const charts = {}   // 实例缓存：{cite, trend, dept, sync}，避免重复 init

const pct = (v) => `${Math.round((v || 0) * 1000) / 10}%`
const short = (s, n = 22) => (s || '').length > n ? s.slice(0, n) + '…' : (s || '')

const PALETTE = ['#2b5fad', '#4a80d4', '#67c23a', '#e6a23c', '#d9534f', '#909399',
                 '#7b68ee', '#20b2aa', '#f4a460', '#778899', '#3cb371', '#cd5c5c']

function render(el, key, option) {
  if (!el) return
  if (!charts[key]) charts[key] = echarts.init(el)
  charts[key].setOption(option)
}

async function loadKb() {
  kb.value = await fetchKbStats()
  await nextTick()
  // 部门分布（饼图，取 Top10 + 其余合并）
  const cats = kb.value.categories
  const top = cats.slice(0, 10)
  const rest = cats.slice(10).reduce((s, c) => s + c.count, 0)
  const data = [...top.map(c => ({ name: c.name, value: c.count }))]
  if (rest > 0) data.push({ name: '其他部门', value: rest })
  render(deptRef.value, 'dept', {
    color: PALETTE,
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    series: [{ type: 'pie', radius: ['38%', '68%'], center: ['50%', '52%'],
               itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 1 },
               label: { fontSize: 11, formatter: '{b}' },
               data }],
  })
  // 灌库覆盖（环形）
  const synced = kb.value.synced, rest2 = kb.value.pending + kb.value.skipped
  render(syncRef.value, 'sync', {
    color: ['#67c23a', '#e6a23c'],
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条' },
    series: [{ type: 'pie', radius: ['58%', '78%'], center: ['50%', '50%'],
               label: { position: 'center', fontSize: 14, fontWeight: 700,
                        formatter: () => (kb.value.laws ? `${Math.round(synced / kb.value.laws * 100)}%` : '0%'),
                        color: '#1f3350' },
               data: [{ name: '已入向量库', value: synced }, { name: '未入库', value: rest2 }] }],
  })
}

async function loadAssist() {
  assist.value = await fetchAssistStats(days.value)
  await nextTick()
  // 法条引用 Top10（横向条形）
  const items = [...assist.value.top_cited_laws].reverse()
  render(citeRef.value, 'cite', {
    grid: { left: 10, right: 26, top: 8, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
               formatter: (ps) => `${ps[0].name}<br/>被引用 ${ps[0].value} 次` },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef1f6' } }, axisLabel: { fontSize: 11 } },
    yAxis: { type: 'category', data: items.map(x => short(x.title || x.ref_id)),
             axisLabel: { fontSize: 11 }, axisTick: { show: false } },
    series: [{ type: 'bar', data: items.map(x => x.count), barWidth: 12,
               itemStyle: { color: '#2b5fad', borderRadius: [0, 4, 4, 0] } }],
  })
  // 提问趋势（折线）
  const daily = assist.value.daily
  render(trendRef.value, 'trend', {
    grid: { left: 10, right: 20, top: 18, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: daily.map(d => d.date.slice(5)),
             axisLabel: { fontSize: 11 }, boundaryGap: false },
    yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: '#eef1f6' } },
             axisLabel: { fontSize: 11 } },
    series: [{ type: 'line', data: daily.map(d => d.count), smooth: true,
               symbolSize: 6, lineStyle: { color: '#2b5fad', width: 2.5 },
               itemStyle: { color: '#2b5fad' },
               areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                 colorStops: [{ offset: 0, color: 'rgba(43,95,173,0.22)' },
                              { offset: 1, color: 'rgba(43,95,173,0.02)' }] } } }],
  })
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadKb(), loadAssist()])
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onResize() {
  Object.values(charts).forEach(c => c?.resize())
}

onMounted(() => {
  loadAll()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  Object.values(charts).forEach(c => c?.dispose())
})
</script>

<style scoped>
.stats-page { background: #fff; border-radius: var(--radius); padding: 20px 24px; box-shadow: var(--shadow-card); }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.toolbar .hint { color: #909399; font-size: 13px; }
.toolbar .spacer { flex: 1; }
.metric-row {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; margin-bottom: 18px;
}
.metric {
  padding: 18px 20px; border-radius: 14px;
  background: linear-gradient(160deg, #f8fbff 0%, #eaf2fd 100%);
  border: 1px solid #e2ecfa;
  box-shadow: 0 2px 10px rgba(43, 95, 173, 0.06);
  transition: transform .2s ease, box-shadow .2s ease;
}
.metric:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(43, 95, 173, 0.16);
}
.metric .num {
  font-size: 26px; font-weight: 800; letter-spacing: 0.5px;
  background: linear-gradient(135deg, #2f66b8 0%, #4a80d4 55%, #5a90e0 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}
.metric .label { margin-top: 6px; font-size: 12.5px; color: #6b7a90; letter-spacing: 0.5px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.chart-card {
  border: 1px solid #eef1f6; border-radius: 12px; padding: 14px 16px 8px;
  background: #fff;
}
.chart-title { font-size: 13.5px; font-weight: 700; color: #1f3350; margin-bottom: 8px; }
.chart-title .sub { font-weight: 400; font-size: 12px; color: #909399; }
.chart { height: 260px; }
</style>
