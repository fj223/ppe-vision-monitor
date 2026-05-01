/**
 * CameraStatusPanel
 *
 * Polls GET /api/v1/cameras every 5 seconds and renders each camera as a
 * status card with a colour-coded indicator dot.
 *   green  — online
 *   yellow — retrying
 *   red    — offline
 * (Requirement 6.5)
 */

import React, { useEffect, useRef, useState } from 'react'
import { fetchCameras } from '../api/client'
import type { CameraStatus } from '../api/types'

const POLL_INTERVAL_MS = 5_000

const STATUS_STYLES: Record<string, { dot: string; label: string; card: string }> = {
  online:   { dot: 'bg-green-400',  label: 'Online',   card: 'border-green-700/50' },
  retrying: { dot: 'bg-yellow-400 animate-pulse', label: 'Retrying', card: 'border-yellow-700/50' },
  offline:  { dot: 'bg-red-500',    label: 'Offline',  card: 'border-red-700/50' },
}

interface Props {
  /** Called with the current list of camera IDs so parent can populate filters */
  onCamerasLoaded?: (cameraIds: string[]) => void
}

export default function CameraStatusPanel({ onCamerasLoaded }: Props) {
  const [cameras, setCameras] = useState<CameraStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function load() {
    const result = await fetchCameras()
    if (result.ok) {
      setCameras(result.data.cameras)
      setError(null)
      onCamerasLoaded?.(result.data.cameras.map((c) => c.camera_id))
    } else {
      setError(result.error.message)
    }
  }

  useEffect(() => {
    load()
    timerRef.current = setInterval(load, POLL_INTERVAL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (error) {
    return (
      <div className="rounded-lg bg-red-900/30 border border-red-700 px-3 py-2 text-red-400 text-xs">
        ⚠ Camera status unavailable: {error}
      </div>
    )
  }

  if (cameras.length === 0) {
    return (
      <div className="text-gray-500 text-xs">No cameras configured.</div>
    )
  }

  return (
    <div className="flex flex-wrap gap-2">
      {cameras.map((cam) => {
        const style = STATUS_STYLES[cam.status] ?? STATUS_STYLES.offline
        return (
          <div
            key={cam.camera_id}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-800 border ${style.card}`}
          >
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${style.dot}`} />
            <span className="text-xs font-mono text-gray-300">{cam.camera_id}</span>
            <span className="text-xs text-gray-500">{style.label}</span>
          </div>
        )
      })}
    </div>
  )
}
