<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { serverDate } from '../utils/date'

interface EvalTool { name: string; status: string }
interface EvalCase {
  key: string; name: string; query: string; passed: boolean
  actual_intent: string; expected_intent: string; intent_correct: boolean
  answer_score: number; citation_score?: number; tool_score: number
  latency_ms: number; prompt_tokens: number; completion_tokens: number
  estimated_cost_usd: number; answer: string; sources: string[]; tools: EvalTool[]; error?: string
}
interface EvalRun {
  id: string; status: string; total_cases: number; passed_cases: number
  answer_accuracy: number; citation_accuracy: number; tool_success_rate: number
  average_latency_ms: number; prompt_tokens: number; completion_tokens: number
  estimated_cost_usd: number; user_satisfaction?: number; results: EvalCase[]; created_at: string
}
interface Overview {
  latest?: EvalRun; history: EvalRun[]; user_satisfaction?: number
  positive_feedback: number; negative_feedback: number
}

const overview = ref<Overview>({ history: [], positive_feedback: 0, negative_feedback: 0 })
const running = ref(false)
const latest = computed(() => overview.value.latest)
const totalTokens = computed(() => (latest.value?.prompt_tokens || 0) + (latest.value?.completion_tokens || 0))

const intentNames: Record<string, string> = {
  order: '订单', logistics: '物流', product: '商品', ticket: '工单', refund: '退款',
  knowledge: '知识问答', human: '人工接管', general: '通用对话', error: '运行错误',
}
function intentName(value: string) { return intentNames[value] || value }
function percent(value?: number) { return value == null ? '暂无数据' : `${value.toFixed(1)}%` }

async function load() {
  overview.value = (await api.get<Overview>('/evaluations')).data
}
async function runEvaluation() {
  running.value = true
  try {
    await api.post('/evaluations/run', {}, { timeout: 180_000 })
    await load()
    ElMessage.success('自动评测完成')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '评测运行失败，请检查后端和模型连接')
  } finally { running.value = false }
}

onMounted(load)
</script>

<template>
  <div class="content-page evaluation-page">
    <header class="page-header roomy evaluation-head">
      <div><p class="eyebrow">AGENT EVALUATION</p><h1>评估中心</h1><p>用固定回归集实际运行 Agent，持续衡量答案、引用、工具、性能与成本</p></div>
      <el-button type="primary" size="large" :loading="running" @click="runEvaluation">{{ running ? '正在执行 6 个用例…' : '运行自动评测' }}</el-button>
    </header>

    <section class="evaluation-metrics">
      <article><span>回答正确率</span><strong>{{ percent(latest?.answer_accuracy) }}</strong><small>预期关键词覆盖率</small></article>
      <article><span>引用来源准确率</span><strong>{{ percent(latest?.citation_accuracy) }}</strong><small>命中预期知识文档</small></article>
      <article><span>工具调用成功率</span><strong>{{ percent(latest?.tool_success_rate) }}</strong><small>预期工具成功执行</small></article>
      <article><span>平均响应时间</span><strong>{{ latest ? `${latest.average_latency_ms.toFixed(0)} ms` : '暂无数据' }}</strong><small>端到端 Agent 延迟</small></article>
      <article><span>Token 消耗</span><strong>{{ totalTokens }}</strong><small>输入 {{ latest?.prompt_tokens || 0 }} / 输出 {{ latest?.completion_tokens || 0 }}</small></article>
      <article><span>估算调用成本</span><strong>${{ (latest?.estimated_cost_usd || 0).toFixed(6) }}</strong><small>供应商 cost 或配置单价</small></article>
      <article><span>用户满意度</span><strong>{{ percent(overview.user_satisfaction) }}</strong><small>👍 {{ overview.positive_feedback }} / 👎 {{ overview.negative_feedback }}</small></article>
    </section>

    <section class="panel-card evaluation-results">
      <header><div><p class="eyebrow">REGRESSION CASES</p><h2>最新评测明细</h2><p v-if="latest">{{ latest.passed_cases }}/{{ latest.total_cases }} 个用例通过 · {{ serverDate(latest.created_at).toLocaleString() }}</p></div><el-tag v-if="latest" :type="latest.passed_cases === latest.total_cases ? 'success' : 'warning'">{{ latest.passed_cases === latest.total_cases ? '全部通过' : '需要改进' }}</el-tag></header>
      <el-table v-if="latest" :data="latest.results" row-key="key">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="evaluation-detail">
              <div><span>测试问题</span><p>{{ row.query }}</p></div>
              <div><span>Agent 回答</span><p>{{ row.answer || row.error || '没有返回答案' }}</p></div>
              <div><span>引用文档</span><p><el-tag v-for="source in row.sources" :key="source" size="small">{{ source }}</el-tag><em v-if="!row.sources.length">无引用</em></p></div>
              <div><span>工具轨迹</span><p><el-tag v-for="tool in row.tools" :key="tool.name" size="small" :type="tool.status === 'success' ? 'success' : 'warning'">{{ tool.name }} · {{ tool.status }}</el-tag><em v-if="!row.tools.length">无业务工具</em></p></div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="用例" min-width="180"><template #default="{ row }"><strong>{{ row.name }}</strong><small class="eval-case-key">{{ row.key }}</small></template></el-table-column>
        <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="row.passed ? 'success' : 'danger'">{{ row.passed ? '通过' : '失败' }}</el-tag></template></el-table-column>
        <el-table-column label="意图" width="125"><template #default="{ row }"><span :class="{ 'metric-failed': !row.intent_correct }">{{ intentName(row.actual_intent) }}</span></template></el-table-column>
        <el-table-column label="答案" width="95"><template #default="{ row }">{{ row.answer_score.toFixed(0) }}%</template></el-table-column>
        <el-table-column label="引用" width="95"><template #default="{ row }">{{ row.citation_score == null ? '不适用' : `${row.citation_score.toFixed(0)}%` }}</template></el-table-column>
        <el-table-column label="工具" width="95"><template #default="{ row }">{{ row.tool_score.toFixed(0) }}%</template></el-table-column>
        <el-table-column label="延迟" width="100"><template #default="{ row }">{{ row.latency_ms }} ms</template></el-table-column>
        <el-table-column label="Token" width="90"><template #default="{ row }">{{ row.prompt_tokens + row.completion_tokens }}</template></el-table-column>
      </el-table>
      <div v-else class="evaluation-empty"><span>评</span><h3>还没有评测记录</h3><p>点击“运行自动评测”，系统会执行 6 个真实 Agent 回归用例。</p></div>
    </section>

    <section v-if="overview.history.length" class="panel-card evaluation-history">
      <header><div><p class="eyebrow">HISTORY</p><h2>历史趋势</h2></div></header>
      <el-table :data="overview.history">
        <el-table-column label="执行时间" min-width="180"><template #default="{ row }">{{ serverDate(row.created_at).toLocaleString() }}</template></el-table-column>
        <el-table-column label="通过" width="100"><template #default="{ row }">{{ row.passed_cases }}/{{ row.total_cases }}</template></el-table-column>
        <el-table-column prop="answer_accuracy" label="回答正确率" width="130" />
        <el-table-column prop="citation_accuracy" label="引用准确率" width="130" />
        <el-table-column prop="tool_success_rate" label="工具成功率" width="130" />
        <el-table-column label="平均延迟" width="120"><template #default="{ row }">{{ row.average_latency_ms.toFixed(0) }} ms</template></el-table-column>
        <el-table-column label="Token" width="100"><template #default="{ row }">{{ row.prompt_tokens + row.completion_tokens }}</template></el-table-column>
        <el-table-column label="成本（USD）" width="130"><template #default="{ row }">${{ row.estimated_cost_usd.toFixed(6) }}</template></el-table-column>
      </el-table>
    </section>
  </div>
</template>
