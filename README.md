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

- FastAPI 自动文档：默认关闭，可显式启用 `/docs`
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

### 2) Bash：克隆、安装与配置

以下命令使用 Python 3.11，从仓库根目录运行。前后端安装到同一虚拟环境，两个依赖文件都需要安装。

两份依赖文件的 Requests 已统一为 `2.32.5`。有 Make 和 Bash 的环境也可在激活虚拟环境后使用 `make install`，该目标安装前后端依赖。已有环境可能保留不兼容的传递依赖，建议使用新环境，并执行 `python -m pip check`。

```bash
git clone https://github.com/yumxiong/rag-kb.git
cd rag-kb
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-frontend.txt
python -m pip check
cp .env.secure.example .env
mkdir -p data/uploads data/chroma_db data/job_status logs
```

### 3) PowerShell：克隆、安装与配置

```powershell
git clone https://github.com/yumxiong/rag-kb.git
Set-Location rag-kb
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-frontend.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item .env.secure.example .env
New-Item -ItemType Directory -Force data/uploads,data/chroma_db,data/job_status,logs | Out-Null
```

仅首次配置时复制模板；已有 `.env` 时直接编辑。模板不含有效密钥。填写匹配聊天提供商的 `API_KEY`（默认 OpenAI 也可用 `OPENAI_API_KEY`），并为文档入库和检索配置 `EMBEDDING_API_KEY`。同一提供商可使用同一个有效 Key；不同提供商须分别填写。只有前端 BYOK 聊天 Key 不能替代服务端 Embedding Key。

管理员页面另需 `JWT_SECRET` 和 `ADMIN_PASSWORD_HASH`，可用 `python scripts/generate_admin_hash.py` 生成密码哈希；未配置时管理员登录不可用。普通上传/问答不要求启用管理员功能。更多信息见 [模型配置](SETUP_API_KEY.md) 和 [安全指南](SECURITY.md)。

### 4) 分别启动后端与前端

Bash 终端 1（仓库根目录）：

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Bash 终端 2（同一仓库根目录）：

```bash
source .venv/bin/activate
BACKEND_URL=http://localhost:8000 BACKEND_URL_CLIENT=http://localhost:8000 python -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

PowerShell 终端 1：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

PowerShell 终端 2：

```powershell
$env:BACKEND_URL = 'http://localhost:8000'
$env:BACKEND_URL_CLIENT = 'http://localhost:8000'
.\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

前端地址为 http://localhost:8501，健康接口为 http://localhost:8000/health。健康接口检查配置和目录，不证明模型调用成功。`/docs`、`/redoc`、`/openapi.json` 默认关闭；仅需本地调试时在 `.env` 设置 `ENABLE_API_DOCS=True` 后重启后端。

2026-09-14 在 Windows / Python 3.11.5 新建隔离环境完成前后端依赖安装、`pip check` 和本地核心问答验收：虚构 Markdown 上传、真实 Qwen 嵌入入库、DeepSeek 回答及浏览器来源展示均已验证。实际安装发现的兼容问题通过 `chardet<6`、`posthog<6` 约束修复；管理员元数据查询与向量查询的 Chroma 配置已统一，Qwen 使用配置的兼容端点并发送文本。

复现素材：[演示支持政策](docs/examples/demo-support-policy.md)。先按上文配置管理员密码哈希和 JWT 密钥，登录前端 Admin 页，返回主页，从侧栏选择该文件并点击“上传文件”。等待任务完成、知识库显示 1 个文档后，提问“导出文件保留多久？”。本次回答为“导出文件保留七天；超过七天后需要重新申请”，API 和页面参考来源均为 `demo-support-policy.md`。上传成功仅表示进入队列，须另外确认处理完成。

本次非敏感模型配置如下；两个 Key 分别通过安全环境提供，不填写到公开文件中：

```dotenv
LLM_PROVIDER=deepseek
CHAT_MODEL=deepseek-flash
API_BASE_URL=https://api.deepseek.com
EMBEDDING_PROVIDER=qwen
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

验收使用独立上传、Chroma、缓存及任务目录，后端/前端绑定 `127.0.0.1:18000/18501`，相应调整 `BACKEND_URL`、`BACKEND_URL_CLIENT` 和 CORS。首次 API 回答 `from_cache=false`；随后浏览器展示复用了该真实回答的缓存。专项单测原有 100 项通过，修复后的向量存储专项 32 项通过；这些结果不代表全应用覆盖率验收。Docker 仅完成先前的 Compose 配置解析，未构建镜像；OCR、HTTPS 和生产部署未做本轮端到端验收。本机曾出现内存/线程资源不足及浏览器卡死，释放本轮资源并重启浏览器后完成验收。

## 🐳 Docker 与 HTTPS

[部署指南](docker/README.md) 是 Docker 主入口。标准 `docker-compose.yml` 仅在 Docker 网络内暴露 8000/8501，不发布宿主机端口，也不自动将根目录 `.env` 注入后端。

本地 HTTP 开发需要准备 `.env.dev`，并合并标准与开发配置：

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up -d --build
```

此命令同样适用于 PowerShell。开发模式将 8000/8501 绑定到 `127.0.0.1`。HTTPS 还需要 mkcert 证书及 `.env.local-https`；生产 Compose 文件未随仓库提供，不能直接运行其文件名。

## 🤖 模型、Provider 与 Key

聊天和嵌入配置独立。聊天通过 OpenAI-compatible 客户端；嵌入明确支持 `openai`、`zhipu`、`qwen` 路径。不要把 DeepSeek 聊天 Key 当成 OpenAI 嵌入 Key。

| 用途 | 配置 | Key |
| --- | --- | --- |
| 服务端聊天 | `LLM_PROVIDER`、`CHAT_MODEL`、`API_BASE_URL` | `API_KEY` / `API_KEY_FILE`，兼容 `OPENAI_API_KEY` |
| 服务端嵌入 | `EMBEDDING_PROVIDER`、`EMBEDDING_MODEL`、`EMBEDDING_API_BASE_URL` | 优先 `EMBEDDING_API_KEY` / `EMBEDDING_API_KEY_FILE`，缺省可回退通用 Key |
| 前端 BYOK | 请求中的 Provider、Model、Base URL | 用户聊天 Key，不覆盖服务端嵌入配置 |

前端自定义聊天 URL 必须使用 HTTPS、通过 `ALLOWED_CHAT_BASE_URLS` 前缀白名单与 DNS 地址检查，不能指向私网/回环地址；提供自定义 URL 还必须同时提供用户 Key。白名单默认包含 OpenAI、DeepSeek、智谱和 OpenRouter，未包含 Qwen 聊天端点。服务端 `API_BASE_URL` 不走这一请求覆盖检查，由部署者配置。

前端可将用户模型设置保存在浏览器本地存储，共用浏览器时需清理保存的 Key。各提供商默认映射和示例见 [模型配置指南](SETUP_API_KEY.md)。

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
| `DEBUG` | 调试模式 | `False` |
| `ENABLE_API_DOCS` | API 文档与 OpenAPI | `False` |
| `API_KEY` / `OPENAI_API_KEY` | 默认模型 API Key | 无 |
| `LLM_PROVIDER` | 聊天模型提供商 | `openai` |
| `EMBEDDING_PROVIDER` | 嵌入模型提供商 | `openai` |
| `CHAT_MODEL` | 聊天模型名 | `gpt-3.5-turbo` |
| `EMBEDDING_MODEL` | 嵌入模型名 | `text-embedding-ada-002` |
| `CHUNK_SIZE` | 文档分块大小 | `1000` |
| `CHUNK_OVERLAP` | 分块重叠大小 | `200` |
| `MAX_SOURCES` | 最多引用来源数 | `3` |
| `SIMILARITY_THRESHOLD` | Chroma 距离阈值，越小越相似；不是百分比 | `1.5` |
| `MAX_FILE_SIZE_MB` | 上传文件大小限制 | `50` |
| `ENABLE_QUOTA_LIMIT` | 是否启用配额限制 | `True` |
| `DEFAULT_DAILY_QUOTA` | 默认每日问答配额 | `5` |
| `UPLOAD_DIR` | 上传文件目录 | `./data/uploads` |
| `CHROMA_DB_PATH` | 向量库存储目录 | `./data/chroma_db` |
| `ALLOWED_ORIGINS` | CORS 白名单 | `http://localhost:8501,http://127.0.0.1:8501` |

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

## 检索评测状态

当前分支保留评测工具和离线测试；私人旧题集及旧成绩已移出当前跟踪范围。公开语料和题集仍在独立人工审核，本分支尚无公开、可复现的检索基线，也未完成正式 30 题评测。参见 [评测工具说明](eval/README.md)。专项测试通过不代表检索成绩或全应用覆盖率通过。

## 📄 License

当前仓库未提供 LICENSE，代码及自编语料的许可尚待作者明确；暂不声明采用 MIT 或其他开源许可。第三方依赖各自遵循其许可证。

---

后续复现结果以实际启动、上传、问答及来源展示的验收记录为准。
