# 任务取消功能快速开始

## 🚀 5分钟快速体验

### 前提条件

确保系统已经启动：
```bash
# 方式1：本地开发模式
make dev

# 方式2：Docker模式
make docker-run
```

访问地址：
- 前端：http://localhost:8501
- 后端：http://localhost:8000

---

## 📝 场景一：前端界面操作（推荐）

### 步骤 1：上传文档

1. 打开前端界面 http://localhost:8501
2. 在左侧找到"📤 上传文档"区域
3. 选择一个**较大的PDF文件**（建议 > 5MB）
4. 点击"📤 上传文件"按钮

### 步骤 2：查看处理状态

上传成功后，你会看到：
```
✅ test.pdf 上传成功!
🔄 文档正在后台异步处理中... 文档ID: abc-123-def

📋 大型文档处理提示：
• 🔍 扫描版PDF需要OCR文字识别，可能需要3-10分钟
• 📊 处理进度将实时显示在下方监听区域
• ✅ 处理完成后会自动更新文档列表和统计信息
• 🛑 如需取消处理，请点击下方取消按钮

[📊 查看处理状态]  [🛑 取消处理]
```

### 步骤 3：取消任务

点击 **"🛑 取消处理"** 按钮，系统会：
1. 发送取消请求到后端
2. 停止文档处理
3. 清理相关文件
4. 显示取消成功消息

### 步骤 4：验证结果

- 查看"正在处理的文档"列表，该文档应该已被移除
- 在文档列表中不会看到这个文档
- 后台日志会显示取消操作

---

## 🔧 场景二：API调用测试

### 步骤 1：上传文档并获取 document_id

```bash
# 上传文档
curl -X POST "http://localhost:8000/api/documents/upload-async" \
  -F "file=@test.pdf"

# 响应示例
{
  "success": true,
  "message": "文件上传成功，已加入处理队列",
  "document_id": "abc-123-def",
  "status": "queued"
}
```

### 步骤 2：查询任务状态

```bash
curl "http://localhost:8000/api/documents/status/abc-123-def"

# 响应示例
{
  "status": "processing",
  "progress": 30,
  "message": "正在解析文档内容..."
}
```

### 步骤 3：检查是否可取消

```bash
curl "http://localhost:8000/api/documents/cancel-status/abc-123-def"

# 响应示例
{
  "success": true,
  "document_id": "abc-123-def",
  "status": "processing",
  "cancellable": true,
  "progress": 30,
  "message": "正在解析文档内容..."
}
```

### 步骤 4：取消任务

```bash
curl -X POST "http://localhost:8000/api/documents/cancel/abc-123-def"

# 响应示例（任务未开始）
{
  "success": true,
  "message": "任务已取消（未开始执行）",
  "document_id": "abc-123-def",
  "status": "cancelled"
}

# 或（任务执行中）
{
  "success": true,
  "message": "取消请求已发送，任务将在下一个检查点停止",
  "document_id": "abc-123-def",
  "status": "cancelling"
}
```

### 步骤 5：验证取消结果

```bash
curl "http://localhost:8000/api/documents/status/abc-123-def"

# 响应示例
{
  "status": "cancelled",
  "progress": 100,
  "message": "Task cancelled by user",
  "cancelled_at": "2024-01-01T12:00:00"
}
```

---

## 🎯 场景三：使用演示脚本

我们提供了一个演示脚本来自动化测试：

```bash
# 场景1：上传后立即取消
python scripts/demo_cancel_task.py test.pdf 1

# 场景2：处理过程中取消
python scripts/demo_cancel_task.py test.pdf 2
```

脚本会自动：
1. 上传文档
2. 监控处理状态
3. 在适当时机取消任务
4. 显示完整的操作流程

---

## 📊 预期结果

### 成功取消的标志

✅ 前端显示"已取消 xxx 的处理"  
✅ 文档不会出现在文档列表中  
✅ 临时文件已被清理  
✅ 任务状态为 `cancelled`  
✅ 后台日志显示取消操作  

### 后台日志示例

```
INFO - Cancel flag set for document abc-123-def
INFO - Task abc-123-def detected cancellation flag
INFO - Cleaned up file: /tmp/test.pdf
INFO - Document processing cancelled: test.pdf
```

---

## ❓ 常见问题

### Q1: 点击取消后任务还在继续？
**A**: 如果任务正在执行，会在下一个检查点停止，可能需要几秒钟。

### Q2: 取消后文件还在服务器上？
**A**: 不会，取消操作会自动清理所有相关文件。

### Q3: 可以取消已完成的任务吗？
**A**: 不可以，只有 `processing` 状态的任务可以取消。

### Q4: 取消会影响其他任务吗？
**A**: 不会，每个任务独立处理，互不影响。

---

## 📚 更多信息

- 详细使用指南：[CANCEL_TASK_GUIDE.md](CANCEL_TASK_GUIDE.md)
- 功能实现总结：[CANCEL_FEATURE_SUMMARY.md](archive/CANCEL_FEATURE_SUMMARY.md)
- API文档：http://localhost:8000/docs

