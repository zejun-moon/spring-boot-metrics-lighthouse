# spring-boot-metrics-lighthouse

🗼 **A lighthouse for Spring Boot metrics** —— 把 Spring Boot 微服务的运行指标接入
Prometheus，并在 Grafana 上做出**能用来判断问题**的面板。

不是「Prometheus 教程」，是**一次真实接入实战的沉淀**：每一条口径都踩过坑，
每一个坑都写清了「现象 → 原因 → 处理」。

```
采集：/actuator/prometheus  ←  micrometer-registry-prometheus  ←  ServiceMonitor
展示：12 面板 dashboard     ←  逐条验收过的 PromQL
```

## 为什么不是知识库

| | 知识库 | 本技能仓 |
|---|---|---|
| 形态 | 长篇散文 | 可执行脚本 + 判据表 |
| 检索 | AI 全文捞关键词，容易漏 | 按步骤走，每步有判定条件 |
| 验证 | 说不清哪句是对的 | **每条标注「实测 / 推断」** |
| 失败样本 | 通常不写 | **专门记**（每次误判的起点） |
| 更新 | 靠人记得改 | `CHANGELOG` + CI + 语义化版本 |
| 保密 | 容易夹带真实信息 | `check_repo.py` 硬扫 + gitleaks |

## 快速开始

```bash
# ① 克隆（AI 也能直接读这个仓）
git clone https://github.com/zejun-moon/spring-boot-metrics-lighthouse.git

# ② 读主流程
cat spring-boot-metrics-lighthouse/skills/spring-boot-metrics-lighthouse/SKILL.md

# ③ 排障先查坑表
grep -n "现象" spring-boot-metrics-lighthouse/skills/spring-boot-metrics-lighthouse/references/pitfalls.md
```

### 给 AI 用

把 `skills/spring-boot-metrics-lighthouse/` 放进你的 skills 目录，
或在 Claude Code 里作为插件安装：

```bash
claude plugin install ./spring-boot-metrics-lighthouse
```

SKILL.md 的 frontmatter 里写了**中英双语触发词**，
提到「微服务监控」「ServiceMonitor target 为 0」「actuator/prometheus 404」
「Grafana 面板没数据」等场景时，AI 应当自动加载本技能。

### 自己跑一遍

```bash
# 端点是不是真的有指标（三态判定）
bash skills/spring-boot-metrics-lighthouse/scripts/verify-actuator-endpoint.sh \
     --url http://<svc>.<ns>.svc.cluster.local:8080/actuator/prometheus

# 采集层配置对不对
bash skills/spring-boot-metrics-lighthouse/scripts/check-servicemonitor.sh \
     --file ./my-servicemonitor.yaml --expect-services svc-a,svc-b

# 生成 12 面板 dashboard
python3 skills/spring-boot-metrics-lighthouse/scripts/gen-dashboard.py \
     --datasource-uid <prom-uid> --namespace <ns> --services svc-a,svc-b \
     --output dashboard.json

# 逐条验收查询（导入成功 ≠ 面板有数据）
bash skills/spring-boot-metrics-lighthouse/scripts/verify-dashboard.sh \
     --dashboard dashboard.json --prometheus http://<prom>:9090
```

## 目录结构

```text
skills/spring-boot-metrics-lighthouse/
  SKILL.md                      # 主流程：四步 + 排障入口 + 边界
  references/
    pitfalls.md                 # 25 条实测坑（先查这里）
    actuator-and-config.md      # 依赖 / management 配置 / 端口口径 / 指标名对照
    servicemonitor.md           # 三种采集方式 + relabelings 配方 + 三层验收
    grafana-dashboard.md        # 12 面板口径表 + 样式 + 图例列 + Table 替代
    grafana-api-troubleshooting.md
    istio-metrics.md            # 网格侧口径（附带）
  scripts/
    verify-actuator-endpoint.sh
    check-servicemonitor.sh
    gen-dashboard.py
    verify-dashboard.sh
field-reports/                  # 脱敏实战报告（含失败样本）
tools/check_repo.py             # 脱敏与结构自检
tests/                          # 扫描器单元测试
```

## 覆盖范围

✅ Spring Boot 2/3 · actuator + micrometer · ServiceMonitor / PodMonitor / 注解抓取 ·
kube-prometheus-stack · Grafana 10.x dashboard 生成与验收

❌ OpenTelemetry Collector 链路 · 非 Operator 的自定义 Prometheus Operator 配置 ·
告警规则设计 · 非 Spring Boot 语言的指标接入

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。核心要求：
**先写脱敏报告，再把结论提炼进 `references/pitfalls.md`**，
提交前 `python3 tools/check_repo.py` 必须退出码 0。

## 许可

[MIT](LICENSE)
