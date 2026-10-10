# EnterpriseMind 自动评估设计

## 目标

评估中心用于持续验证 Agent 的业务正确性和运行质量。它实际调用与线上聊天相同的 LangGraph、RAG 和业务工具，不使用写死的展示数字，也不依赖额外评测模型。

## 内置回归集

当前包含 6 个不会修改订单、退款或工单的用例：

| 用例 | 预期意图 | 关键校验 |
| --- | --- | --- |
| 订单查询与权限工具 | `order` | 订单号、金额、`query_order` |
| 物流节点查询 | `logistics` | 承运商、物流节点、`query_logistics` |
| 商品价格与库存 | `product` | 商品名、价格、`search_products` |
| 保修政策 RAG | `knowledge` | 保修事实、政策文档、`hybrid_retrieval` |
| 电子发票 RAG | `knowledge` | 企业名称、纳税人识别号、政策文档 |
| 客服规范 RAG | `knowledge` | 服务原则、禁止行为、客服规范文档 |

评测过程使用临时会话。每个用例结束后删除临时会话和 AgentRun，避免污染普通用户的会话数量和运行统计；最终结果单独保存到 `evaluation_runs`。

## 指标口径

### 回答正确率

每个用例标注必须出现的关键事实，按命中比例计算单题得分；总指标是全部用例得分的算术平均。关键事实命中至少 50%，且其他强约束通过时，该用例才算通过。

### 引用来源准确率

只统计需要知识库引用的用例。返回引用中至少包含一个被标注为可接受的文档时记为 100%，否则为 0%。

### 工具调用成功率

逐题检查预期工具是否出现在执行轨迹中，且状态为 `success`、`completed` 或 `existing`。总指标为各用例工具得分的平均值。

### 延迟

从进入 `run_customer_agent` 到 LangGraph 返回并生成运行记录的端到端毫秒数，不只计算模型网络时间。

### Token 与成本

模型调用读取 OpenAI-compatible 响应中的：

- `prompt_tokens` 或 `input_tokens`；
- `completion_tokens` 或 `output_tokens`；
- `cost` 或 `total_cost`。

若供应商没有返回 cost，则按照 `LLM_INPUT_COST_PER_MILLION` 与 `LLM_OUTPUT_COST_PER_MILLION` 估算。模型未启用时 Token 和成本均为真实的 0。

### 用户满意度

满意度 = 点赞数 ÷（点赞数 + 点踩数）。没有任何反馈时显示“暂无数据”，不会默认展示 100%。

## 结果解释

评估中心保留最近 20 次运行，并展示每题问题、Agent 答案、实际意图、引用文档、工具轨迹、延迟、Token 和失败原因。固定回归集适合作为提交前质量门禁；后续可以扩展为数据库维护的评测集、CI 阈值阻断和人工标注工作流。
