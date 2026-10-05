/**
 * TypeScript interfaces mirroring the FastAPI Pydantic schemas.
 * All three extended research fields are explicitly typed.
 */

export interface BoundingBox {
  label: string
  confidence: number
  x_min: number
  y_min: number
  x_max: number
  y_max: number
}

/** Full violation detail — returned by GET /violations/{id} */
export interface ViolationEvent {
  event_id: string
  camera_id: string
  timestamp: string          // ISO 8601
  violation_types: string[]
  snapshot_url: string | null
  confidence_scores: Record<string, number>
  upload_status: string
  // Extended research fields
  bounding_boxes: BoundingBox[]
  processing_latency: number  // milliseconds
  inference_metadata: Record<string, unknown>
  created_at: string
}

/** Compact summary — returned in paginated list */
export interface ViolationSummary {
  event_id: string
  camera_id: string
  timestamp: string
  violation_types: string[]
  snapshot_url: string | null
  upload_status: string
  bounding_boxes: BoundingBox[]
  processing_latency: number
}

export interface ViolationListResponse {
  items: ViolationSummary[]
  total: number
  limit: number
  offset: number
}

export interface CameraStatus {
  camera_id: string
  status: 'online' | 'offline' | 'retrying'
}

export interface CameraListResponse {
  cameras: CameraStatus[]
}

export interface ViolationStats {
  total_violations: number
  by_type: Record<string, number>
  avg_processing_latency_ms: number
  cameras_with_violations: string[]
  start_time: string
  end_time: string
}

export interface ViolationFilters {
  camera_id?: string
  start_time?: string
  end_time?: string
  violation_type?: string
  limit?: number
  offset?: number
}

/** Typed error state returned instead of throwing */
export interface ApiError {
  message: string
  status?: number
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError }
