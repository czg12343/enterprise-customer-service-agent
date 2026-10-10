import axios, { type InternalAxiosRequestConfig } from 'axios'
import type { User } from '../types'

export const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
})

const authKeys = ['access_token', 'refresh_token', 'user'] as const
let refreshRequest: Promise<string> | null = null

interface TokenResponse {
  access_token: string
  refresh_token: string
  user: User
}

export function clearAuthSession() {
  authKeys.forEach((key) => localStorage.removeItem(key))
}

export function saveAuthSession(data: TokenResponse) {
  localStorage.setItem('access_token', data.access_token)
  localStorage.setItem('refresh_token', data.refresh_token)
  localStorage.setItem('user', JSON.stringify(data.user))
}

export function refreshAccessToken(): Promise<string> {
  if (refreshRequest) return refreshRequest
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return Promise.reject(new Error('登录状态已失效'))

  refreshRequest = axios
    .post<TokenResponse>('/api/v1/auth/refresh', { refresh_token: refreshToken }, { timeout: 15_000 })
    .then(({ data }) => {
      saveAuthSession(data)
      return data.access_token
    })
    .catch((error) => {
      clearAuthSession()
      throw error
    })
    .finally(() => { refreshRequest = null })
  return refreshRequest
}

function redirectToLogin() {
  if (location.pathname !== '/login') location.assign('/login')
}

export async function authenticatedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const request = async (token: string | null) => {
    const headers = new Headers(init.headers)
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return fetch(url, { ...init, headers })
  }

  let response = await request(localStorage.getItem('access_token'))
  if (response.status !== 401) return response
  try {
    response = await request(await refreshAccessToken())
  } catch {
    redirectToLogin()
    return response
  }
  if (response.status === 401) {
    clearAuthSession()
    redirectToLogin()
  }
  return response
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined
    const isAuthRequest = original?.url?.startsWith('/auth/')
    if (error.response?.status === 401 && original && !original._retry && !isAuthRequest) {
      original._retry = true
      try {
        const accessToken = await refreshAccessToken()
        original.headers.Authorization = `Bearer ${accessToken}`
        return api(original)
      } catch {
        clearAuthSession()
      }
    } else if (error.response?.status === 401 && !isAuthRequest) {
      clearAuthSession()
    }
    if (error.response?.status === 401) redirectToLogin()
    return Promise.reject(error)
  },
)
