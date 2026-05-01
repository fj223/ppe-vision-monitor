/**
 * ManualInspection — drag-and-drop / click-to-upload image analysis card.
 * Calls POST /api/analyze-upload and renders the result inline.
 */

import React, { useCallback, useRef, useState } from 'react'
import { analyzeUpload } from '../api/client'
import type { UploadAnalysisResult } from '../api/client'
import type { BoundingBox } from '../api/types'

const LABEL_COLORS: Record<string, string> = {
  helmet: '#22c55e',
  vest: '#3b82f6',
  no_helmet: '#ef4444',
  no_vest: '#f97316',
}
function colorFor(label: string) {
  return LABEL_COLORS[label.toLowerCase()] ?? '#a855f7'
}

export default function ManualInspection() {
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<UploadAnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function runAnalysis(file: File) {
    setLoading(true)
    setResult(null)
    setError(null)
    const res = await analyzeUpload(file)
    if (res.ok) {
      setResult(res.data)
    } else {
      setError(res.error.message)
    }
    setLoading(false)
  }

  const onFile = useCallback((file: File | undefined) => {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('请上传图片文件（JPG / PNG / WebP）')
      return
    }
    runAnalysis(file)
  }, [])

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    onFile(e.target.files?.[0])
    e.target.value = ''
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    onFile(e.dataTransfer.files?.[0])
  }

  return (
    <div className="space-y-3">
      {/* Drop zone */}
      <div
        className={`relative border-2 border-dashed rounded-lg p-4 text-center cursor-pointer transition-colors
          ${dragging ? 'border-blue-400 bg-blue-900/20' : 'border-gray-600 hover:border-gray-400'}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={onInputChange}
        />
        {loading ? (
          <p className="text-sm text-blue-400 animate-pulse">检测中…</p>
        ) : (
          <>
            <p className="text-2xl mb-1">📷</p>
            <p className="text-xs text-gray-400">点击或拖拽图片到此处</p>
          </>
        )}
      </div>

      {/* Error */}
      {error && (
        <p className="text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
      )}

      {/* Result */}
      {result && <InspectionResult result={result} />}
    </div>
  )
}

function InspectionResult({ result }: { result: UploadAnalysisResult }) {
  return (
    <div className="space-y-2">
      {/* Status badge */}
      <div className={`text-xs font-semibold px-2 py-1 rounded inline-block
        ${result.is_violation ? 'bg-red-900/50 text-red-300' : 'bg-green-900/50 text-green-300'}`}>
        {result.is_violation ? `⚠ 违规：${result.violation_types.join(', ')}` : '✓ 合规'}
      </div>

      {/* Annotated image */}
      <AnnotatedImage
        base64={result.image_base64}
        boxes={result.bounding_boxes}
      />

      {/* Detected labels */}
      {result.detected_ppe.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {result.detected_ppe.map((label) => (
            <span
              key={label}
              className="text-xs px-2 py-0.5 rounded font-mono"
              style={{ background: colorFor(label) + '33', color: colorFor(label) }}
            >
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function AnnotatedImage({ base64, boxes }: { base64: string; boxes: BoundingBox[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)

  function onLoad(e: React.SyntheticEvent<HTMLImageElement>) {
    const img = e.currentTarget
    setDims({ w: img.naturalWidth, h: img.naturalHeight })
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    canvas.width = img.naturalWidth
    canvas.height = img.naturalHeight
    ctx.drawImage(img, 0, 0)
    for (const box of boxes) {
      const color = colorFor(box.label)
      ctx.strokeStyle = color
      ctx.lineWidth = Math.max(2, img.naturalWidth / 300)
      ctx.strokeRect(box.x_min, box.y_min, box.x_max - box.x_min, box.y_max - box.y_min)
      ctx.fillStyle = color
      const fontSize = Math.max(12, img.naturalWidth / 60)
      ctx.font = `bold ${fontSize}px sans-serif`
      const text = `${box.label} ${(box.confidence * 100).toFixed(0)}%`
      const tw = ctx.measureText(text).width
      ctx.fillRect(box.x_min, box.y_min - fontSize - 4, tw + 8, fontSize + 6)
      ctx.fillStyle = '#fff'
      ctx.fillText(text, box.x_min + 4, box.y_min - 4)
    }
  }

  return (
    <div className="relative rounded overflow-hidden bg-gray-900">
      {/* Hidden img used only to trigger onLoad for canvas drawing */}
      <img
        src={`data:image/jpeg;base64,${base64}`}
        alt="detection source"
        className="hidden"
        onLoad={onLoad}
      />
      <canvas
        ref={canvasRef}
        className="w-full h-auto rounded"
        style={{ display: dims ? 'block' : 'none' }}
      />
      {!dims && (
        <div className="h-24 flex items-center justify-center text-gray-500 text-xs">
          渲染中…
        </div>
      )}
    </div>
  )
}
