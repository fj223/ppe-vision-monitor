/**
 * ViolationList
 *
 * Polls GET /api/v1/violations every 5 seconds and renders the latest
 * violations newest-first. Each item shows:
 *   - Camera ID, timestamp, violation types
 *   - Snapshot thumbnail with bounding box overlay (SnapshotViewer)
 *   - Processing latency badge (LatencyBadge)
 *
 * On API failure shows a friendly error banner — never a blank page.
 * (Requirements 6.2, 6.3, 6.7)
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { fetchViolations } from '../api/client'
import type { ViolationFilters, ViolationSummary } from '../api/types'
import LatencyBadge from './LatencyBadge'
import SnapshotViewer from './SnapshotViewer'

const POLL_INTERVAL_MS = 5_000

interface Props {
  filters?: ViolationFilters
  /** Called when the user clicks a violation row to open detail */
  onSelect?: (eventId: string) => void
}

export default function ViolationList({ filters = {}, onSelect }: Props) {
  const [items, setItems] = useState<ViolationSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    const result = await fetchViolations({ ...filters, limit: 50, offset: 0 })
    if (result.ok) {
      setItems(result.data.items)
      setError(null)
    } else {
      setError(result.error.message || 'Failed to load violations.')
    }
    setLoading(false)
  }, [JSON.stringify(filters)]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setLoading(true)
    load()
    timerRef.current = setInterval(load, POLL_INTERVAL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [load])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-400 text-sm">
        Loading violations…
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-900/30 border border-red-700 px-4 py-3 text-red-400 text-sm">
        ⚠ Unable to load violations: {error}
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        No violations detected yet.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <ViolationCard key={item.event_id} item={item} onSelect={onSelect} />
      ))}
    </div>
  )
}

// -------------------------------------------------------------------------- //
// Individual card
// -------------------------------------------------------------------------- //

interface CardProps {
  item: ViolationSummary
  onSelect?: (eventId: string) => void
}

function ViolationCard({ item, onSelect }: CardProps) {
  const ts = new Date(item.timestamp).toLocaleString()

  return (
    <div
      className={`bg-gray-800 rounded-lg border border-gray-700 overflow-hidden
        ${onSelect ? 'cursor-pointer hover:border-red-500 transition-colors' : ''}`}
      onClick={() => onSelect?.(item.event_id)}
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      onKeyDown={(e) => e.key === 'Enter' && onSelect?.(item.event_id)}
    >
      <div className="flex gap-3 p-3">
        {/* Snapshot thumbnail with bounding box overlay */}
        <div className="w-32 flex-shrink-0">
          <SnapshotViewer
            snapshotUrl={item.snapshot_url}
            boundingBoxes={item.bounding_boxes}
          />
        </div>

        {/* Metadata */}
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-xs font-mono text-gray-400">{item.camera_id}</span>
            <LatencyBadge processingLatency={item.processing_latency} />
          </div>

          <p className="text-xs text-gray-500">{ts}</p>

          <div className="flex flex-wrap gap-1">
            {item.violation_types.map((vt) => (
              <span
                key={vt}
                className="px-2 py-0.5 rounded-full text-xs font-semibold bg-red-900/50 text-red-300 ring-1 ring-red-700"
              >
                {vt}
              </span>
            ))}
          </div>

          {item.upload_status !== 'success' && (
            <span className="text-xs text-yellow-500">⚠ Upload pending retry</span>
          )}
        </div>
      </div>
    </div>
  )
}
