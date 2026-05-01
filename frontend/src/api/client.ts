/**
 * Typed API client for the PPE Compliance Monitoring backend.
 *
 * All functions return ApiResult<T> — never throw.
 * The base URL is read from VITE_API_URL (defaults to '' so the Vite
 * dev-server proxy handles /api/* → http://localhost:8000).
 */

import type {
  ApiResult,
  CameraListResponse,
  ViolationEvent,
  ViolationFilters,
  ViolationListResponse,
  ViolationStats,
} from './types'

const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

async function request<T>(
  path: string,
  init?: RequestInit
): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      return { ok: false, error: { message: text || res.statusText, status: res.status } }
    }
    const data = (await res.json()) as T
    return { ok: true, data }
  } catch (err) {
    return {
      ok: false,
      error: { message: err instanceof Error ? err.message : 'Network error' },
    }
  }
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      q.set(k, String(v))
    }
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

// -------------------------------------------------------------------------- //
// Violations
// -------------------------------------------------------------------------- //

export async function fetchViolations(
  filters: ViolationFilters = {}
): Promise<ApiResult<ViolationListResponse>> {
  const query = buildQuery({
    camera_id: filters.camera_id,
    start_time: filters.start_time,
    end_time: filters.end_time,
    violation_type: filters.violation_type,
    limit: filters.limit ?? 50,
    offset: filters.offset ?? 0,
  })
  return request<ViolationListResponse>(`/api/v1/violations${query}`)
}

export async function fetchViolationById(
  eventId: string
): Promise<ApiResult<ViolationEvent>> {
  return request<ViolationEvent>(`/api/v1/violations/${eventId}`)
}

// -------------------------------------------------------------------------- //
// Cameras
// -------------------------------------------------------------------------- //

export async function fetchCameras(): Promise<ApiResult<CameraListResponse>> {
  return request<CameraListResponse>('/api/v1/cameras')
}

// -------------------------------------------------------------------------- //
// Manual upload analysis
// -------------------------------------------------------------------------- //

export interface UploadAnalysisResult {
  is_violation: boolean
  violation_types: string[]
  detected_ppe: string[]
  bounding_boxes: import('./types').BoundingBox[]
  image_base64: string
}

export async function analyzeUpload(
  file: File
): Promise<ApiResult<UploadAnalysisResult>> {
  try {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE_URL}/api/analyze-upload`, {
      method: 'POST',
      body: form,
    })
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      return { ok: false, error: { message: text || res.statusText, status: res.status } }
    }
    const data = (await res.json()) as UploadAnalysisResult
    return { ok: true, data }
  } catch (err) {
    return {
      ok: false,
      error: { message: err instanceof Error ? err.message : 'Network error' },
    }
  }
}

// -------------------------------------------------------------------------- //
// Stats
// -------------------------------------------------------------------------- //

export async function fetchStats(
  startTime?: string,
  endTime?: string
): Promise<ApiResult<ViolationStats>> {
  const query = buildQuery({ start_time: startTime, end_time: endTime })
  return request<ViolationStats>(`/api/v1/stats${query}`)
}
