import { useState, useEffect, useMemo } from 'react'
import { 
  TrendingUp, 
  TrendingDown, 
  DollarSign, 
  CreditCard, 
  Upload,
  AlertCircle,
  CheckCircle,
  Clock,
  Users,
  Building,
  PieChart,
  BarChart3,
  Download,
  RefreshCw
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../contexts/AuthContext'
import { useWebSocket } from '../../contexts/WebSocketContext'
import api, { transactionsAPI, analyticsAPI, aiAPI } from '../../services/api'
import toast from 'react-hot-toast'
import StatsCard from '../../components/Dashboard/StatsCard'
import RecentTransactions from '../../components/Dashboard/RecentTransactions'
import CategoryChart from '../../components/Dashboard/CategoryChart'
import CashFlowChart from '../../components/Dashboard/CashFlowChart'
import QuickActions from '../../components/Dashboard/QuickActions'
import InsightsWidget from '../../components/Dashboard/InsightsWidget'
import PerformanceMetrics from '../../components/Dashboard/PerformanceMetrics'
import TaxSummary from '../../components/Dashboard/TaxSummary'
import BankSyncStatus from '../../components/Dashboard/BankSyncStatus'
import { formatCurrency, formatPercentage } from '../../utils/formatters'

const Dashboard = () => {
  const { user } = useAuth()
  const { subscribe, unsubscribe } = useWebSocket()
  const queryClient = useQueryClient()
  const [timeRange, setTimeRange] = useState('month')
  const [isRefreshing, setIsRefreshing] = useState(false)

  // Fetch dashboard data
  const { data: dashboardData, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard', user?.id, timeRange],
    queryFn: async () => {
      const [stats, transactions, insights, metrics] = await Promise.all([
        transactionsAPI.getStats({ period: timeRange }),
        transactionsAPI.getTransactions({ limit: 10 }),
        aiAPI.getInsights(),
        analyticsAPI.getPerformanceMetrics({ period: timeRange })
      ])
      return { stats, transactions: transactions.data, insights: insights.data, metrics: metrics.data }
    },
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  // Fetch tax summary
  const { data: taxSummary } = useQuery({
    queryKey: ['taxSummary', user?.id],
    queryFn: () => api.get('/tax/summary').then(res => res.data),
    enabled: !!user?.id,
  })

  // Set up WebSocket subscriptions
  useEffect(() => {
    const handleTransactionUpdate = (data) => {
      queryClient.invalidateQueries(['dashboard'])
      toast.success('New transaction processed', {
        icon: '💸',
      })
    }

    const handleDocumentProcessed = (data) => {
      queryClient.invalidateQueries(['documents'])
      toast.success('Document processed successfully', {
        icon: '✅',
      })
    }

    subscribe('transaction.created', handleTransactionUpdate)
    subscribe('document.processed', handleDocumentProcessed)

    return () => {
      unsubscribe('transaction.created', handleTransactionUpdate)
      unsubscribe('document.processed', handleDocumentProcessed)
    }
  }, [subscribe, unsubscribe, queryClient])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await refetch()
    setIsRefreshing(false)
    toast.success('Dashboard updated')
  }

  const handleTimeRangeChange = (range) => {
    setTimeRange(range)
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
          <p className="text-gray-600">Failed to load dashboard data</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const stats = dashboardData?.stats?.data || {}
  const transactions = dashboardData?.transactions || []
  const insights = dashboardData?.insights || {}
  const metrics = dashboardData?.metrics || {}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-600">Welcome back, {user?.full_name || user?.email}!</p>
        </div>
        <div className="flex items-center space-x-4">
          {/* Time Range Selector */}
          <div className="flex bg-white rounded-lg border border-gray-200 p-1">
            {['day', 'week', 'month', 'quarter', 'year'].map((range) => (
              <button
                key={range}
                onClick={() => handleTimeRangeChange(range)}
                className={`px-3 py-1 text-sm font-medium rounded-md capitalize ${
                  timeRange === range
                    ? 'bg-primary-100 text-primary-700'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                {range}
              </button>
            ))}
          </div>
          
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="px-4 py-2 bg-white border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 flex items-center disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Welcome Banner */}
      <div className="bg-gradient-to-r from-primary-600 to-primary-800 rounded-xl p-6 text-white">
        <div className="flex flex-col md:flex-row md:items-center justify-between">
          <div>
            <h2 className="text-xl font-bold">Your AI CFO is Active</h2>
            <p className="text-primary-100 mt-2">
              {insights?.welcome_message || 'Monitoring your finances 24/7 for optimal performance'}
            </p>
          </div>
          <div className="mt-4 md:mt-0">
            <div className="flex items-center space-x-4">
              <div className="flex items-center">
                <CheckCircle className="h-5 w-5 text-green-300 mr-2" />
                <span className="text-sm">AI Categorization Active</span>
              </div>
              <div className="flex items-center">
                <Clock className="h-5 w-5 text-yellow-300 mr-2" />
                <span className="text-sm">Last sync: 5 min ago</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <QuickActions />

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Net Profit"
          value={formatCurrency(stats?.net_profit || 0)}
          icon={TrendingUp}
          trend={stats?.net_profit >= 0 ? 'up' : 'down'}
          trendValue={formatPercentage(stats?.profit_margin || 0)}
          color={stats?.net_profit >= 0 ? 'green' : 'red'}
          isLoading={isLoading}
        />
        
        <StatsCard
          title="Total Income"
          value={formatCurrency(stats?.total_income || 0)}
          icon={DollarSign}
          trend="up"
          trendValue={`${stats?.income_count || 0} transactions`}
          color="blue"
          isLoading={isLoading}
        />
        
        <StatsCard
          title="Total Expenses"
          value={formatCurrency(stats?.total_expenses || 0)}
          icon={CreditCard}
          trend="down"
          trendValue={`${stats?.expense_count || 0} transactions`}
          color="purple"
          isLoading={isLoading}
        />
        
        <StatsCard
          title="Cash Flow"
          value={formatCurrency(stats?.cash_flow || 0)}
          icon={BarChart3}
          trend={stats?.cash_flow >= 0 ? 'up' : 'down'}
          trendValue={formatPercentage(stats?.cash_flow_growth || 0)}
          color="indigo"
          isLoading={isLoading}
        />
      </div>

      {/* Charts & Insights Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* Expenses Chart */}
          <div className="bg-white rounded-xl shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Expenses by Category</h2>
              <button className="text-sm text-primary-600 hover:text-primary-700 font-medium flex items-center">
                <Download className="h-4 w-4 mr-1" />
                Export
              </button>
            </div>
            <div className="h-80">
              <CategoryChart 
                data={stats?.category_breakdown || []} 
                isLoading={isLoading}
              />
            </div>
          </div>
          
          {/* Cash Flow Chart */}
          <div className="bg-white rounded-xl shadow p-6">
            <h2 className="text-lg font-semibold mb-4">Cash Flow Forecast</h2>
            <div className="h-80">
              <CashFlowChart 
                data={metrics?.cash_flow_forecast || []}
                isLoading={isLoading}
              />
            </div>
          </div>
        </div>
        
        <div className="space-y-6">
          {/* AI Insights */}
          <InsightsWidget insights={insights} />
          
          {/* Performance Metrics */}
          <PerformanceMetrics metrics={metrics} />
          
          {/* Tax Summary */}
          <TaxSummary data={taxSummary} />
          
          {/* Bank Sync Status */}
          <BankSyncStatus />
        </div>
      </div>

      {/* Recent Transactions & Quick Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <RecentTransactions 
            transactions={transactions} 
            isLoading={isLoading}
            onRefresh={refetch}
          />
        </div>
        
        <div className="space-y-6">
          {/* System Status */}
          <div className="bg-white rounded-xl shadow p-6">
            <h2 className="text-lg font-semibold mb-4">System Status</h2>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <CheckCircle className="h-5 w-5 text-green-500 mr-2" />
                  <span>AI Categorization</span>
                </div>
                <span className="text-sm text-green-600 font-medium">Active (98%)</span>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <Clock className="h-5 w-5 text-yellow-500 mr-2" />
                  <span>Bank Sync</span>
                </div>
                <span className="text-sm text-yellow-600 font-medium">Last: 5 min ago</span>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <AlertCircle className="h-5 w-5 text-red-500 mr-2" />
                  <span>Needs Review</span>
                </div>
                <span className="text-sm text-red-600 font-medium">
                  {transactions.filter(t => t.needs_review).length} items
                </span>
              </div>
              
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <Users className="h-5 w-5 text-blue-500 mr-2" />
                  <span>Team Members</span>
                </div>
                <span className="text-sm text-blue-600 font-medium">3 active</span>
              </div>
            </div>
          </div>

          {/* Quick Tips */}
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl shadow p-6">
            <h2 className="text-lg font-semibold mb-3">💡 AI Tip</h2>
            <p className="text-sm text-gray-700 mb-4">
              {insights?.tip_of_the_day || "Forward receipts to receipts@yourcompany.aether.ai for instant processing."}
            </p>
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-500">Updated daily</span>
              <button className="text-sm text-primary-600 hover:text-primary-700 font-medium">
                Learn more →
              </button>
            </div>
          </div>

          {/* Quick Export */}
          <div className="bg-white rounded-xl shadow p-6">
            <h2 className="text-lg font-semibold mb-4">Quick Export</h2>
            <div className="space-y-3">
              <button className="w-full px-4 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center justify-between">
                <span>Transactions CSV</span>
                <Download className="h-4 w-4 text-gray-400" />
              </button>
              <button className="w-full px-4 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center justify-between">
                <span>Tax Report PDF</span>
                <Download className="h-4 w-4 text-gray-400" />
              </button>
              <button className="w-full px-4 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center justify-between">
                <span>Financial Summary</span>
                <Download className="h-4 w-4 text-gray-400" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
