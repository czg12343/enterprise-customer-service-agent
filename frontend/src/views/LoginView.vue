<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const form = reactive({ username: 'customer', password: 'Customer123!' })
const serviceState = ref<'checking' | 'online' | 'offline'>('checking')
const serviceLabel = computed(() => ({ checking: '正在检查服务', online: '后端服务已连接', offline: '后端服务未连接' })[serviceState.value])

function useDemo(role: 'customer' | 'service' | 'admin') {
  const passwords = { customer: 'Customer123!', service: 'Service123!', admin: 'Admin123!' }
  form.username = role
  form.password = passwords[role]
}

async function submit() {
  try {
    await auth.login(form.username, form.password)
    router.push('/chat')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '登录失败，请检查账号信息')
  }
}

onMounted(async () => {
  try {
    const response = await fetch('/health')
    serviceState.value = response.ok ? 'online' : 'offline'
  } catch {
    serviceState.value = 'offline'
  }
})
</script>

<template>
  <div class="login-page">
    <section class="login-story">
      <div class="story-mark">EM</div>
      <p class="eyebrow">ENTERPRISE AI OPERATIONS</p>
      <h1>让每一次服务，<br />都有答案和行动。</h1>
      <p>融合企业知识、订单物流与售后流程的智能客服 Agent。可信回答，安全执行，全程可追溯。</p>
      <div class="flow-line">
        <span>理解意图</span><b>→</b><span>调用业务</span><b>→</b><span>交付结果</span>
      </div>
      <div class="story-metrics">
        <div><strong>10+</strong><span>业务工具</span></div>
        <div><strong>RAG</strong><span>引用可溯源</span></div>
        <div><strong>24/7</strong><span>持续服务</span></div>
      </div>
    </section>
    <section class="login-card">
      <div class="login-card-top">
        <p class="eyebrow">WELCOME BACK</p>
        <span class="backend-status" :class="serviceState"><i></i>{{ serviceLabel }}</span>
      </div>
      <h2>登录 EnterpriseMind</h2>
      <p class="muted">进入你的企业智能服务工作台</p>
      <el-form label-position="top" size="large" @submit.prevent="submit">
        <el-form-item label="账号"><el-input v-model="form.username" placeholder="请输入用户名" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password placeholder="请输入密码" @keyup.enter="submit" /></el-form-item>
        <el-button class="submit-button" type="primary" :loading="auth.loading" @click="submit">安全登录</el-button>
      </el-form>
      <div class="demo-box">
        <span>演示账号</span>
        <button @click="useDemo('customer')">普通用户</button>
        <button @click="useDemo('service')">客服</button>
        <button @click="useDemo('admin')">管理员</button>
      </div>
      <small class="security-note">密码采用 PBKDF2 加密，接口使用 JWT 权限校验</small>
      <p v-if="serviceState === 'offline'" class="offline-tip">请先在另一个终端运行 <code>python backend\run.py</code></p>
    </section>
  </div>
</template>
