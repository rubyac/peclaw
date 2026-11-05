# 评测回归

实际指标与队列测试位于 tests/unit/test_evaluation_scoring.py 和 tests/integration/test_evaluation.py；浏览器流程见 apps/web/tests/evaluation.spec.ts。

在 services/api 执行 `uv run python -m app.evaluation.demo --output /tmp/peclaw-eight-demos`，运行固定八项演示的十五个测试节点并生成清单、结果和范围声明。需要完整开发依赖及本地 PostgreSQL/S3 服务。合成协议用例不代表真实模型效果；缺失或跳过测试会失败。说明见 docs/EVALUATION.md。
