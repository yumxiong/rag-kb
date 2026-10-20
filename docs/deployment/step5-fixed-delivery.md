# Step5 本地固定交付清单（2026-10-17）

当前部署状态、用户验收及维护边界见[部署收尾总览](step5-deployment-baseline-20261020.md)。
本文原始交付阶段描述保留用于追溯，不作为当前待办清单。

2026-10-19 Streamlit 单服务补丁已部署：当前 `STREAMLIT_IMAGE=rag-step5-streamlit:21271bf`。
原始 2026-10-17 归档及其他镜像保持不变；恢复部署时须叠加清单的
`current_image_overrides`，不能仅加载旧包恢复有缺陷的 Streamlit。
补丁详情和真实页面验收见 [Streamlit 修复记录](step5-streamlit-import-fix-20261019.md)。

应用源提交：`4d1ba85b46ade64bae52d5c200e3660c2671de0b`。
本次从该提交的 `git archive` 干净快照构建三个 linux/amd64 应用镜像，
Next 构建参数为 `RAG_BACKEND_ORIGIN=http://backend:8000`。
后端和 Streamlit 默认依赖镜像源返回无匹配版本，改用官方 PyPI 后成功；
未更改固定依赖版本。部分传递依赖未完全锁定，因此以本次保存的镜像为交付依据，
不保证日后重新构建逐字节一致。实际 Python 依赖清单保留在交付目录。

## 本次更新

取消固定价格策略到期阻断，策略 `cny-2026-10-17-full-context-v2-no-expiry`
持续有效，价格需要时人工调整。新后端镜像内断网运行金额专项 **33 passed**，
覆盖原到期日、其后及 2030 年继续准入，同时保留 50 元限额和时钟倒退保护。
每日准入按配置单价计算，供应商变价可能使实际账单偏离预留金额。
三个应用镜像均从本次源提交重建；首次因 Docker 引擎未启动而未能构建，启动后成功。
2026-10-16 的旧包保留供追溯，不再作为当前部署候选。

## 固定文件

机器可读清单：[step5-fixed-delivery-manifest.json](step5-fixed-delivery-manifest.json)。
本地交付目录：`rag-step5-local-delivery-20261017/`（Git 忽略）。
仅交付以下文件，不打包整个目录中的构建上下文、日志或其他验收文件：

- `repository.tar`：固定应用源快照，3,266,560 字节。
- `images.tar`：三个应用及 Nginx、Certbot 离线镜像，891,347,456 字节。
- `knowledge-base-v3.tar.gz`：公开 AtlasDesk 9 文档、32 分块，778,103 字节。
- `delivery-manifest.json`、`SHA256SUMS`、`release.env.candidate`。
- `backend-dependencies.txt`、`streamlit-dependencies.txt`。

源快照包含构建时的历史报告及验收脚本；当前清单和本报告在构建验收后另行提交，
以交付目录外置的 delivery-manifest.json 为当前产物清单，不以源快照内旧清单覆盖它。
知识库包含原文、Chroma 索引及逐文件哈希，不包含密钥、金额账本、reference 或证书。
镜像归档的所有 SHA256 blob 均重新校验，标签集合与清单一致。
Docker containerd 的镜像 ID 可能是索引摘要，传统 Docker 显示的 ID 可能是配置摘要；
清单同时记录本机 ID 和配置摘要。目标加载后必须核对标签对应配置摘要，不能仅相信可变标签
（尤其是 Certbot 的本地 `latest` 标签），也不能将本地 ID 宣称为 registry 发布摘要。

## Linux 验收

新后端镜像在 `--network none`、全新 Linux 原生 named volumes 中通过：

- 交付归档 SHA256、成员路径与类型、逐文件哈希校验。
- v3 的供应商、端点、模型、1024 维及索引版本完整身份核对。
- 9 文档、32 个有限值向量读取；32 个自向量 ANN 查询均找回对应分块。
  此项检验索引可读性，语义回答/引用/拒答质量沿用此前真实 v3 回归，不混称新真实接口验收。
- production 模式显式初始化合成账本；个人计次 1、累计预留 3 元、未决请求 1 均跨进程保留；
  剩余额度 47 元，超额预留拒绝。
- 所有使用数据的容器退出后备份 data 与独立 reference，恢复到另一组全新卷；
  恢复文件哈希完全一致，再次读取索引及账本成功，未重置未决金额。
- 既有 Linux 存储故障保护 12 项通过：挂载、reference、损坏账本、第二进程锁、fsync
  和各写入边界失败保护。所有本次临时卷已清理。

入口为 `scripts/acceptance/step5/run_linux_delivery.py`，只允许对可丢弃测试卷运行。
本轮命令：`python scripts/acceptance/step5/run_linux_delivery.py --image rag-step5-backend:4d1ba85 --output rag-step5-local-delivery-20261017`。
结果在交付目录 `linux-results.json` 和 `linux-check.txt`，不含真实密钥或生产账本。
此前完整 Python 测试 739 passed、覆盖率 81.66%；本轮对价格策略修改执行 33 项 Linux 镜像内专项回归及上述交付/恢复重验，
没有重新运行历史前端全范围 lint，也没有执行真实供应商或公网验收。

## 后续部署门槛

下一步是经单独授权后进行远端准备：采用 `/opt/rag-kb`，代码在其 `repository` 目录，
data、config/reference、外置 backend.env、secrets 与证书分别按候选手册布局。
先验宿主目录、磁盘空间与实际 Linux mount source，再校验 SHA256、加载镜像并核对配置摘要。
`release.env.candidate` 的 mount source 是阻断性占位符，不可原样启动。
目标服务器的存储恢复、容量、真实供应商调用和公网入口仍待目标环境验证。

当前交付镜像已采用无固定到期的价格策略，无需定期延期；价格变更由人工维护。
真实验收金额账本 `rag-step5-local-paid-state` 不在本次公开交付包中；必须另行规划安全迁移，
保留已消费及未决金额，并停止旧写入者。不能用本次合成账本替换，也不能直接初始化零账本
从而绕过每日 50 元统一金额准入。

备份以停机后的 data 与独立 reference 配套留存为准；金额账本恢复还须核对备份后消费，
不得回滚预算。当前仅本地手动备份（可选每日保留 7 份），异机灾难恢复未覆盖。
证书使用 `xihuyue@gmail.com` 注册，root 与 next 分开签发；用户手动检查续期与有效期，
不依赖到期邮件。云安全组 80/443 已由用户确认开放。

远端准备、staging/正式签证、应用启动分别授权。本轮未推送、未操作服务器、未申请证书。
