# CHANGELOG

本文件记录本仓库的所有重要变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 待办

- 补充 OpenTelemetry Collector 路径（当前只覆盖 Prometheus 抓取）
- 补充告警规则设计（当前只覆盖「看图」，不含告警）
- `verify-dashboard.sh` 增加对 instant 查询与 range 查询的区分处理

## [0.1.0] - 2026-11-27

首个版本：从一次真实的 Spring Boot 微服务指标接入实战中提炼。

### 新增

- **技能主流程** `skills/spring-boot-metrics-lighthouse/SKILL.md`
  —— 四步流程（确认来源 → 服务侧 → 采集层 → 展示层）+ 排障入口 + 边界声明
- **坑表** `references/pitfalls.md` —— 25 条实测坑，分采集层 / 展示层 / Grafana API / 环境侧四组，
  每条含「现象 → 原因 → 处理」
- **参考文档**
  - `actuator-and-config.md` —— 依赖、management 配置、端口口径、指标名对照
  - `servicemonitor.md` —— ServiceMonitor / PodMonitor / 注解三种采集方式 + relabelings 配方 + 三层验收
  - `grafana-dashboard.md` —— 12 面板口径表、样式配方、图例列选择、Table 面板替代方案
  - `grafana-api-troubleshooting.md` —— Grafana API / 渲染的 6 个坑
  - `istio-metrics.md` —— Istio 网格侧指标口径（附带章节）
- **脚本**
  - `verify-actuator-endpoint.sh` —— 端点三态判定（真指标 / 假阳性 200 / 404）
  - `check-servicemonitor.sh` —— 采集层结构与白名单校验
  - `gen-dashboard.py` —— 12 面板 dashboard 生成器（uid / ns / 维度标签 / 服务白名单全参数化）
  - `verify-dashboard.sh` —— 逐条跑 panel 查询，标出空结果
- **脱敏自检**
  - `tools/check_repo.py` —— 结构 / 版本一致 / 报告索引 / 敏感信息四类检查
  - `tests/test_check_repo.py` —— 扫描器阳性阴性样本单测
- **实战沉淀**
  - `field-reports/2026-11-12-springboot-metrics-onboarding.md`
  - `field-reports/2026-11-25-grafana-panel-debugging.md`
- **工程化**
  - `.claude-plugin/plugin.json` + `marketplace.json` —— 可作为 Claude Code 插件安装
  - `.github/workflows/ci.yml` —— 自检 + 单测 + shell 语法 + 生成器冒烟 + gitleaks
  - `AGENTS.md` / `CLAUDE.md` / `CONTRIBUTING.md` / `SECURITY.md` / `ROADMAP.md`
