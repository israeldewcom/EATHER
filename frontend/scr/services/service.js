import axios from 'axios'
import { toast } from 'react-hot-toast'

// Create axios instance with interceptors
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
  headers: {
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  },
  timeout: 30000, // 30 seconds
  withCredentials: true,
})

// Request queue for rate limiting
let pendingRequests = []
let isRefreshing = false

// Request interceptor
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    const companyId = localStorage.getItem('current_company_id')
    
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    
    if (companyId) {
      config.headers['X-Company-Id'] = companyId
    }
    
    // Add request ID for tracking
    config.headers['X-Request-ID'] = crypto.randomUUID()
    
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
api.interceptors.response.use(
  (response) => {
    // Handle successful responses
    if (response.data?.message && !response.config.silent) {
      toast.success(response.data.message, { duration: 3000 })
    }
    return response
  },
  async (error) => {
    const originalRequest = error.config
    
    // Handle network errors
    if (!error.response) {
      toast.error('Network error. Please check your connection.')
      return Promise.reject(error)
    }
    
    const { status, data } = error.response
    
    // Handle 401 Unauthorized (token expired)
    if (status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Wait for token refresh
        return new Promise((resolve) => {
          pendingRequests.push(() => {
            resolve(api(originalRequest))
          })
        })
      }
      
      originalRequest._retry = true
      isRefreshing = true
      
      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (!refreshToken) {
          throw new Error('No refresh token')
        }
        
        const response = await axios.post('/api/v1/auth/refresh', {
          refresh_token: refreshToken,
        })
        
        const { access_token, refresh_token } = response.data
        localStorage.setItem('access_token', access_token)
        localStorage.setItem('refresh_token', refresh_token)
        
        // Update Authorization header
        api.defaults.headers.common.Authorization = `Bearer ${access_token}`
        originalRequest.headers.Authorization = `Bearer ${access_token}`
        
        // Retry pending requests
        pendingRequests.forEach(callback => callback())
        pendingRequests = []
        
        // Retry original request
        return api(originalRequest)
      } catch (refreshError) {
        // Refresh failed, logout user
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('user')
        localStorage.removeItem('current_company_id')
        
        // Redirect to login
        window.location.href = '/login'
        toast.error('Session expired. Please login again.')
        
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }
    
    // Handle other error statuses
    switch (status) {
      case 400:
        toast.error(data.detail || 'Bad request')
        break
      case 403:
        toast.error('You do not have permission to perform this action')
        break
      case 404:
        toast.error('Resource not found')
        break
      case 422:
        // Validation errors
        if (data.detail) {
          if (Array.isArray(data.detail)) {
            data.detail.forEach(err => {
              toast.error(`${err.loc?.join('.')}: ${err.msg}`)
            })
          } else {
            toast.error(data.detail)
          }
        }
        break
      case 429:
        toast.error('Too many requests. Please slow down.')
        break
      case 500:
        toast.error('Internal server error')
        break
      case 502:
      case 503:
      case 504:
        toast.error('Service temporarily unavailable')
        break
      default:
        toast.error(data.detail || 'An error occurred')
    }
    
    return Promise.reject(error)
  }
)

// API Endpoints
export const authAPI = {
  login: (email, password) => 
    api.post('/auth/login', { email, password }),
  
  register: (userData) => 
    api.post('/auth/register', userData),
  
  logout: () => 
    api.post('/auth/logout'),
  
  getCurrentUser: () => 
    api.get('/auth/me'),
  
  updateProfile: (userData) => 
    api.put('/auth/me', userData),
  
  changePassword: (data) => 
    api.post('/auth/change-password', data),
  
  forgotPassword: (email) => 
    api.post('/auth/forgot-password', { email }),
  
  resetPassword: (token, newPassword) => 
    api.post('/auth/reset-password', { token, new_password: newPassword }),
  
  enableMFA: () => 
    api.post('/auth/mfa/enable'),
  
  verifyMFA: (code) => 
    api.post('/auth/mfa/verify', { code }),
  
  disableMFA: () => 
    api.post('/auth/mfa/disable'),
}

export const transactionsAPI = {
  getTransactions: (params = {}) => 
    api.get('/transactions', { params }),
  
  getTransaction: (id) => 
    api.get(`/transactions/${id}`),
  
  createTransaction: (data) => 
    api.post('/transactions', data),
  
  updateTransaction: (id, data) => 
    api.put(`/transactions/${id}`, data),
  
  deleteTransaction: (id) => 
    api.delete(`/transactions/${id}`),
  
  getStats: (params = {}) => 
    api.get('/transactions/stats/summary', { params }),
  
  categorizeTransaction: (id, category) => 
    api.post(`/transactions/${id}/categorize`, { category }),
  
  reconcileTransaction: (id, receiptId) => 
    api.post(`/transactions/${id}/reconcile`, { receipt_id: receiptId }),
  
  flagTransaction: (id, reason) => 
    api.post(`/transactions/${id}/flag`, { reason }),
  
  importCSV: (csvData, hasHeaders = true) => 
    api.post('/transactions/import/csv', { csv_data: csvData, has_headers: hasHeaders }),
  
  bulkCategorize: (transactionIds) => 
    api.post('/transactions/auto-categorize/bulk', { transaction_ids: transactionIds }),
  
  bulkReconcile: (transactionIds) => 
    api.post('/transactions/bulk/reconcile', { transaction_ids: transactionIds }),
  
  exportCSV: (params = {}) => 
    api.get('/transactions/export/csv', { params, responseType: 'blob' }),
  
  search: (query, params = {}) => 
    api.get('/transactions/search', { params: { q: query, ...params } }),
}

export const documentsAPI = {
  uploadDocument: (formData, onProgress) => 
    api.post('/documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: onProgress,
    }),
  
  getDocuments: (params = {}) => 
    api.get('/documents', { params }),
  
  getDocument: (id) => 
    api.get(`/documents/${id}`),
  
  updateDocument: (id, data) => 
    api.put(`/documents/${id}`, data),
  
  deleteDocument: (id) => 
    api.delete(`/documents/${id}`),
  
  processDocument: (id) => 
    api.post(`/documents/${id}/process`),
  
  extractData: (id) => 
    api.post(`/documents/${id}/extract`),
  
  bulkProcess: (documentIds) => 
    api.post('/documents/bulk/process', { document_ids: documentIds }),
  
  getPreview: (id) => 
    api.get(`/documents/${id}/preview`, { responseType: 'blob' }),
  
  search: (query, params = {}) => 
    api.get('/documents/search', { params: { q: query, ...params } }),
}

export const reportsAPI = {
  generateReport: (type, params = {}) => 
    api.post('/reports/generate', { report_type: type, ...params }),
  
  getReports: (params = {}) => 
    api.get('/reports', { params }),
  
  getReport: (id) => 
    api.get(`/reports/${id}`),
  
  downloadReport: (id) => 
    api.get(`/reports/${id}/download`, { responseType: 'blob' }),
  
  scheduleReport: (data) => 
    api.post('/reports/schedule', data),
  
  getTemplates: () => 
    api.get('/reports/templates'),
  
  createTemplate: (data) => 
    api.post('/reports/templates', data),
  
  updateTemplate: (id, data) => 
    api.put(`/reports/templates/${id}`, data),
  
  deleteTemplate: (id) => 
    api.delete(`/reports/templates/${id}`),
}

export const aiAPI = {
  categorizeText: (text) => 
    api.post('/ai/categorize', { text }),
  
  predictCashFlow: (data) => 
    api.post('/ai/cashflow/predict', data),
  
  getInsights: () => 
    api.get('/ai/insights'),
  
  taxOptimization: (data) => 
    api.post('/ai/tax/optimize', data),
  
  detectAnomalies: () => 
    api.get('/ai/anomalies'),
  
  generateSuggestions: (data) => 
    api.post('/ai/suggestions', data),
  
  chat: (message, context) => 
    api.post('/ai/chat', { message, context }),
  
  trainModel: (data) => 
    api.post('/ai/train', data),
}

export const bankAPI = {
  getAccounts: () => 
    api.get('/bank/accounts'),
  
  createLinkToken: () => 
    api.post('/bank/link-token'),
  
  exchangeToken: (publicToken) => 
    api.post('/bank/exchange-token', { public_token: publicToken }),
  
  syncAccounts: () => 
    api.post('/bank/sync'),
  
  getTransactions: (accountId, params = {}) => 
    api.get(`/bank/accounts/${accountId}/transactions`, { params }),
  
  removeAccount: (accountId) => 
    api.delete(`/bank/accounts/${accountId}`),
  
  getBalance: (accountId) => 
    api.get(`/bank/accounts/${accountId}/balance`),
  
  getInstitutions: () => 
    api.get('/bank/institutions'),
}

export const taxAPI = {
  getSummary: (year) => 
    api.get('/tax/summary', { params: { year } }),
  
  getDeductions: (params = {}) => 
    api.get('/tax/deductions', { params }),
  
  addDeduction: (data) => 
    api.post('/tax/deductions', data),
  
  updateDeduction: (id, data) => 
    api.put(`/tax/deductions/${id}`, data),
  
  deleteDeduction: (id) => 
    api.delete(`/tax/deductions/${id}`),
  
  generateForm: (formType, year) => 
    api.post('/tax/forms/generate', { form_type: formType, year }),
  
  getForms: (params = {}) => 
    api.get('/tax/forms', { params }),
  
  getForm: (id) => 
    api.get(`/tax/forms/${id}`),
  
  calculateEstimatedTax: (data) => 
    api.post('/tax/calculate', data),
  
  getTaxTips: () => 
    api.get('/tax/tips'),
}

export const analyticsAPI = {
  getMetrics: (params = {}) => 
    api.get('/analytics/metrics', { params }),
  
  getPerformanceMetrics: (params = {}) => 
    api.get('/analytics/performance', { params }),
  
  getTrends: (params = {}) => 
    api.get('/analytics/trends', { params }),
  
  getForecast: (params = {}) => 
    api.get('/analytics/forecast', { params }),
  
  getComparisons: (params = {}) => 
    api.get('/analytics/comparisons', { params }),
  
  getCustomReport: (config) => 
    api.post('/analytics/custom-report', config),
  
  exportAnalytics: (format, params = {}) => 
    api.get('/analytics/export', { params: { format, ...params }, responseType: 'blob' }),
}

export const companyAPI = {
  getCompanies: () => 
    api.get('/companies'),
  
  getCompany: (id) => 
    api.get(`/companies/${id}`),
  
  createCompany: (data) => 
    api.post('/companies', data),
  
  updateCompany: (id, data) => 
    api.put(`/companies/${id}`, data),
  
  deleteCompany: (id) => 
    api.delete(`/companies/${id}`),
  
  getMembers: (companyId) => 
    api.get(`/companies/${companyId}/members`),
  
  addMember: (companyId, data) => 
    api.post(`/companies/${companyId}/members`, data),
  
  updateMember: (companyId, userId, data) => 
    api.put(`/companies/${companyId}/members/${userId}`, data),
  
  removeMember: (companyId, userId) => 
    api.delete(`/companies/${companyId}/members/${userId}`),
  
  getSettings: (companyId) => 
    api.get(`/companies/${companyId}/settings`),
  
  updateSettings: (companyId, data) => 
    api.put(`/companies/${companyId}/settings`, data),
}

export const settingsAPI = {
  getUserPreferences: () => 
    api.get('/settings/preferences'),
  
  updateUserPreferences: (data) => 
    api.put('/settings/preferences', data),
  
  getNotificationSettings: () => 
    api.get('/settings/notifications'),
  
  updateNotificationSettings: (data) => 
    api.put('/settings/notifications', data),
  
  getIntegrations: () => 
    api.get('/settings/integrations'),
  
  connectIntegration: (integrationId, data) => 
    api.post(`/settings/integrations/${integrationId}/connect`, data),
  
  disconnectIntegration: (integrationId) => 
    api.delete(`/settings/integrations/${integrationId}/connect`),
  
  getBillingInfo: () => 
    api.get('/settings/billing'),
  
  updateBillingInfo: (data) => 
    api.put('/settings/billing', data),
  
  getSubscription: () => 
    api.get('/settings/subscription'),
  
  updateSubscription: (planId) => 
    api.post('/settings/subscription', { plan_id: planId }),
  
  cancelSubscription: () => 
    api.delete('/settings/subscription'),
}

export const webhookAPI = {
  createWebhook: (data) => 
    api.post('/webhooks', data),
  
  getWebhooks: () => 
    api.get('/webhooks'),
  
  updateWebhook: (id, data) => 
    api.put(`/webhooks/${id}`, data),
  
  deleteWebhook: (id) => 
    api.delete(`/webhooks/${id}`),
  
  testWebhook: (id) => 
    api.post(`/webhooks/${id}/test`),
}

// Helper function for file downloads
export const downloadFile = (blob, filename) => {
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)
}

// Helper function for paginated queries
export const createPaginatedQuery = (key, fetchFn, options = {}) => ({
  queryKey: key,
  queryFn: async ({ pageParam = 1 }) => {
    const response = await fetchFn({ page: pageParam, ...options.params })
    return {
      data: response.data,
      nextPage: response.data.has_more ? pageParam + 1 : undefined,
      total: response.data.total,
    }
  },
  getNextPageParam: (lastPage) => lastPage.nextPage,
  ...options,
})

export default api
