# 🔐 安全配置指南

当前模型配置以 [模型配置指南](SETUP_API_KEY.md) 为准，容器端口、env_file 和生成文件以 [部署指南](docker/README.md) 为准。`ENABLE_API_DOCS=False`、`DEBUG=False` 为代码默认值。Base64 是编码，不是加密；宿主机 Keyring 不会自动进入 Docker 容器。

## API Key安全管理

为了保护您的OpenAI API Key，我们提供了多种安全的存储方式。**强烈建议不要将API Key明文存储在.env文件中**。

## 🛡️ 推荐的安全方案

### 1. 系统环境变量 (★★★★★ 推荐)

在操作系统级别设置环境变量，不写入任何文件：

**Windows:**
```powershell
# 临时设置（当前会话）
$env:OPENAI_API_KEY = "your-api-key-here"

# 永久设置
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-api-key-here", "User")
```

**Linux/Mac:**
```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
export OPENAI_API_KEY="your-api-key-here"

# 重新加载配置
source ~/.bashrc
```

### 2. 系统密钥环 (★★★★★ 最安全)

使用操作系统的密钥管理服务：

```bash
# 安装keyring
pip install keyring

# 设置密钥
python scripts/setup-keyring.py

# 删除密钥
python scripts/setup-keyring.py delete
```

### 3. Docker Secrets (★★★★☆ 生产推荐)

适用于生产环境的Docker部署：

```bash
# 设置Docker secrets
./scripts/setup-secrets.sh

# 使用secrets启动
cd docker
# 仓库未提供 docker-compose.secrets.yml；按部署指南自行配置挂载和 *_FILE。
```

### 4. 限制访问权限的文件存储

将 API Key 存储在单独文件中并限制访问权限；下面的命令不会加密文件：

```bash
# 创建密钥文件
echo "your-api-key-here" > secrets/openai_api_key/deepseek_api_key
chmod 600 secrets/openai_api_key/deepseek_api_key

# 配置环境变量
export OPENAI_API_KEY_FILE="./secrets/openai_api_key/deepseek_api_key"
```

## 🚀 启动应用（安全方式）

### 方式1: 系统环境变量
```bash
export OPENAI_API_KEY="your-key"
./scripts/start.sh
```

### 方式2: 密钥文件
```bash
export OPENAI_API_KEY_FILE="./secrets/openai_api_key/deepseek_api_key"
./scripts/start.sh
```

### 方式3: Docker Secrets
```bash
cd docker
# 仓库未提供 docker-compose.secrets.yml；按部署指南自行配置挂载和 *_FILE。
```

### 方式4: 系统密钥环
```bash
# 无需额外设置，应用会自动检测
./scripts/start.sh
```

## 🔍 安全检查清单

### 开发环境
- [ ] 确保.env文件在.gitignore中
- [ ] 不要在代码中硬编码API Key
- [ ] 使用系统环境变量或密钥环
- [ ] 定期检查Git提交历史

### 生产环境  
- [ ] 使用Docker Secrets或云平台密钥管理服务
- [ ] 启用API Key轮换策略
- [ ] 监控API使用情况和异常调用
- [ ] 设置访问日志和审计

### 团队协作
- [ ] 每个团队成员使用自己的API Key
- [ ] 在文档中明确密钥管理政策
- [ ] 定期进行安全培训和检查
- [ ] 建立密钥泄露应急预案

## 🚨 如果发现密钥泄露

1. **立即行动**
   ```bash
   # 撤销泄露的密钥
   # 在OpenAI控制台中删除API Key
   
   # 生成新的密钥
   # 在OpenAI控制台中创建新的API Key
   ```

2. **检查影响范围**
   - 查看OpenAI使用日志
   - 检查是否有异常API调用
   - 确认哪些服务受到影响

3. **更新系统**
   ```bash
   # 更新所有使用该密钥的服务
   python scripts/setup-keyring.py  # 存储新密钥
   
   # 重启服务
   ./scripts/stop.sh
   ./scripts/start.sh
   ```

4. **预防措施**
   - 审查代码提交历史
   - 更新安全政策
   - 加强访问控制

## 🛠️ 故障排除

### API Key无法读取
```bash
# 检查配置
python -c "
from app.core.config import settings
key = settings.get_openai_api_key()
print('API Key found:', bool(key))
print('Key source: ', end='')
if settings.openai_api_key: print('environment')
elif settings.openai_api_key_file: print('file')
else: print('keyring or other')
"
```

### 权限问题
```bash
# 检查文件权限
ls -la secrets/
ls -la .env*

# 设置正确权限
chmod 600 secrets/*
chmod 600 .env*
```

### Docker Secrets问题
```bash
# 检查secret是否创建成功
docker secret ls

# 检查容器中的secret
docker exec <container-name> ls -la /run/secrets/
```

## 🌐 CORS安全配置

### 快速配置CORS
```bash
# 交互式配置CORS设置
python scripts/setup-cors.py

# 查看当前CORS配置
python scripts/setup-cors.py show
```

### 手动配置CORS
编辑 `.env` 文件或设置环境变量：

```bash
# 开发环境
ALLOWED_ORIGINS=http://localhost:8501,http://127.0.0.1:8501

# 生产环境 - 替换为你的域名
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# HTTP方法限制
ALLOWED_METHODS=GET,POST,DELETE

# 请求头限制
ALLOWED_HEADERS=Content-Type,Authorization
```

### 部署环境配置

**本地开发:**
```bash
cp .env.template .env
# 编辑 .env 文件配置API密钥
```

**生产部署:**
```bash
cp .env.production.template .env.production
# 生产 Compose 未提供，须另行准备；不要把含前端变量的模板直接作为后端 .env。
# 编辑 ALLOWED_ORIGINS 为你的域名
# 确保 DEBUG=False
```

## 📚 最佳实践

1. **永远不要在代码中硬编码密钥**
2. **使用最小权限原则**
3. **定期轮换API密钥**
4. **严格配置CORS域名白名单**
5. **监控API使用情况**
6. **启用访问日志**
7. **建立密钥管理流程**
8. **定期安全审计**
9. **团队安全培训**

## 🔗 相关链接

- [OpenAI API Key管理](https://platform.openai.com/api-keys)
- [Docker Secrets文档](https://docs.docker.com/engine/swarm/secrets/)
- [Python keyring库](https://pypi.org/project/keyring/)
- [环境变量最佳实践](https://12factor.net/config)
