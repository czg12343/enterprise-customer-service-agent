import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, clearAuthSession, saveAuthSession } from '../api/client'
import type { User } from '../types'

interface LoginResponse {
  access_token: string
  refresh_token: string
  user: User
}

export const useAuthStore = defineStore('auth', () => {
  const saved = localStorage.getItem('user')
  let initialUser: User | null = null
  if (saved) {
    try {
      initialUser = JSON.parse(saved) as User
    } catch {
      clearAuthSession()
    }
  }
  const user = ref<User | null>(initialUser)
  const loading = ref(false)
  const isAuthenticated = computed(() => Boolean(user.value && localStorage.getItem('access_token')))

  async function login(username: string, password: string) {
    loading.value = true
    try {
      const { data } = await api.post<LoginResponse>('/auth/login', { username, password })
      saveAuthSession(data)
      user.value = data.user
    } finally {
      loading.value = false
    }
  }

  function logout() {
    clearAuthSession()
    user.value = null
  }

  return { user, loading, isAuthenticated, login, logout }
})
