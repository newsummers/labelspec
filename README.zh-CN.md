# LabelSpec

[English](README.md)

LabelSpec 将自然语言业务标准编译为有版本、可执行、可追溯的 Rule，用于可靠的单标签文本分类。

系统沉淀的核心资产不是 Prompt 或某个模型，而是 Definition、Boundary、Priority Rules，以及持续推动这些 Rule 进化的真实 Case。

```text
Standard -> Data -> Model -> Failure -> Standard
```

## 功能

- 同时上传 MD、TXT、DOCX、文本型 PDF、CSV、XLSX 标准文档
- 分文档抽取并合并 Definition、Boundary、Priority，保留来源引用并识别冲突
- 支持任意深度标签树，最终结果只允许没有子节点的叶子标签
- 每个节点维护局部 Definition，分类时自动继承完整祖先定义链
- 通过标签树逐层召回候选，再披露相关 Boundary、Priority 和历史 Case
- 手动新增、修改、删除或移动标签及规则，每次保存创建不可变版本和字段级变更记录
- 校验树结构、Rule ID 唯一性、Label 引用、规则作用域和来源冲突
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
labelspec compile standard.md supplemental-boundaries.docx --name "客户意图" --output-dir ./compiled
labelspec activate <standard-id>
labelspec import-data cases.csv
labelspec annotate <dataset-id> <standard-id>
labelspec mine <run-id>
labelspec revise <standard-id> <rule-id> edited-rule.json --reason "人工确认的修改"
labelspec impact-rerun <source-run-id> <target-standard-id> <rule-id>
labelspec export-results <run-id> results.jsonl --gold-only
```

Web 工作台内置金融/汽车演示标准和 CSV 数据。导入演示数据不会绕过模型 API Key 要求。

### 数据集格式

Web 和 CLI 的数据集导入支持 CSV、XLSX、TXT、JSONL/NDJSON，推荐使用 CSV。CSV/XLSX 的表头必须包含 `text`，可选 `gold_label`；JSONL 每行必须是包含 `text` 的对象；TXT 每行作为一条 `text`，不支持 `gold_label`。系统会自动为每条记录生成内部 ID，用户无需填写 `id`。其他字段会保存在 metadata 中。

Web 数据页提供一个包含 `text,gold_label` 表头的 CSV 模板；`gold_label` 可以留空。`text` 是待分类文本，`gold_label` 是可选的人工真实标签，用于评估和规则改进。

未创建过标注运行的数据集可以在 Web 界面删除；已有标注运行的数据集为保留历史记录不能删除。

## 数据与费用

业务标准和待标注文本会发送给用户配置的千帆模型。处理生产或敏感数据前，请确认千帆平台的数据、保留、配额和计费政策。本地工作数据默认保存在 `backend/data/labelspec.db`。

## 范围

v0.2 只支持单标签文本分类；叶子标签可处于任意层级。扫描 PDF 暂不支持 OCR，系统不负责模型训练或 Fine-tuning。

## License

Apache License 2.0，详见 [LICENSE](LICENSE)。
