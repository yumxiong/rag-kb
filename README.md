# RAG Knowledge Base

[文档导航](docs/README.md) · [部署指南](docker/README.md) · [任务取消](docs/CANCEL_TASK_GUIDE.md)

一个面向中文与多模型场景的 RAG（Retrieval-Augmented Generation）知识库系统：

- 后端使用 **FastAPI** 提供文档、问答、配额、成本监控等 API
- 前端使用 **Streamlit** 提供开箱即用的上传、检索、问答与管理界面
- 底层使用 **ChromaDB + LangChain** 构建向量检索与问答链路
- 支持 **OpenAI / DeepSeek / Zhipu / Qwen / OpenAI-compatible** 多种接入方式

它不仅是一个“能跑起来”的 RAG Demo，也包含了不少更贴近真实产品环境的能力：**异步文档处理、实时状态更新、任务取消、扫描版 PDF OCR、BYOK、自定义配额、缓存节流、管理员控制台、Docker/HTTPS 部署**。

## ✨ 核心能力

### 文档处理

- 支持 `PDF`、`DOCX/DOC`、`TXT`、`Markdown`
- PDF 采用智能处理策略：可搜索 PDF 优先走文本提取，扫描版 PDF 可走 OCR 增强流程
- 文档自动切分为 chunk，并写入 ChromaDB 向量库
- 上传后支持同步或异步处理，适合大文件与慢 OCR 场景

### 检索与问答

- 基于 LangChain 的 RAG 问答链路
- 支持语义检索与带来源引用的回答
- 前端可限制检索范围到单个文档，减少跨文档误召回
- 提供问题建议、检索结果来源展示、处理耗时展示

### 多模型 / 多提供商

- 服务端支持 `openai`、`deepseek`、`zhipu`、`qwen`
- 前端支持 **BYOK（Bring Your Own Key）**
- 可自定义模型名与 OpenAI-compatible `base_url`
- 用户设置会保存在浏览器本地，便于切换不同模型供应商

### 实时性与可操作性

- 异步上传任务可查询状态
- 提供 **SSE 状态流** 与前端实时更新机制
- 可取消仍在处理中的文档任务
- 对超时、失败、取消等状态有单独反馈

### 管理与成本控制

- 管理员登录（JWT）
- 配额管理：默认按用户指纹限制每日调用次数
- 用户自带 Key 时可绕过平台默认配额
- SQLite 缓存嵌入与问答结果，减少重复请求成本
- 提供缓存统计、成本节省估算、优化建议接口

### 工程化能力

- FastAPI 自动文档：`/docs`
- 单元测试、覆盖率、lint、format 命令齐全
- Docker / Docker Compose 开发与部署配置
- 本地 HTTPS 开发脚本与 Nginx 配置
- Secret 文件、环境变量、Keyring 等多种安全配置方式

## 🏗️ 系统架构

```text
Streamlit UI
    ↓
FastAPI API
    ├─ 文档上传 / 异步任务 / 状态查询 / 取消
    ├─ QA 检索 / 问答 / 配额 / 管理员认证
    ├─ 成本监控 / 缓存统计
    ↓
Core Services
    ├─ DocumentProcessor / EnhancedPDFProcessor
    ├─ QAEngine
    ├─ VectorStore (ChromaDB)
    ├─ CacheManager / QuotaManager
    ↓
LLM / Embedding Providers
    ├─ OpenAI
    ├─ DeepSeek
    ├─ Zhipu GLM
    ├─ Qwen
    └─ Custom OpenAI-compatible API
```

## 🧱 技术栈

### Backend

- FastAPI
- LangChain / langchain-openai / langchain-chroma
- ChromaDB
- PyMuPDF / PyPDF / unstructured
- Pydantic Settings

### Frontend

- Streamlit
- requests
- streamlit-js-eval

### Storage / Infra

- ChromaDB 向量存储
- SQLite 缓存
- 本地文件存储（上传文件、配额数据、作业状态）
- Docker / Docker Compose / Nginx

## 📁 项目结构

```text
app/
  api/           # FastAPI 路由：documents / qa / auth / cost
  core/          # 文档处理、向量库、问答引擎、缓存、配额、配置
  models/        # Pydantic 模型
  main.py        # FastAPI 入口

frontend/
  components/    # 上传、问答、文档管理、模型设置等组件
  pages/         # Streamlit 多页面（如 Admin）
  utils/         # 状态管理、实时更新、本地设置加载
  streamlit_app.py

tests/           # Pytest 测试
docker/          # Dockerfile、compose、Nginx、本地 HTTPS 配置
scripts/         # 环境、安全、启动、辅助脚本
data/            # 上传文件、向量库、配额、任务状态
secrets/         # 本地 secret 文件（请勿提交）
```

## 🚀 快速开始

### 1) 环境要求

- Python 3.11+
- pip
- Docker（可选）
- 可用的 LLM API Key（OpenAI / DeepSeek / Zhipu 等）

### 2) 克隆仓库

```bash
git clone <your-repo-url>
cd <your-repo-dir>
```

### 3) 创建虚拟环境

```bash
python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 4) 安装依赖

```bash
make install
```

如果你不使用 `make`，也可以手动执行：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data/uploads data/chroma_db logs
```

### 5) 配置模型与密钥

推荐方式：

1. 复制一个示例配置
2. 填入你的 API Key
3. 启动服务

示例文件：

- `.env.secure.example`：安全配置模板
- `.env.deepseek`：DeepSeek 示例
- `.env.zhipu`：Zhipu 示例

最简单的方式是使用环境变量：

```bash
# Linux / macOS
export OPENAI_API_KEY="your-key"

# Windows PowerShell
$env:OPENAI_API_KEY="your-key"
```

也可以使用：

- `API_KEY`
- `OPENAI_API_KEY_FILE`
- Docker secrets
- 系统 Keyring（`make setup-keyring`）

更多安全说明请查看 [SECURITY.md](SECURITY.md)。

### 6) 启动开发环境

#### 方案 A：一键启动

```bash
make dev
```

#### 方案 B：手动分别启动

终端 1：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

终端 2：

```bash
BACKEND_URL=http://localhost:8000 streamlit run frontend/streamlit_app.py
```

### 7) 访问地址

- Frontend: http://localhost:8501
- Backend API: http://localhost:8000
- Swagger Docs: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

## 🐳 Docker 与 HTTPS

### Docker 开发模式

```bash
make docker-dev
```

对应配置文件：`docker/docker-compose.dev.yml`

### Docker 常规运行

```bash
make docker-run
```

停止服务：

```bash
make docker-stop
```

查看日志：

```bash
make docker-logs
```

### 本地 HTTPS 开发

仓库内已经提供本地 HTTPS 配置脚本与 Nginx 配置。

```bash
make setup-local-https
make dev-https
```

适合需要测试浏览器安全策略、同源/混合内容、HTTPS 场景联调时使用。

## 🤖 支持的模型与接入方式

### 服务端配置

通过环境变量控制：

- `LLM_PROVIDER`
- `EMBEDDING_PROVIDER`
- `CHAT_MODEL`
- `EMBEDDING_MODEL`
- `API_KEY`
- `API_BASE_URL`
- `EMBEDDING_API_BASE_URL`

常见 provider：

- `openai`
- `deepseek`
- `zhipu`
- `qwen`

### 前端 BYOK

前端支持用户临时输入自己的：

- Provider
- API Key
- Base URL
- Model

这些设置会保存在浏览器本地存储中，适合：

- 临时切换模型测试
- 多环境联调
- 平台 Key 与用户 Key 并存的场景

## 📄 文档处理说明

### 支持格式

- `.pdf`
- `.docx`
- `.doc`
- `.txt`
- `.md`

### PDF 处理策略

- 可提取文本的 PDF：优先使用快速文本提取
- 扫描版 PDF：启用 OCR 增强流程
- OCR 场景支持取消，避免超长任务阻塞

### OCR 说明

项目已包含 `pytesseract` 与 `Pillow` Python 依赖，但若要完整处理扫描版 PDF，通常还需要在系统层安装 **Tesseract-OCR**。

如果扫描版 PDF 效果不理想，请优先检查：

- 是否已安装 Tesseract 引擎
- PDF 图像是否清晰
- 是否存在密码保护或损坏

## 💬 典型使用流程

1. 上传一个或多个文档
2. 等待后台处理完成
3. 在聊天区提问
4. 查看回答、来源片段和处理耗时
5. 如需要，限定检索范围到某个文档
6. 对于大文件，可随时查看状态或取消任务

## 🔐 管理员与配额

系统包含一个简单但实用的管理员控制台（Streamlit `Admin` 页面）：

- 管理员登录基于 JWT
- 可查看配额统计
- 可重置用户配额

默认配额逻辑：

- 基于 `IP + User-Agent` 生成用户指纹
- 平台默认每日配额由 `DEFAULT_DAILY_QUOTA` 控制
- 若用户通过前端提供自己的 API Key，则可绕过默认平台配额

相关配置：

- `ENABLE_QUOTA_LIMIT`
- `DEFAULT_DAILY_QUOTA`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH` / `ADMIN_PASSWORD_HASH_FILE`
- `JWT_SECRET` / `JWT_SECRET_FILE`

可用脚本：

```bash
python scripts/generate_admin_hash.py
```

## 💸 缓存与成本优化

项目内置两类缓存：

- Embedding cache
- QA cache

特点：

- 使用 SQLite 持久化缓存
- 记录命中次数与最近访问时间
- 可计算粗略成本节省估算
- 提供缓存清理与优化建议 API

相关接口示例：

- `GET /api/cost/cache/stats`
- `GET /api/cost/embedding/stats`
- `POST /api/cost/cache/cleanup`
- `GET /api/cost/optimization/recommendations`

## 📚 主要 API 一览

### 基础接口

- `GET /`
- `GET /health`
- `GET /info`

### 文档接口

- `POST /api/documents/upload`
- `POST /api/documents/upload-async`
- `GET /api/documents/status/{document_id}`
- `GET /api/documents/status/stream/{document_id}`
- `POST /api/documents/cancel/{document_id}`
- `GET /api/documents/stats/overview`

### 问答接口

- `POST /api/qa/ask`
- `POST /api/qa/search`
- `GET /api/qa/suggestions`
- `GET /api/qa/health`
- `GET /api/qa/stats`
- `GET /api/qa/quota`

### 管理与认证

- `POST /api/auth/login`
- `POST /api/qa/quota/reset`
- `GET /api/qa/quota/stats`

### 成本优化

- `GET /api/cost/cache/stats`
- `GET /api/cost/optimization/recommendations`

## ⚙️ 关键配置项

| 变量名 | 说明 | 默认值 |
|---|---|---|
| `APP_NAME` | 应用名称 | `RAG Knowledge Base` |
| `DEBUG` | 调试模式 | `True` |
| `API_KEY` / `OPENAI_API_KEY` | 默认模型 API Key | 无 |
| `LLM_PROVIDER` | 聊天模型提供商 | `openai` |
| `EMBEDDING_PROVIDER` | 嵌入模型提供商 | `openai` |
| `CHAT_MODEL` | 聊天模型名 | `gpt-3.5-turbo` |
| `EMBEDDING_MODEL` | 嵌入模型名 | `text-embedding-ada-002` |
| `CHUNK_SIZE` | 文档分块大小 | `1000` |
| `CHUNK_OVERLAP` | 分块重叠大小 | `200` |
| `MAX_SOURCES` | 最多引用来源数 | `3` |
| `SIMILARITY_THRESHOLD` | 相似度阈值 | `0.7` |
| `MAX_FILE_SIZE_MB` | 上传文件大小限制 | `50` |
| `ENABLE_QUOTA_LIMIT` | 是否启用配额限制 | `True` |
| `DEFAULT_DAILY_QUOTA` | 默认每日问答配额 | `5` |
| `UPLOAD_DIR` | 上传文件目录 | `./data/uploads` |
| `CHROMA_DB_PATH` | 向量库存储目录 | `./data/chroma_db` |
| `ALLOWED_ORIGINS` | CORS 白名单 | `*` 或配置值 |

## 🧪 测试与开发命令

### 测试

```bash
make test
```

生成 HTML 覆盖率报告：

```bash
make test-html
```

### 代码质量

```bash
make format
make lint
```

项目测试基于 `pytest`，覆盖率阈值配置为 **70%**。

## 🛠️ 常见排查

### 上传后无法问答

- 确认文档状态已完成
- 确认向量库中已有文档
- 确认默认 API Key 或 BYOK 配置有效

### 扫描版 PDF 提取失败

- 检查是否安装系统级 Tesseract-OCR
- 检查 PDF 清晰度
- 尝试缩小文件或重新导出 PDF

### Docker 启动异常

- 检查 `.env` 是否存在且配置正确
- 检查 `8000` / `8501` 端口占用
- 查看 `make docker-logs`

### 问答慢或成本高

- 降低 `MAX_SOURCES`
- 使用缓存统计接口观察命中率
- 检查模型供应商响应时间

## 🔒 安全建议

- 不要提交 `.env`、密钥文件或 `secrets/` 中的真实内容
- 优先使用环境变量、Keyring 或 secret 文件
- 生产环境请显式配置 CORS
- 管理员密码只保存哈希，不保存明文

## 🤝 开发建议

提交前建议至少运行：

```bash
make format
make lint
make test
```

如果你准备扩展这个项目，比较适合的方向包括：

- 新增文档格式（如 Excel / PPT）
- 增强文档过滤、标签与元数据检索
- 增加对话历史与会话持久化
- 接入更多 OpenAI-compatible 服务
- 增加更完整的管理员运维页面

## 📄 License

本项目采用 MIT License。

---

如果你想把它继续扩展成团队内部知识库、客服问答底座，或一个支持多租户/多模型的 RAG 平台，这个仓库已经具备一个很不错的工程起点。
