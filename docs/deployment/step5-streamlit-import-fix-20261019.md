# Streamlit 包导入修复（2026-10-19）

用户报告根域名显示 `ModuleNotFoundError: No module named 'frontend'`；
Next 及转发到 Next 的 www 正常。Docker 的 Streamlit CLI 提供入口目录
`/app/frontend`，但未提供包根目录 `/app`；chat_interface 的
`frontend.utils.anonymous_session` 导入因此失败。

Dockerfile 增加 `ENV PYTHONPATH=/app`，放在依赖安装之后保持现网依赖层。
源提交 `66f517b` 添加修复和镜像验收脚本，`21271bf95aed2905ee34d1296806626e5fa78496`
将环境设置移至依赖层之后。未修改应用逻辑、身份或预算契约。

## 验证

- 旧镜像在隔离 AppTest 中复现同一 frontend 导入错误。
- 探针仅补齐 Streamlit CLI 实际提供的入口目录，不向 sys.path 注入 `/app`，
  包根目录必须由镜像提供。真实完整 streamlit_app.py 执行及再次渲染均无异常，
  四个建议问题可见、匿名用户无上传控件和 admin_jwt。后端为模拟响应且容器断网。
- 最终镜像依赖清单与现网 `4d1ba85` 镜像完全一致。
  首个候选因设置位置使依赖重装产生三项无关更新，已弃用；虽然上传到独立暂存目录，
  没有加载或部署，不作为交付候选。
- 最终镜像 `rag-step5-streamlit:21271bf` 的 ID：
  `sha256:16edb0a8bc576f3803fc039f0b03c965af5028d5a60cc00d3db00f81ba50b94a`。
  镜像包 326279168 字节，SHA256：
  `fcb71bf4c3cc06604164fdc79a4b9c536ed5d511f9fb8c7f816b43b159d199f2`。
  本地保存于 `rag-step5-local-streamlit-fix-20261019/final`，远端保存于
  `/opt/rag-kb/releases/20261019-streamlit-21271bf`。归档各 blob 摘要核验通过。
- 远端核验包哈希、镜像 ID、源提交和 PYTHONPATH 后，备份 release.env，仅更新
  STREAMLIT_IMAGE，使用 `up -d --no-deps --wait frontend` 替换 Streamlit。
  backend、next、nginx 的容器 ID 均保持不变，未操作账本或密钥。
- Tabbit 浏览器先确认线上旧错误，再访问修复后页面，实际显示 RAG知识库首页、
  9 文档、个人额度、四个建议问题、可见聊天输入框；导入异常数量为 0。
  浏览器任务已结束并保留页面。本轮没有提交付费问题。

此前 HTTP 200、WebSocket 101、健康检查只能证明服务可连接，不能证明页面脚本执行成功。
本次补充真实入口执行和浏览器渲染检查，纠正此前公网验收覆盖不足。
不得将旧验收记录理解为完整 Streamlit 浏览器验收。

原始全量交付包不覆盖；[固定清单](step5-fixed-delivery-manifest.json)新增补丁描述和
当前 STREAMLIT_IMAGE 覆盖项。服务器 repository 仍是原固定快照，Streamlit 源码
由本补丁镜像及其独立源码快照追溯；其他服务仍使用原固定镜像。

用户于 2026-10-19 表示已手动确认自动续期任务执行成功；这是用户提供的证据，
本轮未重复读取续期日志或调整调度。此前六份远端运维记录继续保留，未纳入本修复提交。
