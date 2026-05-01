/**
 * SnapshotViewer
 *
 * Renders a violation snapshot image with a <canvas> overlay that draws
 * each bounding box as a labelled rectangle. The canvas is sized to match
 * the rendered image on every load/resize so coordinates map accurately —
 * critical for academic paper visual proofs.
 *
 * Coordinate mapping:
 *   The API returns pixel coordinates relative to the original image
 *   dimensions. We scale them by (renderedWidth / naturalWidth) so the
 *   boxes stay accurate regardless of how the browser scales the image.
 *
 * (Requirements 6.3, 4.3, 4.8)
 */

import React, { useCallback, useEffect, useRef } from 'react'
import type { BoundingBox } from '../api/types'

// One colour per label — cycles through the palette for unknown labels
const LABEL_COLOURS: Record<string, string> = {
  no_helmet: '#ef4444',   // red-500
  no_vest:   '#f97316',   // orange-500
  helmet:    '#22c55e',   // green-500
  vest:      '#22c55e',
  person:    '#3b82f6',   // blue-500
}
const FALLBACK_COLOUR = '#a855f7' // purple-500

const FONT_SIZE = 13
const LINE_WIDTH = 2
const LABEL_PADDING = 3

interface Props {
  snapshotUrl: string | null
  boundingBoxes: BoundingBox[]
  /** Optional CSS class for the outer wrapper */
  className?: string
}

export default function SnapshotViewer({ snapshotUrl, boundingBoxes, className = '' }: Props) {
  const imgRef = useRef<HTMLImageElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const drawBoxes = useCallback(() => {
    const img = imgRef.current
    const canvas = canvasRef.current
    if (!img || !canvas || !img.naturalWidth) return

    // Match canvas pixel dimensions to the rendered image size
    const rect = img.getBoundingClientRect()
    canvas.width = rect.width
    canvas.height = rect.height

    const scaleX = rect.width / img.naturalWidth
    const scaleY = rect.height / img.naturalHeight

    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    for (const bb of boundingBoxes) {
      const x = bb.x_min * scaleX
      const y = bb.y_min * scaleY
      const w = (bb.x_max - bb.x_min) * scaleX
      const h = (bb.y_max - bb.y_min) * scaleY

      const colour = LABEL_COLOURS[bb.label] ?? FALLBACK_COLOUR

      // Box outline
      ctx.strokeStyle = colour
      ctx.lineWidth = LINE_WIDTH
      ctx.strokeRect(x, y, w, h)

      // Semi-transparent fill
      ctx.fillStyle = colour + '22' // ~13% opacity
      ctx.fillRect(x, y, w, h)

      // Label background + text
      const label = `${bb.label} ${(bb.confidence * 100).toFixed(0)}%`
      ctx.font = `bold ${FONT_SIZE}px monospace`
      const textWidth = ctx.measureText(label).width
      const labelH = FONT_SIZE + LABEL_PADDING * 2

      // Place label above the box; clamp to canvas top
      const labelY = y - labelH < 0 ? y : y - labelH

      ctx.fillStyle = colour
      ctx.fillRect(x, labelY, textWidth + LABEL_PADDING * 2, labelH)

      ctx.fillStyle = '#ffffff'
      ctx.fillText(label, x + LABEL_PADDING, labelY + FONT_SIZE)
    }
  }, [boundingBoxes])

  // Redraw whenever the image loads or bounding boxes change
  useEffect(() => {
    const img = imgRef.current
    if (!img) return
    if (img.complete && img.naturalWidth) {
      drawBoxes()
    } else {
      img.addEventListener('load', drawBoxes)
      return () => img.removeEventListener('load', drawBoxes)
    }
  }, [drawBoxes, snapshotUrl])

  // Redraw on window resize so scaling stays accurate
  useEffect(() => {
    window.addEventListener('resize', drawBoxes)
    return () => window.removeEventListener('resize', drawBoxes)
  }, [drawBoxes])

  if (!snapshotUrl) {
    return (
      <div className={`flex items-center justify-center bg-gray-800 rounded text-gray-500 text-sm h-40 ${className}`}>
        No snapshot available
      </div>
    )
  }

  return (
    <div className={`relative inline-block w-full ${className}`}>
      <img
        ref={imgRef}
        src={snapshotUrl}
        alt="Violation snapshot"
        className="w-full rounded block"
        crossOrigin="anonymous"
      />
      {/* Canvas sits exactly on top of the image */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full pointer-events-none"
        aria-label={`Bounding box overlay — ${boundingBoxes.length} object(s) detected`}
      />
    </div>
  )
}
