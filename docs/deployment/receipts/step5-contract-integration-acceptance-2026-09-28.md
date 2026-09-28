# 第 1 步 integration 契约接受回执

来源：2026-09-28 用户转交的 integration 复审结论；本文为 deploy 归档记录，不是 integration worktree 文件快照。

接受版本：`anonymous-quota-v1-draft.2`。
双方确认的协议正文提交：`0f6ecf2ff2cec29158ea81616d6dbed4480dd67c`。

> integration 复审结论：接受 anonymous-quota-v1-draft.2，固定提交为 0f6ecf2ff2cec29158ea81616d6dbed4480dd67c。 上次提出的两项问题已闭合：过期身份的恢复请求有明确上限，且不会自动重放问答；账本提交边界、首次建账和持久卷缺失时的拒绝启动规则也已写明。未发现新的契约阻塞项。
>
> deploy 可以将此作为第 1 步的 integration 接受回执，记录双方确认的提交并冻结契约，然后进入第 2 步。此确认仅针对文档协议；功能实现、故障注入和两套前端的真实联调仍须按清单验收。本次只做静态复审，未修改 worktree 或运行功能测试。

deploy 接受上述同一协议正文并将其状态冻结；版本标识保留 draft.2 以对应已确认的固定提交，不改变协议行为。后续行为变化必须另行递增版本并评审。第 0 步基线回执仍仅代表基线接收。
