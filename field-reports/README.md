# 实战报告索引

> 每次**真实执行**（不论成败）都写一份**脱敏**报告。
> 报告是原始素材，`references/pitfalls.md` 是提炼后的结论 —— 两边都要有。

| 日期 | 报告 | 结果 | 覆盖 |
|---|---|---|---|
| 2026-11-12 | [5 个 Spring Boot 微服务首次接入 Prometheus + Grafana](2026-11-12-springboot-metrics-onboarding.md) | success | 采集层三个坑 + 展示层六个口径坑 + Grafana 环境坑 |
| 2026-11-25 | [Grafana 面板排障：三个「看起来像数据问题」的配置问题](2026-11-25-grafana-panel-debugging.md) | success | `decimals`+noValue、全屏截图假象、NFS 上改文件夹名挂死 |

## 写报告的规矩

1. 用 [`TEMPLATE.md`](TEMPLATE.md) 的 frontmatter 字段
2. **脱敏**：真实 IP → `10.0.0.x`；内网域名 → `example.com`；
   真实 ns / uid / 私有仓库地址 / 人名 → 一律替换
3. **失败样本比成功样本值钱** —— 记清楚「当时为什么判断错了」，
   而不是只记最后怎么修好的
4. 报告里标 `状态：promoted → pitfalls.md #N`，表示已提炼进坑表
5. 新增报告后**必须同步更新这个索引表**（`tools/check_repo.py` 会验）
