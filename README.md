# PPE Vision Monitor

本项目是一个本地运行的个人防护装备（PPE）视频监测原型。后端使用 **Ultralytics YOLOv8** 对 RTSP 视频帧或人工上传图片进行目标检测；不会调用 Yandex Vision API，也不需要任何云端视觉服务密钥。违规快照保存到本机，并由 FastAPI 的 `/snapshots` 路由提供访问。

## 当前数据集

根目录 `archive/` 为原始数据：图片与 YOLO 标签平铺存放。实际核对结果如下：

- 1,754 张 `.jpg` 图片、1,756 个 `.txt` 文件（其中 `classes.txt` 不是样本标签）；
- 1,753 个有效图片—标签配对；1 张图片没有标签、2 个标签没有对应图片，预处理时会记录并跳过；
- 已抽样核对标签：`0 = helmet`（安全帽），`1 = vest`（反光背心）。

`backend/training/prepare_dataset.py` 使用随机种子 `42` 建立固定的 70%/20%/10% 划分：训练集 1,227 张、验证集 351 张、测试集 175 张。生成目录 `backend/datasets/` 被 Git 忽略，原始 `archive/` 不会被改写。

## 运行实验

请在 `backend/` 目录执行：

```powershell
python training/prepare_dataset.py
python training/train.py --epochs 50 --batch 2 --device cpu
```

MX350 仅有 2 GB 显存；若 CUDA 环境可用，可将 `--device cpu` 改为 `--device 0`，并将 `--batch` 降为 `1`。训练脚本会打印测试集的 mAP 指标，但不会预填任何结果。训练结束后，将生成的 `best.pt` 复制为：

```text
backend/models/best.pt
```

## 启动系统

```powershell
Copy-Item .env.example .env
docker compose up --build
```

可选地在 `.env` 中填写 `RTSP_STREAMS=cam_01=rtsp://...`。不填写时不会启动摄像头任务，仍可通过 `POST /api/analyze-upload` 上传图片验证模型。前端开发服务：

```powershell
cd frontend
npm install
npm run dev
```

## 架构

```text
RTSP camera / uploaded image
        |
OpenCV frame capture
        |
Local YOLOv8 inference (best.pt)
        |
Violation decision + bounding boxes + inference metadata
        |                         |
PostgreSQL event record     local snapshots/ directory
        |
FastAPI API -> React dashboard
```

系统记录的是本地 YOLOv8 推理延迟，不是网络 API 往返时间。论文中的准确率、mAP、延迟或“与云端 API 的对比”必须只采用本机实际执行训练/测试后生成的记录；在结果尚未复现前，不应填入数值。

## 主要目录

```text
backend/
  models/best.pt              # 训练后放入的权重（不提交）
  training/prepare_dataset.py # 可复现数据划分
  training/train.py           # YOLOv8 训练与测试
  modules/vision_analyzer.py  # 本地推理
  modules/violation_recorder.py # 本地快照保存
  snapshots/                  # 违规证据帧
frontend/                     # React 仪表板
archive/                      # 用户提供的原始图片与标签
```
