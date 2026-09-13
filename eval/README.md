# 检索评测工具

本目录保留检索、评分、对比和校验工具。旧版 `eval_set.json`、
`eval_set_v1.json`、`eval_set_v2.json`、`eval_set_v3.json` 及其旧评分产物
依赖私人笔记，已移出当前版本的跟踪范围；已有本地副本由 Git 忽略。
旧成绩不作为公开、可复现的评测证据。

`evaluate_retrieval.py`、`evaluate_retrieval_v1.py`、
`evaluate_retrieval_v2.py` 和 `run_retrieval.py` 的默认入口仍使用上述本地题集。
新克隆不包含这些文件或对应私人语料，不能直接复现这些历史运行。
离线评分与校验测试使用自建测试数据，不需要恢复私人题集。

公开语料和题集正在独立准备与人工审核，当前分支尚未提供公开基线。
请勿为补齐历史评分的引用上传私人 `run.json`、语料、题集或摘录；
未来公开运行产物须逐文件审核后纳入版本控制。
