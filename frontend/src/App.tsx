/**
 * App — main dashboard layout.
 *
 * Layout (viewport-fit, no full-page scroll):
 *   Header  — title + camera status strip
 *   Body    — CSS Grid, two columns
 *     Left (60%)  — LIVE ALERTS (internal scroll)
 *     Right (40%) — TODAY'S STATS / MANUAL INSPECTION / HISTORY (stacked, each scrollable)
 *
 * (Requirements 6.1, 6.2, 6.4, 6.5, 6.6)
 */

import React, { useState } from 'react'
import CameraStatusPanel from './components/CameraStatusPanel'
import HistoryFilter from './components/HistoryFilter'
import ManualInspection from './components/ManualInspection'
import SnapshotViewer from './components/SnapshotViewer'
import StatsChart from './components/StatsChart'
import ViolationList from './components/ViolationList'
import LatencyBadge from './components/LatencyBadge'
import { fetchViolationById } from './api/client'
import type { ViolationEvent, ViolationFilters } from './api/types'

export default function App() {
  const [availableCameras, setAvailableCameras] = useState<string[]>([])
  const [historyFilters, setHistoryFilters] = useState<ViolationFilters>({})
  const [selectedEvent, setSelectedEvent] = useState<ViolationEvent | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  async function openDetail(eventId: string) {
    setDetailLoading(true)
    const result = await fetchViolationById(eventId)
    if (result.ok) setSelectedEvent(result.data)
    setDetailLoading(false)
  }

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-gray-100 overflow-hidden">

      {/* ---------------------------------------------------------------- */}
      {/* Header                                                            */}
      {/* ---------------------------------------------------------------- */}
      <header className="flex-none bg-gray-800 border-b border-gray-700 px-6 py-3">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-lg font-bold tracking-tight">
            🦺 PPE Compliance Monitor
          </h1>
          <span className="text-xs text-gray-500">Live · auto-refresh 5 s</span>
        </div>
        <CameraStatusPanel onCamerasLoaded={setAvailableCameras} />
      </header>

      {/* ---------------------------------------------------------------- */}
      {/* Main — two-column grid, fills remaining viewport height           */}
      {/* ---------------------------------------------------------------- */}
      <main className="flex-1 min-h-0 grid grid-cols-5 gap-4 p-4">

        {/* ---- Left: Live Alerts (60%) ---------------------------------- */}
        <section className="col-span-3 flex flex-col min-h-0 bg-gray-800 rounded-xl border border-gray-700 p-4">
          <h2 className="flex-none text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Live Alerts
          </h2>
          <div className="flex-1 min-h-0 overflow-y-auto">
            <ViolationList onSelect={openDetail} />
          </div>
        </section>

        {/* ---- Right: stacked cards (40%) ------------------------------- */}
        <aside className="col-span-2 flex flex-col gap-4 min-h-0 overflow-y-auto">

          {/* Today's Stats */}
          <div className="flex-none bg-gray-800 rounded-xl border border-gray-700 p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Today's Stats
            </h2>
            <StatsChart />
          </div>

          {/* Manual Inspection */}
          <div className="flex-none bg-gray-800 rounded-xl border border-gray-700 p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Manual Inspection
            </h2>
            <ManualInspection />
          </div>

          {/* History */}
          <div className="flex-none bg-gray-800 rounded-xl border border-gray-700 p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              History
            </h2>
            <HistoryFilter
              cameras={availableCameras}
              filters={historyFilters}
              onChange={setHistoryFilters}
            />
            {Object.values(historyFilters).some(Boolean) && (
              <div className="mt-3 max-h-64 overflow-y-auto">
                <ViolationList filters={historyFilters} onSelect={openDetail} />
              </div>
            )}
          </div>

        </aside>
      </main>

      {/* ---------------------------------------------------------------- */}
      {/* Violation detail modal                                            */}
      {/* ---------------------------------------------------------------- */}
      {(selectedEvent || detailLoading) && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
          onClick={() => setSelectedEvent(null)}
        >
          <div
            className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-2xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {detailLoading ? (
              <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
                Loading detail…
              </div>
            ) : selectedEvent ? (
              <ViolationDetail event={selectedEvent} onClose={() => setSelectedEvent(null)} />
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------------------------------- //
// Violation detail modal content
// -------------------------------------------------------------------------- //

function ViolationDetail({
  event,
  onClose,
}: {
  event: ViolationEvent
  onClose: () => void
}) {
  const ts = new Date(event.timestamp).toLocaleString()

  return (
    <div className="p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-100">Violation Detail</h3>
          <p className="text-xs text-gray-400 font-mono mt-0.5">{event.event_id}</p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-200 text-xl leading-none"
          aria-label="Close"
        >
          ×
        </button>
      </div>

      {/* Snapshot with bounding box overlay */}
      <SnapshotViewer
        snapshotUrl={event.snapshot_url}
        boundingBoxes={event.bounding_boxes}
      />

      {/* Metadata grid */}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <MetaRow label="Camera" value={event.camera_id} />
        <MetaRow label="Time" value={ts} />
        <MetaRow
          label="Violations"
          value={event.violation_types.join(', ') || '—'}
        />
        <MetaRow label="Upload" value={event.upload_status} />
      </div>

      {/* Processing latency — verbose badge for research metrics */}
      <div>
        <p className="text-xs text-gray-400 mb-1">Vision API Performance</p>
        <LatencyBadge processingLatency={event.processing_latency} verbose />
      </div>

      {/* Confidence scores */}
      {Object.keys(event.confidence_scores).length > 0 && (
        <div>
          <p className="text-xs text-gray-400 mb-1">Confidence scores</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(event.confidence_scores).map(([label, score]) => (
              <span
                key={label}
                className="px-2 py-0.5 rounded text-xs font-mono bg-gray-700 text-gray-300"
              >
                {label}: {(score * 100).toFixed(1)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Raw API response — collapsible, for research / data replay */}
      <details className="group">
        <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-200 select-none">
          Raw API response (click to expand)
        </summary>
        <pre className="mt-2 text-xs bg-gray-900 rounded p-3 overflow-x-auto text-gray-400 max-h-48">
          {JSON.stringify(event.raw_api_response, null, 2)}
        </pre>
      </details>
    </div>
  )
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-sm text-gray-200 font-mono truncate">{value}</p>
    </div>
  )
}
