# LabelSpec

[English](README.md)

LabelSpec 将自然语言业务标准编译为有版本、可执行、可追溯的 Rule，用于可靠的单标签文本分类。

系统沉淀的核心资产不是 Prompt 或某个模型，而是 Definition、Boundary、Priority Rules，以及持续推动这些 Rule 进化的真实 Case。

```text
Standard -> Data -> Model -> Failure -> Standard
```

## 功能

- 将自由编写或基于模板的 `standard.md` 编译为三个 YAML 文件
- 校验 Rule ID 唯一性、Label 引用和 Rule 内容完整性
- 通过标签地图、Definition、Boundary、Priority、历史 Case 渐进式披露规则
- 独立运行 Annotator 与 Verifier，再以确定性逻辑完成结果分流
- 输出 `AUTO_ACCEPT`、`REVIEW`、`AMBIGUOUS`、`SPEC_GAP`
- 聚类重复失败并生成需要人工审核的 Rule 修改建议
- 生成不可变 Standard 版本，只重跑受影响数据
- 对比准确率、自动通过率、人工审核率和 Rule 冲突率
- 提供中文 Web 工作台与 CLI

## 环境要求

- Python 3.9+
- Node.js 20+
- 百度智能云千帆 ModelBuilder API Key

LabelSpec 不提供模拟模型。标准编译、标注、校验、Embedding 和 Spec Gap 挖掘都必须使用真实 API Key。

## 快速开始

```bash
git clone <你的仓库地址>
cd labelspec
make install
cp .env.example .env
```

在 `.env` 中配置：

```dotenv
QIANFAN_API_KEY=bce-v3/your-api-key
```

构建前端并启动：

```bash
make run
```

访问 [http://127.0.0.1:8000](http://127.0.0.1:8000)，API 文档位于 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

API Key 只由后端读取，不进入浏览器或 SQLite。用户可以在 UI 中分别选择标准编译、标注、校验、Spec Gap 和 Embedding 模型。

## 本地开发

分别在两个终端运行：

```bash
make dev-backend
make dev-frontend
```

执行测试与生产构建：

```bash
make test
```

## CLI

```bash
labelspec --help
labelspec settings
labelspec compile standard.md --name "客户意图" --output ./compiled
labelspec activate <standard-id>
labelspec import-data cases.csv
labelspec annotate <dataset-id> <standard-id>
labelspec mine <run-id>
labelspec revise <standard-id> <rule-id> edited-rule.json --reason "人工确认的修改"
labelspec impact-rerun <source-run-id> <target-standard-id> <rule-id>
labelspec export-results <run-id> results.jsonl --gold-only
```

Web 工作台内置金融/汽车演示标准和 CSV 数据。导入演示数据不会绕过模型 API Key 要求。

## 数据与费用

业务标准和待标注文本会发送给用户配置的千帆模型。处理生产或敏感数据前，请确认千帆平台的数据、保留、配额和计费政策。本地工作数据默认保存在 `backend/data/labelspec.db`。

## 范围

v0.1 只支持单标签文本分类，不负责模型训练或 Fine-tuning。

## License

Apache License 2.0，详见 [LICENSE](LICENSE)。
