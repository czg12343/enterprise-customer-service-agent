<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sidebarOpen = ref(false)

const roleName = computed(() => ({ customer: '普通用户', service: '客服人员', admin: '系统管理员' })[auth.user?.role || 'customer'])
const menu = computed(() => [
  { path: '/chat', label: '智能客服', mark: 'AI' },
  { path: '/orders', label: auth.user?.role === 'customer' ? '我的订单' : '订单中心', mark: '订' },
  ...(auth.user?.role === 'admin' ? [{ path: '/products', label: '商品管理', mark: '品' }] : []),
  { path: '/tickets', label: auth.user?.role === 'customer' ? '我的工单' : '工单中心', mark: '单' },
  ...(auth.user?.role !== 'customer' ? [{ path: '/handoffs', label: '人工接管', mark: '接' }] : []),
  ...(auth.user?.role !== 'customer' ? [{ path: '/evaluation', label: '评估中心', mark: '评' }] : []),
  ...(auth.user?.role !== 'customer' ? [{ path: '/retrieval', label: '检索测试', mark: '检' }] : []),
  ...(auth.user?.role !== 'customer' ? [{ path: '/admin', label: '运营管理', mark: '管' }] : []),
])

function signOut() {
  auth.logout()
  router.push('/login')
}

watch(() => route.path, () => { sidebarOpen.value = false })
</script>

<template>
  <div class="app-shell">
    <header class="mobile-header">
      <button class="mobile-menu-button" aria-label="打开导航" @click="sidebarOpen = true">☰</button>
      <div class="mobile-brand"><span class="brand-symbol">E</span><strong>EnterpriseMind</strong></div>
      <span class="mobile-online"><i></i>在线</span>
    </header>
    <button v-if="sidebarOpen" class="sidebar-mask" aria-label="关闭导航" @click="sidebarOpen = false"></button>
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="brand">
        <span class="brand-symbol">E</span>
        <div><strong>EnterpriseMind</strong><small>企业智能服务中枢</small></div>
        <button class="sidebar-close" aria-label="关闭导航" @click="sidebarOpen = false">×</button>
      </div>
      <nav class="nav-list">
        <router-link v-for="item in menu" :key="item.path" :to="item.path" :class="{ active: route.path === item.path }" @click="sidebarOpen = false">
          <span class="nav-mark">{{ item.mark }}</span>{{ item.label }}
        </router-link>
      </nav>
      <div class="service-status"><i></i><span>智能服务在线</span><small>LangGraph 已连接</small></div>
      <div class="user-panel">
        <span class="avatar">{{ auth.user?.username.slice(0, 1).toUpperCase() }}</span>
        <div><strong>{{ auth.user?.username }}</strong><small>{{ roleName }}</small></div>
        <button title="退出登录" @click="signOut">↗</button>
      </div>
    </aside>
    <main class="main-content"><router-view /></main>
  </div>
</template>
