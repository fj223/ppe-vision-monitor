/**
 * HistoryFilter
 *
 * Controlled filter bar for historical violation queries.
 * Emits a ViolationFilters object on every change so the parent can
 * pass it down to ViolationList.
 * (Requirement 6.4)
 */

import React from 'react'
import type { ViolationFilters } from '../api/types'

interface Props {
  cameras: string[]           // available camera IDs for the select
  filters: ViolationFilters
  onChange: (filters: ViolationFilters) => void
}

export default function HistoryFilter({ cameras, filters, onChange }: Props) {
  function update(patch: Partial<ViolationFilters>) {
    onChange({ ...filters, ...patch })
  }

  return (
    <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">Filter History</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">

        {/* Camera select */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Camera</label>
          <select
            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            value={filters.camera_id ?? ''}
            onChange={(e) => update({ camera_id: e.target.value || undefined })}
          >
            <option value="">All cameras</option>
            {cameras.map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
        </div>

        {/* Start time */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">From</label>
          <input
            type="datetime-local"
            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            value={filters.start_time ? toLocalInput(filters.start_time) : ''}
            onChange={(e) =>
              update({ start_time: e.target.value ? toIso(e.target.value) : undefined })
            }
          />
        </div>

        {/* End time */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">To</label>
          <input
            type="datetime-local"
            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            value={filters.end_time ? toLocalInput(filters.end_time) : ''}
            onChange={(e) =>
              update({ end_time: e.target.value ? toIso(e.target.value) : undefined })
            }
          />
        </div>

        {/* Violation type */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">Violation type</label>
          <select
            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1.5 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            value={filters.violation_type ?? ''}
            onChange={(e) => update({ violation_type: e.target.value || undefined })}
          >
            <option value="">All types</option>
            <option value="helmet">No helmet</option>
            <option value="vest">No vest</option>
          </select>
        </div>
      </div>

      {/* Clear button */}
      {(filters.camera_id || filters.start_time || filters.end_time || filters.violation_type) && (
        <button
          className="mt-3 text-xs text-gray-400 hover:text-gray-200 underline"
          onClick={() => onChange({})}
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

// datetime-local input expects "YYYY-MM-DDTHH:mm" in local time
function toLocalInput(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function toIso(localInput: string): string {
  return new Date(localInput).toISOString()
}
