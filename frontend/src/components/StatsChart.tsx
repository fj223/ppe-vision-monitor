/**
 * StatsChart
 *
 * Fetches today's violation statistics and renders:
 *   - Total violation count
 *   - Average Vision API processing latency
 *   - Bar chart of violations by type (recharts)
 * (Requirement 6.6)
 */

import React, { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchStats } from '../api/client'
import type { ViolationStats } from '../api/types'

const BAR_COLOURS: Record<string, string> = {
  helmet: '#ef4444',
  vest:   '#f97316',
}
const DEFAULT_BAR_COLOUR = '#6366f1'

function todayRange(): { start: string; end: string } {
  const now = new Date()
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  return { start: start.toISOString(), end: now.toISOString() }
}

export default function StatsChart() {
  const [stats, setStats] = useState<ViolationStats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const { start, end } = todayRange()
    fetchStats(start, end).then((result) => {
      if (result.ok) {
        setStats(result.data)
      } else {
        setError(result.error.message)
      }
    })
  }, [])

  if (error) {
    return (
      <div className="rounded-lg bg-red-900/30 border border-red-700 px-3 py-2 text-red-400 text-xs">
        ⚠ Stats unavailable: {error}
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="text-gray-500 text-xs">Loading statistics…</div>
    )
  }

  const chartData = Object.entries(stats.by_type).map(([type, count]) => ({
    type,
    count,
  }))

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-gray-300">Today's Summary</h3>

      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-700/50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-red-400">{stats.total_violations}</p>
          <p className="text-xs text-gray-400 mt-0.5">Total violations</p>
        </div>
        <div className="bg-gray-700/50 rounded-lg p-3 text-center">
          <p className="text-2xl font-bold text-blue-400">
            {Math.round(stats.avg_processing_latency_ms)}
            <span className="text-sm font-normal text-gray-400 ml-1">ms</span>
          </p>
          <p className="text-xs text-gray-400 mt-0.5">Avg Vision API latency</p>
        </div>
      </div>

      {/* Bar chart */}
      {chartData.length > 0 ? (
        <div>
          <p className="text-xs text-gray-400 mb-2">Violations by type</p>
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="type"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6 }}
                labelStyle={{ color: '#e5e7eb' }}
                itemStyle={{ color: '#9ca3af' }}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {chartData.map((entry) => (
                  <Cell
                    key={entry.type}
                    fill={BAR_COLOURS[entry.type] ?? DEFAULT_BAR_COLOUR}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="text-xs text-gray-500 text-center py-4">No violations today.</p>
      )}
    </div>
  )
}
