# 模型配置指南

从 [.env.secure.example](.env.secure.example) 复制本地 `.env` 后编辑。安装和启动命令见 [README](README.md)。

## 聊天和嵌入

| Provider | 聊天默认映射 | 嵌入默认映射 |
| --- | --- | --- |
| openai | `https://api.openai.com/v1`，`gpt-3.5-turbo` | 同端点，`text-embedding-ada-002` |
| deepseek | `https://api.deepseek.com`，`deepseek-v4-flash` | 无专用默认映射，应另配嵌入服务 |
| zhipu | `https://open.bigmodel.cn/api/paas/v4`，`glm-4` | 同端点，`embedding-3` |
| qwen | 须显式配置兼容聊天端点和模型 | `https://dashscope.aliyuncs.com/compatible-mode/v1`，`text-embedding-v3`；优先尝试 DashScope SDK |

以上是代码映射，不保证供应商模型生命周期或账号可用性。默认模型替换仅在模型名仍为代码中的 OpenAI 默认值时发生；切换 Provider 时建议显式指定模型。

DeepSeek 聊天搭配 OpenAI 嵌入示例：

```dotenv
LLM_PROVIDER=deepseek
API_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-v4-flash
EMBEDDING_PROVIDER=openai
EMBEDDING_API_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-ada-002
```

分别通过系统环境或本地 `.env` 提供 `API_KEY` 和 `EMBEDDING_API_KEY`。不要把 DeepSeek 聊天 Key 当成 OpenAI 嵌入 Key。更换嵌入模型应重建向量库或使用新集合，不能混用不同模型的向量。

## 密钥来源

聊天依次读取 `API_KEY`、`API_KEY_FILE`、`API_KEY_BASE64`，然后兼容 `OPENAI_API_KEY` 及对应文件/Base64 配置，再尝试代码约定的 Docker secret 路径和 Keyring。

嵌入优先读取 `EMBEDDING_API_KEY`、`EMBEDDING_API_KEY_FILE`、`EMBEDDING_API_KEY_BASE64`；智谱还可回退 `ZHIPU_API_KEY`，最后回退通用聊天 Key。跨提供商时显式配置嵌入 Key。Base64 只是编码，不是加密。

容器使用文件 Key 时，明确设置 `API_KEY_FILE` 和 `EMBEDDING_API_KEY_FILE` 为实际挂载的容器内路径。宿主机 Keyring 和系统环境不会自动进入容器。

## BYOK 与 URL

BYOK 只覆盖聊天配置，不替换服务端嵌入 Key。自定义聊天 URL 必须同时提供用户 Key，并使用 HTTPS、匹配 `ALLOWED_CHAT_BASE_URLS` 前缀白名单，DNS 解析结果不得包含私网、回环、链路本地或组播地址。默认白名单不含 Qwen 聊天端点，需部署者显式配置。

服务端 `API_BASE_URL` 不经过请求覆盖的 URL 检查。前端应显式选择 Provider，避免只凭 Key 长度猜测。浏览器可能保存设置和 Key，共用设备使用后清除。

管理员登录另需 `JWT_SECRET` 和 `ADMIN_PASSWORD_HASH`（或对应文件/Base64配置）。密码哈希生成命令：`python scripts/generate_admin_hash.py`。参见 [安全指南](SECURITY.md)。
