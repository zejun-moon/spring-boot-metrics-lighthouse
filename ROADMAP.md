# ROADMAP

> 本文件记录**下一步要做什么**，以及每条为什么值得做。
> 已完成的部分见 [CHANGELOG.md](CHANGELOG.md)。

## v0.2.0 · 采集方式补全

- [ ] **PodMonitor 完整配方** —— 现在只在 `servicemonitor.md` 里带了一段，
      应独立成章（选的是 Pod label，不是 Service）
- [ ] **裸 Prometheus 注解版** —— 同样只带了一段，扩容
- [ ] **独立 management 端口的完整方案** —— 含 Service/ServiceMonitor 的配套改动
      （现在只有一句「生产推荐」）
- [ ] **`verify-actuator-endpoint.sh` 支持多端点批量探测**

## v0.3.0 · 验收自动化

- [ ] **一键验收脚本**：给定 ns + ServiceMonitor 名 + dashboard JSON，
      自动跑完「端点 → 采集 → 查询 → 渲染」四层
- [ ] **空面板自动归因**：不只报「空结果」，还要按
      「指标名不存在 / 标签不对 / 真的没事件」给出候选原因
- [ ] **Grafana 渲染层校验**：检查 `gridPos` 是否重叠、
      `decimals` 是否被误设、`sortBy` 是否写了 reducer id

## v0.4.0 · 覆盖面

- [ ] **OpenTelemetry Collector 路径** —— 现在的采集假设是
      「Prometheus 直接抓 actuator」，OTel Collector 是另一条链路
- [ ] **告警规则** —— 「看图」之外，「什么时候该叫人」
- [ ] **非 Spring Boot 语言** —— Go / Node / Python 服务的指标接入

## 待定

- **多集群 / 多环境**：现在所有示例都是单集群。
  多集群下 `namespace` 与标签的聚合方式要重新设计。
- **与故障速查面板的联动**：本技能只管「正常态看板」，
  故障态看板（场景 → 信号 → 现象）属于另一条工作线。
- **性能**：12 个面板 × 多个服务 × 高基数 URI 的查询成本评估。

## 已知缺口

| 缺口 | 影响 |
|---|---|
| 没有真实 P95 | Micrometer 默认无 `_bucket`；开 histogram 是容量变更，需确认 |
| 标签不齐时跨服务聚合会裂 | 部分服务在代码里加了 `application` 标签，部分没有 |
| 没有覆盖 `tomcat_threads_*` | Micrometer 默认不暴露；要用得显式配置 |
| Istio 部分是附带章节 | 网格侧内容尚未定稿，单独抽技能更合适 |
