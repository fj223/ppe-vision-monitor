# 技术设计文档：PPE 合规性监控系统

## 概述

本文档描述工厂 PPE（个人防护装备）合规性自动化监控系统的技术设计。系统通过 RTSP 视频流实时采集工厂摄像头画面，调用 Yandex Vision API 进行 PPE 合规性分析，将违规快照持久化至 Yandex Object Storage，并通过 FastAPI 后端向 React 仪表板提供实时告警与历史查询能力。

系统的核心设计目标：
- **实时性**：端到端延迟控制在 10 秒以内（帧提取间隔 2 秒 + API 调用 ≤5 秒 + 写入 ≤1 秒）
- **可观测性**：记录 `processing_latency`、`bounding_boxes`、`raw_api_response` 三个扩展字段，支持性能统计与离线模型分析
- **可靠性**：上传失败自动重试，数据库写入失败不静默丢弃，RTSP 断线自动重连
- **模块化**：四个核心模块（Video_Processor、Vision_Analyzer、Violation_Recorder、Event_Repository）通过明确接口解耦

---

## 架构

### 模块划分与交互关系

```mermaid
graph TD
    CAM["📷 RTSP 摄像头"] -->|视频流| VP["Video_Processor\n(OpenCV + asyncio)"]
    VP -->|帧图像 bytes| VA["Vision_Analyzer\n(Yandex Vision API)"]
    VA -->|AnalysisResult| VR["Violation_Recorder\n(boto3 + S3)"]
    VR -->|ViolationEvent| ER["Event_Repository\n(asyncpg + PostgreSQL)"]
    ER -->|查询结果| API["API_Server\n(FastAPI)"]
    API -->|REST JSON| DASH["Dashboard\n(React + Tailwind)"]

    subgraph 后端服务
        VP
        VA
        VR
        ER
        API
    end

    subgraph Yandex Cloud
        YV["Yandex Vision API"]
        YOS["Yandex Object Storage"]
        PG["PostgreSQL"]
    end

    VA -->|HTTP POST| YV
    VR -->|boto3 S3| YOS
    ER -->|asyncpg| PG
```

### 部署架构

```mermaid
graph LR
    subgraph docker-compose
        direction TB
        SVC["backend\n(FastAPI + Worker)\n:8000"]
        DB["postgres\n:5432"]
        SVC -->|asyncpg| DB
    end
    DASH["前端\n(React Dev/Nginx)\n:3000"] -->|HTTP| SVC
    SVC -->|HTTPS| YV2["Yandex Vision API"]
    SVC -->|HTTPS S3| YOS2["Yandex Object Storage"]
```

后端服务与视频处理 Worker 合并在同一容器中，通过 asyncio 任务并发运行，避免引入消息队列的额外复杂度。

---

## 组件与接口

### 模块目录结构

```
backend/
├── main.py                  # FastAPI 应用入口
├── config.py                # 环境变量加载（pydantic-settings）
├── modules/
│   ├── video_processor.py   # Video_Processor
│   ├── vision_analyzer.py   # Vision_Analyzer
│   ├── violation_recorder.py # Violation_Recorder
│   └── event_repository.py  # Event_Repository
├── api/
│   ├── routes/
│   │   ├── violations.py
│   │   ├── cameras.py
│   │   └── stats.py
│   └── schemas.py           # Pydantic 请求/响应模型
└── db/
    └── migrations/          # SQL 迁移脚本
```

### Video_Processor 接口

```python
class VideoProcessor:
    async def start(self, camera_id: str, rtsp_url: str) -> None:
        """启动指定摄像头的帧提取循环（asyncio Task）"""

    async def stop(self, camera_id: str) -> None:
        """停止指定摄像头的帧提取任务"""

    def get_camera_status(self, camera_id: str) -> CameraStatus:
        """返回摄像头当前状态（online/offline/retrying）"""
```

帧提取循环每 2 秒截取一帧，失败时以 10 秒间隔重试，超过 5 次触发告警并停止。每路摄像头运行独立的 asyncio Task，互不干扰。

### Vision_Analyzer 接口

```python
@dataclass
class AnalysisResult:
    is_violation: bool
    violation_types: list[str]       # 缺失的 PPE 类别
    detected_ppe: list[str]          # 检测到的 PPE 类别
    confidence_scores: dict[str, float]
    bounding_boxes: list[BoundingBox] # 违规对象边界框列表
    processing_latency_ms: int        # Vision API 调用耗时（毫秒）
    raw_api_response: dict            # Vision API 完整原始响应

class VisionAnalyzer:
    async def analyze(self, frame: bytes, camera_id: str) -> AnalysisResult | None:
        """分析帧图像，返回合规性结果；API 失败时返回 None"""
```

`processing_latency_ms` 在调用 Vision API 前后通过 `time.monotonic()` 计算，精度为毫秒。`raw_api_response` 存储 API 返回的完整 JSON 字典，不做任何裁剪。

### Violation_Recorder 接口

```python
@dataclass
class ViolationEvent:
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    confidence_scores: dict[str, float]
    bounding_boxes: list[BoundingBox]
    processing_latency_ms: int
    raw_api_response: dict
    snapshot_url: str | None = None   # 上传成功后填充

class ViolationRecorder:
    async def record(self, frame: bytes, result: AnalysisResult, camera_id: str) -> ViolationEvent:
        """上传快照并构造 ViolationEvent，上传失败时标记 pending_retry"""
```

### Event_Repository 接口

```python
class EventRepository:
    async def insert_violation(self, event: ViolationEvent) -> str:
        """插入违规事件记录，返回生成的 event_id（UUID）"""

    async def query_violations(
        self,
        camera_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        violation_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ViolationEventRecord]:
        """按条件查询违规事件列表"""

    async def get_violation_by_id(self, event_id: str) -> ViolationEventRecord | None:
        """查询单条违规事件详情，包含所有扩展字段"""

    async def get_stats(self, start_time: datetime, end_time: datetime) -> ViolationStats:
        """返回指定时间范围内的违规统计汇总"""
```

---

## 数据模型

### 数据库 Schema

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE violation_events (
    -- 核心字段
    event_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id           VARCHAR(64)  NOT NULL,
    timestamp           TIMESTAMPTZ  NOT NULL,
    violation_types     TEXT[]       NOT NULL,
    snapshot_url        TEXT,
    confidence_scores   JSONB        NOT NULL DEFAULT '{}',

    -- 扩展字段（需求 4.3）
    bounding_boxes      JSONB        NOT NULL DEFAULT '[]',
    processing_latency  INTEGER      NOT NULL,   -- 单位：毫秒
    raw_api_response    JSONB        NOT NULL DEFAULT '{}',

    -- 元数据
    upload_status       VARCHAR(16)  NOT NULL DEFAULT 'success',  -- success | pending_retry | failed
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- 查询性能索引（需求 4.7）
CREATE INDEX idx_violations_camera_id  ON violation_events (camera_id);
CREATE INDEX idx_violations_timestamp  ON violation_events (timestamp DESC);
CREATE INDEX idx_violations_types      ON violation_events USING GIN (violation_types);
```

`bounding_boxes` 字段存储格式示例：

```json
[
  {
    "label": "no_helmet",
    "confidence": 0.94,
    "x_min": 120,
    "y_min": 45,
    "x_max": 280,
    "y_max": 210
  }
]
```

`raw_api_response` 字段存储 Yandex Vision API 返回的完整 JSON，结构示例：

```json
{
  "results": [
    {
      "results": [
        {
          "classificationResult": {
            "properties": [
              {"name": "helmet", "probability": 0.94},
              {"name": "vest", "probability": 0.12}
            ]
          }
        }
      ]
    }
  ]
}
```

### Pydantic 响应模型

```python
class BoundingBox(BaseModel):
    label: str
    confidence: float
    x_min: int
    y_min: int
    x_max: int
    y_max: int

class ViolationEventResponse(BaseModel):
    event_id: str
    camera_id: str
    timestamp: datetime
    violation_types: list[str]
    snapshot_url: str | None
    confidence_scores: dict[str, float]
    bounding_boxes: list[BoundingBox]        # 需求 4.3 / 4.8
    processing_latency: int                  # 需求 4.3 / 4.8
    raw_api_response: dict                   # 需求 4.3 / 4.8
    upload_status: str
```

---

## 数据流设计

### 三个扩展字段的完整流转路径

以下描述从 Vision API 调用到前端响应的完整数据流，重点标注三个扩展字段的采集与传递节点：

```
Vision_Analyzer.analyze(frame)
│
├─ [采集] t0 = time.monotonic()
├─ POST https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze
├─ [采集] processing_latency_ms = int((time.monotonic() - t0) * 1000)
├─ [采集] raw_api_response = response.json()  ← 完整原始响应
├─ 解析 bounding_boxes ← 从 raw_api_response 中提取坐标
│
└─ 返回 AnalysisResult {
       is_violation, violation_types, confidence_scores,
       bounding_boxes,          ← 传递给 Violation_Recorder
       processing_latency_ms,   ← 传递给 Violation_Recorder
       raw_api_response         ← 传递给 Violation_Recorder
   }

Violation_Recorder.record(frame, result, camera_id)
│
├─ 上传快照至 Yandex Object Storage
│
└─ 构造 ViolationEvent {
       ...,
       bounding_boxes=result.bounding_boxes,
       processing_latency_ms=result.processing_latency_ms,
       raw_api_response=result.raw_api_response
   }

Event_Repository.insert_violation(event)
│
└─ INSERT INTO violation_events (
       ...,
       bounding_boxes=$1,        ← JSONB，序列化为 JSON 字符串
       processing_latency=$2,    ← INTEGER，毫秒
       raw_api_response=$3       ← JSONB，序列化为 JSON 字符串
   )

API_Server GET /api/v1/violations/{event_id}
│
└─ 响应 ViolationEventResponse {
       ...,
       bounding_boxes: [...],    ← 前端用于重绘检测框
       processing_latency: 342,  ← 前端用于性能统计展示
       raw_api_response: {...}   ← 前端/离线工具用于数据回溯
   }
```

### 完整处理时序

```mermaid
sequenceDiagram
    participant VP as Video_Processor
    participant VA as Vision_Analyzer
    participant YV as Yandex Vision API
    participant VR as Violation_Recorder
    participant YOS as Yandex Object Storage
    participant ER as Event_Repository
    participant PG as PostgreSQL

    VP->>VA: analyze(frame_bytes, camera_id)
    VA->>YV: POST /vision/v1/batchAnalyze
    Note over VA,YV: 记录 processing_latency_ms
    YV-->>VA: raw_api_response (JSON)
    VA->>VA: 解析 bounding_boxes, violation_types
    VA-->>VP: AnalysisResult (含三个扩展字段)

    alt is_violation == True
        VP->>VR: record(frame, result, camera_id)
        VR->>YOS: PUT violations/{camera_id}/{date}/{ts}.jpg
        YOS-->>VR: snapshot_url
        VR-->>VP: ViolationEvent (含三个扩展字段)
        VP->>ER: insert_violation(event)
        ER->>PG: INSERT violation_events (含 bounding_boxes, processing_latency, raw_api_response)
        PG-->>ER: event_id
    end
```

---

## 正确性属性

*属性（Property）是在系统所有合法执行中都应成立的特征或行为——本质上是对系统应做什么的形式化陈述。属性是人类可读规范与机器可验证正确性保证之间的桥梁。*

### 属性 1：违规判断的完备性

*对任意* 缺少至少一项必需 PPE 类别（安全头盔或安全背心）的 Vision API 检测结果，`Vision_Analyzer` 的解析逻辑应将该结果标记为违规（`is_violation=True`），且 `violation_types` 列表应包含所有缺失的 PPE 类别名称。

**验证：需求 2.4**

### 属性 2：API 失败不产生误报

*对任意* Yandex Vision API 错误响应（网络异常、HTTP 4xx/5xx、格式错误的响应体），`Vision_Analyzer.analyze()` 应返回 `None`，不产生任何违规记录，且不抛出未捕获异常。

**验证：需求 2.5**

### 属性 3：存储路径格式正确性

*对任意* 合法的 `camera_id`（字母数字下划线组合）和 UTC 时间戳，`Violation_Recorder` 生成的 Yandex Object Storage 存储键应严格符合 `violations/{camera_id}/{YYYY-MM-DD}/{timestamp}.jpg` 格式，且返回的访问 URL 应包含该存储键。

**验证：需求 3.3、3.4**

### 属性 4：违规事件记录完整性

*对任意* 完整的 `ViolationEvent` 对象（包含所有核心字段与三个扩展字段），`Event_Repository.insert_violation()` 写入数据库后，通过 `get_violation_by_id()` 查询到的记录应包含所有字段，且 `bounding_boxes`、`processing_latency`、`raw_api_response` 的值与写入时完全一致（round-trip 属性）。

**验证：需求 4.1、4.2、4.3、4.8**

### 属性 5：查询过滤结果一致性

*对任意* 过滤条件组合（`camera_id`、`start_time`、`end_time`、`violation_type`），`Event_Repository.query_violations()` 返回的所有记录都应满足所有指定的过滤条件，不返回任何不符合条件的记录。

**验证：需求 4.6、5.2**

### 属性 6：API 参数验证覆盖性

*对任意* 不合法的请求参数（类型错误、超出范围、缺少必填字段），`API_Server` 应返回 HTTP 422 状态码，且响应体应包含结构化的错误描述，不返回 500 或空响应。

**验证：需求 5.6**

### 属性 7：上传重试次数上限

*对任意* 连续失败次数在 1 到 3 次之间的上传场景，`Violation_Recorder` 应在最终成功前恰好重试了失败次数对应的次数，且总重试次数不超过 3 次；若 3 次全部失败，事件应被标记为 `pending_retry` 而非丢弃。

**验证：需求 3.5、3.6**

---

## 错误处理

### 错误分类与处理策略

| 错误场景 | 处理模块 | 策略 |
|---|---|---|
| RTSP 连接失败 | Video_Processor | 10 秒后重试，超过 5 次触发告警并停止 |
| Vision API 超时（>5s） | Vision_Analyzer | 中止请求，记录超时日志，跳过本帧 |
| Vision API 返回错误 | Vision_Analyzer | 记录错误详情，返回 `None`，不产生违规记录 |
| Object Storage 上传失败 | Violation_Recorder | 最多重试 3 次（间隔 2 秒），失败后标记 `pending_retry` |
| 数据库写入失败 | Event_Repository | 记录错误日志，返回错误状态，不静默丢弃 |
| API 请求参数非法 | API_Server | 返回 HTTP 422 + 结构化错误描述（FastAPI 自动处理） |
| 未捕获内部异常 | API_Server | 返回 HTTP 500，记录完整堆栈，不暴露内部细节 |
| 必需环境变量缺失 | config.py | 启动时输出明确错误信息并拒绝启动 |

### 结构化日志格式

所有模块使用 Python `structlog` 或 `logging` 输出 JSON 格式日志，包含以下字段：

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "ERROR",
  "module": "vision_analyzer",
  "camera_id": "cam_01",
  "event": "api_call_failed",
  "error": "ConnectionTimeout",
  "processing_latency_ms": 5001
}
```

---

## 测试策略

### 双轨测试方法

本系统采用单元测试与属性测试相结合的方式，确保核心业务逻辑的正确性。

**属性测试库**：`hypothesis`（Python）

**属性测试配置**：每个属性测试最少运行 100 次迭代（`@settings(max_examples=100)`）。

**标注格式**：每个属性测试通过注释标注对应的设计属性：

```python
# Feature: ppe-compliance-monitoring, Property 1: 违规判断的完备性
@given(missing_ppe=st.lists(st.sampled_from(["helmet", "vest"]), min_size=1))
@settings(max_examples=100)
def test_violation_detection_completeness(missing_ppe):
    ...
```

### 各属性的测试实现思路

| 属性 | 测试方法 | 生成器策略 |
|---|---|---|
| 属性 1：违规判断完备性 | `hypothesis` | 生成随机 PPE 检测结果，确保至少缺少一项必需类别 |
| 属性 2：API 失败不误报 | `hypothesis` | 生成随机 HTTP 错误码、格式错误的 JSON 响应体 |
| 属性 3：存储路径格式 | `hypothesis` | 生成随机 camera_id 和时间戳，验证路径正则匹配 |
| 属性 4：记录完整性 | `hypothesis` | 生成随机 ViolationEvent，mock asyncpg，验证 round-trip |
| 属性 5：查询过滤一致性 | `hypothesis` | 生成随机事件集合和过滤条件，验证结果子集正确 |
| 属性 6：API 参数验证 | `hypothesis` | 生成随机非法参数，使用 FastAPI TestClient |
| 属性 7：重试次数上限 | `hypothesis` | 生成 1-3 次失败序列，mock boto3，验证重试计数 |

### 单元测试覆盖范围

- RTSP 重连逻辑（5 次失败触发告警）
- Vision API 超时处理（5 秒阈值）
- 上传失败标记 `pending_retry`
- 数据库写入失败返回错误状态
- API 内部异常返回 500 且不暴露细节
- 环境变量缺失时启动失败

### 集成测试

- 使用 `testcontainers-python` 启动真实 PostgreSQL 容器，验证 Schema 迁移和索引创建
- 使用 `moto` mock Yandex S3 兼容端点，验证 boto3 上传逻辑
- 端到端 API 测试使用 FastAPI `TestClient`

---

## 部署架构

### docker-compose.yml 结构

```yaml
version: "3.9"
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    command: uvicorn main:app --host 0.0.0.0 --port 8000

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ppe_monitoring
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./backend/db/migrations:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

### 环境变量清单（.env）

```
# 数据库
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/ppe_monitoring

# Yandex Object Storage（S3 兼容）
YOS_ENDPOINT_URL=https://storage.yandexcloud.net
YOS_ACCESS_KEY_ID=<key>
YOS_SECRET_ACCESS_KEY=<secret>
YOS_BUCKET_NAME=ppe-violations

# Yandex Vision API
YANDEX_VISION_API_KEY=<api_key>
YANDEX_VISION_FOLDER_ID=<folder_id>

# RTSP 流配置（逗号分隔）
RTSP_STREAMS=cam_01=rtsp://192.168.1.10/stream,cam_02=rtsp://192.168.1.11/stream

# 应用配置
FRAME_INTERVAL_SECONDS=2
VISION_API_TIMEOUT_SECONDS=5
MAX_RETRY_ATTEMPTS=5
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000
```

缺少任意必需环境变量时，`pydantic-settings` 在应用启动时抛出 `ValidationError` 并输出明确的字段名称，进程以非零状态码退出。
