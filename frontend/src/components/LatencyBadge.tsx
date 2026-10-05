/**
 * LatencyBadge
 *
 * Displays local YOLOv8 inference latency with colour coding:
 *   green  < 1 000 ms  — fast, within real-time budget
 *   yellow 1 000–3 000 ms  — acceptable but degraded
 *   red    > 3 000 ms  — slow, warrants investigation
 *
 * Used in ViolationList items and the violation detail view to surface
 * performance metrics for academic evaluation.
 * (Requirements 6.3, 4.3)
 */

import React from 'react'

interface Props {
  processingLatency: number   // milliseconds
  /** Show a longer label; default is compact badge */
  verbose?: boolean
}

function getColour(ms: number): { bg: string; text: string; ring: string; label: string } {
  if (ms < 1000) {
    return {
      bg: 'bg-green-900/40',
      text: 'text-green-400',
      ring: 'ring-green-500/50',
      label: 'Fast',
    }
  }
  if (ms <= 3000) {
    return {
      bg: 'bg-yellow-900/40',
      text: 'text-yellow-400',
      ring: 'ring-yellow-500/50',
      label: 'Slow',
    }
  }
  return {
    bg: 'bg-red-900/40',
    text: 'text-red-400',
    ring: 'ring-red-500/50',
    label: 'Critical',
  }
}

export default function LatencyBadge({ processingLatency, verbose = false }: Props) {
  const { bg, text, ring, label } = getColour(processingLatency)

  if (verbose) {
    return (
      <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ring-1 ${bg} ${ring}`}>
        <span className={`text-xs font-semibold uppercase tracking-wide ${text}`}>
          {label}
        </span>
        <span className={`text-sm font-mono font-bold ${text}`}>
          {processingLatency.toLocaleString()} ms
        </span>
        <span className="text-xs text-gray-500">YOLOv8 latency</span>
      </div>
    )
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-semibold ring-1 ${bg} ${text} ${ring}`}
      title={`YOLOv8 inference latency: ${processingLatency} ms`}
    >
      {processingLatency.toLocaleString()} ms
    </span>
  )
}
