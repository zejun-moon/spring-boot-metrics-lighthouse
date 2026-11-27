# AGENTS.md — 给维护本仓库的 AI Agent

本仓库主要由 AI agent 阅读、执行、改进和沉淀经验。人类维护者负责审核与决策。
**开始任何工作前请先读完本文件（约 4 分钟）。**

## 使命

让任何 AI 助手在**不踩坑**的前提下，把 Spring Boot 微服务的指标接进 Prometheus 和 Grafana。
所有改动都服务于这三点：

1. **准确**：指标口径来自实测，不来自想象
2. **可执行**：能自动判定的就写成脚本，不靠人肉比对
3. **可追溯**：每条结论都能追到一份脱敏实战报告

## 仓库地图

| 路径 | 作用 | 什么时候改 |
|---|---|---|
| `skills/spring-boot-metrics-lighthouse/SKILL.md` | 技能主流程，被 AI 加载 | 流程/原则变化（保持 < 500 行，细节放 references） |
| `skills/.../references/pitfalls.md` | 坑：现象 → 原因 → 处理 | 每遇到一个新问题 |
| `skills/.../references/actuator-and-config.md` | 依赖、management 配置、端口口径 | 新版本行为差异 |
| `skills/.../references/servicemonitor.md` | 采集层：选择器、relabelings、验收 | 新采集方式 |
| `skills/.../references/grafana-dashboard.md` | 面板口径、样式、图例、Table 替代 | 面板调整 |
| `skills/.../references/grafana-api-troubleshooting.md` | Grafana API / 渲染坑 | 新坑 |
| `skills/.../references/istio-metrics.md` | 网格侧指标口径（附带） | Istio 口径更新 |
| `skills/.../scripts/verify-actuator-endpoint.sh` | 端点三态判定 | 判定规则变化 |
| `skills/.../scripts/check-servicemonitor.sh` | 采集层结构校验 | 新增校验项 |
| `skills/.../scripts/gen-dashboard.py` | 12 面板生成器 | 面板口径调整 |
| `skills/.../scripts/verify-dashboard.sh` | 逐条跑查询 | 判定规则变化 |
| `field-reports/` | 每次真实执行的脱敏报告 | **每次真实执行后必写** |
| `tools/check_repo.py` | 仓库自检（结构、版本一致、敏感信息） | 新规则 |
| `tests/test_check_repo.py` | 扫描器单元测试 | 扫描规则变化 |
| `.claude-plugin/` | Claude Code 插件与 marketplace 清单 | 发版时改版本号 |
| `CHANGELOG.md` | 变更记录 | 每个 PR |

## 铁律

1. **绝不提交敏感信息**：真实 IP、域名、主机名、账号、口令、密钥、内部 uid、
   私有镜像仓库地址。示例统一用 `10.0.0.x`、`example.com`。
   提交前必须 `python3 tools/check_repo.py` 通过（CI 还有 gitleaks）。
2. **诚实标注验证状态**：只在真实环境跑通过的才写「已验证」；
   报告与正文里区分 `实测` 与 `推断`。
3. **口径必须能被复现**：写进文档的每条 PromQL / 配置片段，
   都要能说明「为什么是这样」以及「怎么验证它对」。
4. **不写没用的东西**：不写「Prometheus 是 awesome」这类正确但没信息量的内容。
   每个段落都要能帮人**做出判断**。
5. **改行为的事由人决定**：重建业务镜像、改 Grafana 数据源、删除文件夹、
   调采集间隔与保留期 —— 技能里写成「向用户确认」，不写成自动执行。
6. **SKILL.md 只放主流程**：正文 < 500 行，细节一律进 `references/`。
   `tools/check_repo.py` 会验「SKILL.md 引用的路径都存在」。

## 沉淀经验的工作流（最重要）

每次真实执行（无论成败）：

1. 按 `field-reports/TEMPLATE.md` 写 `field-reports/YYYY-MM-DD-<主题>.md`（脱敏），
   并更新 `field-reports/README.md` 的索引表
2. 对报告里每个新问题判断：
   - 以后还会遇到 → 写进 `pitfalls.md`（带「现象 → 原因 → 处理」）
   - 能自动检测 → 在 `scripts/` 里加判定
   - 能自动修复 → 改脚本 + 补测试
   - 只是这一次的特例 → 只留在报告里
3. 在报告的问题小节标注 `状态：promoted → pitfalls.md #N`
4. 更新 `CHANGELOG.md` 的 `[Unreleased]` 段

## 本地自检

```bash
python3 tools/check_repo.py              # 结构、版本一致、敏感信息
python3 -m unittest discover -s tests    # 扫描器单元测试
find . -name '*.sh' -not -path './.git/*' -print0 | xargs -0 -n1 bash -n
python3 skills/spring-boot-metrics-lighthouse/scripts/gen-dashboard.py \
    --datasource-uid test --namespace example-ns --output /tmp/d.json
```

## 提交与发版

- 分支 + PR；Conventional Commits（`feat:`、`fix:`、`docs:`、`pitfall:`、`report:`、`ci:`）；squash 合并
- PR 描述说清楚：改了什么、为什么改、验证状态（实测 / 推断 / 未测）
- 发版（semver）：
  1. 同步修改 `.claude-plugin/plugin.json` 的 `version`，以及 `marketplace.json` 里的
     `metadata.version` 和 `plugins[0].version`
  2. 把 `CHANGELOG.md` 的 `[Unreleased]` 改成新版本号
  3. `check_repo.py` 会校验三处版本号与 CHANGELOG 一致
  4. 提 PR，CI 通过后合并；打 `vX.Y.Z` 标签
- 分支：仓库只长期保留 `main`。PR 合并后分支自动删除；main 有保护，必须通过 CI

## 常见任务 → 去哪里

| 任务 | 入口 |
|---|---|
| 给某个服务接指标 | 加载技能，按 `SKILL.md` 执行，结束后写 field report |
| 遇到没见过的报错 | 先搜 `pitfalls.md`，再搜 `field-reports/` |
| 加一个新面板 | 改 `gen-dashboard.py` 的 `ITEMS`，跑冒烟测试，更新 `grafana-dashboard.md` 的口径表 |
| 改采集范围 | `servicemonitor.md` + `check-servicemonitor.sh` 加校验项 |
| 改扫描规则 | `tools/check_repo.py` + `tests/test_check_repo.py` **同时**改，并补阳性样本 |
| 判断能不能发布 | `python3 tools/check_repo.py` 退出码 0 |
