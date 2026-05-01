# 需求文档

## 简介

本系统是一套用于工厂环境的生产级个人防护装备（PPE）合规性自动化监控系统。系统通过 RTSP 视频流实时采集工厂监控摄像头画面，利用 Yandex Vision API 对每帧图像进行 PPE 合规性分析（识别头盔、安全背心等装备的佩戴情况），在检测到违规行为时自动将快照上传至 Yandex Object Storage 并在 PostgreSQL 数据库中记录事件元数据，同时通过 React 实时仪表板向管理人员展示告警信息与历史违规数据。

---

## 术语表

- **PPE（个人防护装备）**：工厂环境中要求工人佩戴的安全装备，包括安全头盔、安全背心、护目镜等。
- **Video_Processor**：负责连接 RTSP 视频流并按固定间隔截取帧图像的模块。
- **Vision_Analyzer**：负责调用 Yandex Vision API 对图像进行 PPE 合规性分析的模块。
- **Violation_Recorder**：负责在检测到违规时将快照上传至 Yandex Object Storage 并向数据库写入事件记录的模块。
- **Event_Repository**：负责与 PostgreSQL 数据库交互、读写违规事件元数据的模块。
- **API_Server**：基于 FastAPI 构建的后端服务，向前端仪表板提供 REST API 接口。
- **Dashboard**：基于 React + Tailwind CSS 构建的前端实时监控仪表板。
- **RTSP 流**：来自工厂监控摄像头的实时视频流，使用 RTSP 协议传输。
- **违规事件**：一次被检测到的 PPE 不合规行为，包含时间戳、摄像头编号、违规类型及快照图像链接。
- **快照**：在检测到违规时从视频帧中截取并保存的静态图像。
- **Yandex Object Storage**：兼容 S3 协议的对象存储服务，用于持久化保存违规快照图像。
- **Yandex Vision API**：提供图像对象检测与分类能力的云端 AI 服务。
- **Bounding_Boxes（边界框坐标）**：Yandex Vision API 返回的违规对象在图像中的像素坐标区域，用于前端重绘检测框及离线模型准确度分析。
- **Processing_Latency（处理延迟）**：单次调用 Yandex Vision API 所消耗的时间，单位为毫秒，用于系统实时性能统计评估。
- **Raw_API_Response（原始响应）**：Yandex Vision API 返回的完整 JSON 格式原始数据，用于数据回溯和离线实验。

---

## 需求列表

### 需求 1：视频流采集与帧提取

**用户故事：** 作为安全管理员，我希望系统能持续从工厂摄像头的视频流中自动采集图像帧，以便对现场 PPE 佩戴情况进行实时监控。

#### 验收标准

1. THE Video_Processor SHALL 通过 OpenCV 连接指定的 RTSP 视频流地址。
2. WHEN RTSP 视频流连接成功，THE Video_Processor SHALL 每 2 秒截取一帧图像。
3. WHEN RTSP 视频流连接失败，THE Video_Processor SHALL 记录错误日志并在 10 秒后自动重试连接。
4. WHILE 视频流处于连接状态，THE Video_Processor SHALL 持续运行帧提取循环，不得中断。
5. IF 连续重试次数超过 5 次仍无法连接，THEN THE Video_Processor SHALL 触发告警通知并停止重试，等待人工干预。
6. THE Video_Processor SHALL 支持同时管理多路 RTSP 视频流，每路流独立运行帧提取任务。

---

### 需求 2：PPE 合规性图像分析

**用户故事：** 作为安全管理员，我希望系统能自动分析每帧图像中工人的 PPE 佩戴情况，以便及时发现不合规行为。

#### 验收标准

1. WHEN Video_Processor 提取到一帧图像，THE Vision_Analyzer SHALL 将该图像发送至 Yandex Vision API 进行对象检测与分类。
2. THE Vision_Analyzer SHALL 识别图像中以下 PPE 类别：安全头盔、安全背心。
3. WHEN Yandex Vision API 返回检测结果，THE Vision_Analyzer SHALL 将结果解析为结构化的合规性状态对象，包含检测到的 PPE 类别列表及置信度分数。
4. WHEN 检测结果中缺少任意一项必需 PPE 类别，THE Vision_Analyzer SHALL 将本次分析结果标记为"违规"。
5. IF Yandex Vision API 调用失败或返回错误响应，THEN THE Vision_Analyzer SHALL 记录错误详情并跳过本帧，不产生误报违规记录。
6. IF Yandex Vision API 调用超时（超过 5 秒），THEN THE Vision_Analyzer SHALL 中止本次请求并记录超时日志。
7. THE Vision_Analyzer SHALL 使用 requests 库或 Yandex SDK 调用 Vision API，并通过配置项指定所使用的客户端类型。

---

### 需求 3：违规快照存储

**用户故事：** 作为安全管理员，我希望系统能将每次违规事件的图像快照持久化保存，以便事后审查与取证。

#### 验收标准

1. WHEN Vision_Analyzer 将分析结果标记为"违规"，THE Violation_Recorder SHALL 将对应帧图像以 JPEG 格式上传至 Yandex Object Storage。
2. THE Violation_Recorder SHALL 使用 boto3 库并配置 Yandex S3 兼容端点进行存储操作。
3. THE Violation_Recorder SHALL 按照 `violations/{camera_id}/{YYYY-MM-DD}/{timestamp}.jpg` 的路径规则命名并存储快照文件。
4. WHEN 快照上传成功，THE Violation_Recorder SHALL 返回该快照在 Yandex Object Storage 中的访问 URL。
5. IF 快照上传失败，THEN THE Violation_Recorder SHALL 记录错误日志，并将上传失败的事件标记为待重试状态，不丢弃违规记录。
6. THE Violation_Recorder SHALL 对上传操作进行最多 3 次自动重试，每次重试间隔 2 秒。

---

### 需求 4：违规事件元数据记录

**用户故事：** 作为安全管理员，我希望系统能将每次违规事件的详细信息记录到数据库中，以便进行历史查询、统计分析及 AI 模型准确率评估。

#### 验收标准

1. WHEN Violation_Recorder 完成快照上传，THE Event_Repository SHALL 在 PostgreSQL 数据库中插入一条违规事件记录。
2. THE Event_Repository SHALL 在每条违规事件记录中存储以下核心字段：事件唯一标识符（UUID）、摄像头编号、违规发生时间戳（UTC）、违规类型列表、快照存储 URL、Vision API 置信度分数。
3. THE Event_Repository SHALL 在每条违规事件记录中额外存储以下扩展字段，以支持系统性能评估与 AI 准确率分析：
   - **Bounding_Boxes**：以 JSONB 格式存储 Yandex Vision API 返回的违规对象边界框坐标（包含 `x_min`、`y_min`、`x_max`、`y_max` 像素坐标），用于前端在快照上重绘检测框及离线模型准确度分析。
   - **Processing_Latency**：以整数类型（毫秒）记录单次调用 Yandex Vision API 所消耗的时间，用于系统实时性能的统计评估。
   - **Raw_API_Response**：以 JSONB 格式存储 Yandex Vision API 返回的完整原始响应数据，用于后续数据回溯和离线实验。
4. THE Event_Repository SHALL 使用参数化查询执行所有数据库写入操作，以防止 SQL 注入。
5. IF 数据库写入操作失败，THEN THE Event_Repository SHALL 记录错误日志并返回错误状态，不静默丢弃数据。
6. THE Event_Repository SHALL 支持按摄像头编号、时间范围、违规类型对历史事件进行查询过滤。
7. THE Event_Repository SHALL 为 `camera_id`、`timestamp`、`violation_types` 字段建立数据库索引，以保证查询性能。
8. WHEN 查询违规事件详情，THE Event_Repository SHALL 在响应中包含 `bounding_boxes`、`processing_latency` 及 `raw_api_response` 字段，以支持前端检测框渲染与性能分析。

---

### 需求 5：后端 REST API 服务

**用户故事：** 作为前端开发者，我希望后端提供标准的 REST API 接口，以便仪表板能够获取实时告警和历史违规数据。

#### 验收标准

1. THE API_Server SHALL 基于 FastAPI 框架提供 REST API 服务，并在 `/docs` 路径自动生成 OpenAPI 文档。
2. THE API_Server SHALL 提供 `GET /api/v1/violations` 接口，支持按 `camera_id`、`start_time`、`end_time`、`violation_type` 参数过滤并返回违规事件列表。
3. THE API_Server SHALL 提供 `GET /api/v1/violations/{event_id}` 接口，返回指定违规事件的完整详情。
4. THE API_Server SHALL 提供 `GET /api/v1/cameras` 接口，返回当前所有已注册摄像头的状态信息。
5. THE API_Server SHALL 提供 `GET /api/v1/stats` 接口，返回指定时间范围内的违规统计汇总数据。
6. WHEN API 请求参数不合法，THE API_Server SHALL 返回 HTTP 422 状态码及结构化的错误描述信息。
7. IF 后端服务发生未捕获异常，THEN THE API_Server SHALL 返回 HTTP 500 状态码，并记录完整的错误堆栈日志，不向客户端暴露内部实现细节。
8. THE API_Server SHALL 支持跨域资源共享（CORS），允许前端仪表板域名发起跨域请求。

---

### 需求 6：实时监控仪表板

**用户故事：** 作为安全管理员，我希望通过可视化仪表板实时查看 PPE 违规告警和历史数据，以便快速响应现场安全问题。

#### 验收标准

1. THE Dashboard SHALL 基于 React 框架和 Tailwind CSS 构建，并在现代浏览器中正常渲染。
2. THE Dashboard SHALL 每 5 秒自动轮询后端 API，刷新最新违规告警列表。
3. WHEN 检测到新的违规事件，THE Dashboard SHALL 在告警列表顶部显示该事件，并包含摄像头编号、违规时间、违规类型及快照缩略图。
4. THE Dashboard SHALL 提供历史违规记录查询功能，支持按摄像头编号和时间范围进行筛选。
5. THE Dashboard SHALL 展示各摄像头的实时在线状态（在线 / 离线）。
6. THE Dashboard SHALL 展示当日违规次数统计及按违规类型分类的汇总图表。
7. IF 后端 API 请求失败，THEN THE Dashboard SHALL 显示友好的错误提示信息，不展示空白页面或未处理的异常。

---

### 需求 7：系统配置与模块化设计

**用户故事：** 作为系统运维工程师，我希望系统采用模块化设计并支持外部化配置，以便于部署、维护和扩展。

#### 验收标准

1. THE API_Server SHALL 通过环境变量或 `.env` 配置文件读取所有外部服务的连接参数，包括数据库连接字符串、Yandex Object Storage 端点与凭证、Yandex Vision API 密钥、RTSP 流地址列表。
2. THE API_Server SHALL 将视频处理、视觉分析、存储操作、数据库访问四个功能拆分为独立的 Python 模块，模块间通过明确定义的接口进行交互。
3. IF 任意必需的环境变量未配置，THEN THE API_Server SHALL 在启动时输出明确的错误信息并拒绝启动。
4. THE API_Server SHALL 为所有模块提供结构化日志输出，日志级别可通过配置项调整。
5. WHERE 部署环境支持 Docker，THE API_Server SHALL 提供 Dockerfile 及 docker-compose.yml 以支持容器化部署。
