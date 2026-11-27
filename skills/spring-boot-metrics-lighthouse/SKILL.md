---
name: spring-boot-metrics-lighthouse
license: MIT
description: 把 Spring Boot 微服务的运行指标接入 Prometheus 并在 Grafana 做出可读面板——actuator 端点、micrometer-registry-prometheus 依赖、management 配置、ServiceMonitor/PodMonitor 采集、dashboard 生成与逐条验收。凡是用户提到「微服务监控」「Prometheus 抓不到 Spring Boot 指标」「ServiceMonitor target 为 0」「actuator/prometheus 404」「Grafana 面板没数据」「加 JVM/HTTP/连接池/日志级别指标」「micrometer」「给服务加监控」「指标采集不生效」「连接池或 GC 怎么画」「P95 怎么算」等场景，都要用本技能——即使用户没说「监控」而只说「看不到服务的运行状况」「看不到内存和 GC」「这个服务到底是活着还是死了」。Spring Boot microservices metrics to Prometheus and Grafana: actuator endpoints, micrometer registry, management config, ServiceMonitor/PodMonitor scraping, dashboard generation and per-query verification.
---

# Spring Boot 微服务指标接入（Prometheus + Grafana）

一套**已经在真实环境跑通并逐条验收过**的接入流程：从「服务里没有指标」到「Grafana 上一块能判断问题的面板」。

本技能沉淀自一次 Spring PetClinic 形态的 5 服务微服务集群接入实战（2026-11 实测），
覆盖 actuator → micrometer → ServiceMonitor → Grafana 全链路，含 **25 条踩过的坑**。

## 什么时候不要用本技能

- 业务里是 **Go / Node / Python** 服务 → 用对应语言的 exporter，不要强上 actuator
- 指标已经接好了，问题是 **Grafana 本身崩了 / 数据源连不上** → 那是 Grafana 侧问题，见 `references/grafana-api-troubleshooting.md`
- 要做的是 **链路追踪（trace）** → 指标（metrics）与链路（traces）是两条链路，本技能只管指标；`references/istio-metrics.md` 附带了网格侧指标口径

---

## 第 0 步 · 先确认「指标从哪来」

**不要跳过这步。** 指标的来源决定后面所有动作。

| 采集方式 | 用在哪 | 你需要准备的对象 |
|---|---|---|
| **ServiceMonitor** | 已有 Service、端口是 `http` 之类命名端口 | Service + ServiceMonitor CR |
| **PodMonitor** | 只有 Pod、没有 Service，或要抓 sidecar 之类非 Service 端点 | PodMonitor CR（按 label 选 Pod） |
| **annotations 抓取** | Prometheus 不是 Operator（裸 Prometheus） | Pod 上的 `prometheus.io/scrape` 等注解 |

本技能主流程走 **ServiceMonitor**（最常见的 kube-prometheus-stack 场景）。
裸 Prometheus 请参考 `references/servicemonitor.md` 末尾的注解版配方。

**同时确认 Prometheus 侧怎么选对象**——这是**最容易静默失效**的地方：

```bash
# ServiceMonitorSelector / PodMonitorSelector 长什么样，标签必须命中它
kubectl get prometheus -n <monitoring-ns> -o jsonpath='{.spec.serviceMonitorSelector}{"\n"}'
kubectl get prometheus -n <monitoring-ns> -o jsonpath='{.spec.podMonitorSelector}{"\n"}'
```

常见值是 `matchLabels: {release: kube-monitor}`（kube-prometheus-stack 默认）。
**你的 ServiceMonitor 上必须带这个 label，否则对象存在、不报错、target 数 = 0**（见坑 #1）。

---

## 第 1 步 · 服务侧：让 actuator 真的有指标

### 1.1 依赖

```xml
<dependency>
  <groupId>io.micrometer</groupId>
  <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
```

**只有 `micrometer-core` 不够。** `actuator` + `micrometer-core` 都在镜像里了，但缺
`micrometer-registry-prometheus` 时 `/actuator/prometheus` 返回 **404**——
此时**不是**「没装 actuator」（坑 #3）。

> ⚠️ 加依赖意味着**要重建镜像**。先确认业务镜像是否已有这个 jar：
> `kubectl exec <pod> -- sh -c 'ls /*.jar | head; unzip -l /app/app.jar | grep micrometer-registry-prometheus'`。
> 若业务镜像不能重建，退而求其次用 PodMonitor + 自建 exporter。

### 1.2 management 配置

```yaml
management:
  endpoint:
    prometheus:
      enabled: true
  metrics:
    export:
      prometheus:
        enabled: true
  endpoints:
    web:
      exposure:
        include: '*'
```

采集路径是 **`/actuator/prometheus`**，`/metrics` **一律 404**（Spring Boot 没有这个路径）。

**端口口径**（坑 #11，很隐蔽）：如果 `server.port: 0`（随机端口），
真实端口由 `config/<app>.yml` 覆盖，且**只在 `docker` profile 下生效**。
用 ServiceMonitor 抓的时候，抓的是 **Service 的 targetPort**，不是 actuator 独立端口。

### 1.3 验证端点真的出指标

```bash
bash scripts/verify-actuator-endpoint.sh --url http://<svc>.<ns>.svc.cluster.local:<port>/actuator/prometheus
```

脚本会区分三种情况：**真指标**（含 `# HELP` / `# TYPE`）、**假阳性 200**（返回 JSON —— 典型是
config-server 把路径当 `{application}/{profile}` 解析了，坑 #2）、**404**。

---

## 第 2 步 · 采集层：ServiceMonitor

核心就三个要点，每个都对应一条真实踩过的坑：

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: <app>-services
  namespace: <app-ns>
  labels:
    release: kube-monitor        # ① 少了这行 → 被 serviceMonitorSelector 静默丢弃
spec:
  namespaceSelector:
    matchNames: [<app-ns>]
  selector: {}                    # ② 业务 Service 没 label → 空选 + relabelings 白名单
  endpoints:
    - port: http
      path: /actuator/prometheus  # ③ 不是 /metrics
      interval: 15s
      scrapeTimeout: 10s
      relabelings:
        - sourceLabels: [__meta_kubernetes_service_name]
          regex: "svc-a|svc-b|svc-c"
          action: keep
        - sourceLabels: [__meta_kubernetes_service_name]
          targetLabel: service
          action: replace
```

**为什么 selector 留空？** 业务 Service 常常**一个 label 都没有**，
`matchLabels` / `targetLabels` 都用不了（坑 #4）。而同一 ns 里除数据库外
**所有 Service 的端口都叫 `http`**（坑 #5），只写 `port: http` 会把
admin-server / config-server / grafana-server 一起抓进来。
→ 空 selector 全选，再用 `__meta_kubernetes_service_name` 精确 `keep`。

**为什么 relabeling 要把 service 名提到 `service` 标签？**
Grafana 面板要按服务聚合，Prometheus Operator 自动打的 `job` 标签在
不同 Operator 版本里可能带额外后缀（`job="svc/instance"`），**不要依赖 `job`**，
用自己定义的 `service` 标签。

### 验收采集层

```bash
bash scripts/check-servicemonitor.sh --namespace <app-ns> --name <app>-services \
    --expect-services svc-a,svc-b,svc-c
```

再在 Prometheus 侧确认 target 与序列（**target up ≠ 有指标序列**）：

```bash
# target 是否 up
kubectl -n <monitoring-ns> exec <prometheus-pod> -- \
  wget -qO- 'http://localhost:9090/api/v1/targets?state=active' | \
  jq '.data.activeTargets[] | {scrapePool, health, lastError}'
# 是否有指标序列
kubectl -n <monitoring-ns> exec <prometheus-pod> -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=up{service="svc-a"}' | jq .data.result
```

---

## 第 3 步 · 展示层：Grafana 面板

### 3.1 生成而不是手搓

```bash
python scripts/gen-dashboard.py \
    --datasource-uid <prom-uid> \
    --namespace <app-ns> \
    --services svc-a,svc-b,svc-c \
    --output dashboard.json
```

生成器产出的面板口径**已按实测校正**，直接抄会踩的坑：

| 监控项 | 口径 | 为什么不能照抄官方示例 |
|---|---|---|
| 响应时间 | **平均 + 最大**两个口径 | Micrometer 默认只暴露 `_count/_sum/_max`，**没有 `_bucket`** → 算不了 P95 |
| 线程数 | 用 `jvm_threads_live_threads` | **没有 `tomcat_threads_*`** |
| JVM 内存 | 只画「堆 / 非堆已用」 | `jvm_memory_max_bytes` 里 G1 Eden/Survivor 的 max 是**负数**（无界），sum 后抵消成 0，画上限线没意义 |
| 错误率 | `A or 0 * B` 写法 | 没有 5xx 时整个表达式为空 → **图看起来像坏了** |
| 错误日志速率 | 只列峰值 | 错误是稀疏事件，当前值常年为 0 |
| GC 暂停 | 峰值 + 当前 + **累计** | 累计暂停才是关键 |

### 3.2 样式与图例

- **细线无填充**：`drawStyle=line` / `lineWidth=1` / `fillOpacity=0` / `gradientMode=none`
- 样式字段在 **`fieldConfig.defaults.custom`** 下（图例在**面板级** `options.legend`）——
  查顶层会误判成「没生效」（坑 #14）
- **图例用 table 模式放右侧**：`displayMode=table` + `placement=right`
  → 点一行能在图里只看那条线（Grafana 原生隔离行为）
- **图例的统计列按监控项选**，不是清一色 `Max|Last`：多数 `max+lastNotNull`、
  GC 暂停 `max+sum`、日志级别分布 `lastNotNull`、错误速率 `max`
- `options.legend.sortBy` 写的是**列的显示名**（`Max` / `Last *` / `Total`），
  **不是** reducer id（`max` / `lastNotNull` / `sum`）——写错就静默不排序（坑 #15）

> ⚠️ **Grafana 10.x 的 legend 表头文字改不了**：第一列恒为字面量 `Name`
> （源码写死，非 i18n key，换中文界面也是英文），统计列名取自 reducer 注册表的固定英文名。
> 想用中文表头只能换成 **Table 面板**（列名可任意自定义），代价是失去 legend 的点击隔离。
> 生成器里 `USE_EXTRA_TABLE` 开关可以随时切。

### 3.3 导入

```bash
curl -sS -X POST "$GRAFANA/api/dashboards/db" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d @<(jq -n --slurpfile d dashboard.json \
        '{dashboard:$d[0], folderUid:"<folder-uid>", overwrite:true}')
```

三个坑（详见 `references/grafana-api-troubleshooting.md`）：

1. Grafana 10.x 用 **`Authorization: Bearer <token>` 请求头**，不是 `params.auth`
2. `POST /api/ds/query` **必须带顶层 `from`/`to`**，缺了不报错但 `frames` 为空（看着像「没数据」）
3. **别用 `PUT /api/folders/:uid` 改文件夹名** —— SQLite 在 NFS 上时
   `database is locked` 挂死；要改名就「新建文件夹 → 导 dashboard → 删旧文件夹」

### 3.4 逐条验收（不能只看「导入成功」）

导入成功 **≠** 面板有数据。用 `scripts/verify-dashboard.sh` 把每个查询跑一遍：

```bash
bash scripts/verify-dashboard.sh --dashboard dashboard.json --prometheus http://<prom>:9090
```

它会逐条执行 panel 的 PromQL，标出**空结果**的表达式。
**空结果的面板绝大多数不是 Grafana 的问题，而是指标口径不对**（见坑 #7/#8/#10）。

---

## 第 4 步 · 排障入口

| 现象 | 先看 | 大概率原因 |
|---|---|---|
| target 数 = 0，但对象存在 | `references/pitfalls.md` #1 | ServiceMonitor 缺 `release` 标签 |
| target up 但查不到序列 | `references/pitfalls.md` #2 #7 | 抓到的是假阳性 200 / 服务没装 registry |
| `/actuator/prometheus` 404 | `references/pitfalls.md` #3 | 缺 `micrometer-registry-prometheus` |
| 抓到不该抓的服务 | `references/pitfalls.md` #4 #5 | selector 与端口名撞车 |
| 面板空图但服务活着 | `references/pitfalls.md` #8 #10 | 表达式口径不对 / 标签不齐 |
| 图例表头是英文 | `references/pitfalls.md` #15 | Grafana 写死，改不了 |
| Grafana 改文件夹名 500 | `references/grafana-api-troubleshooting.md` | NFS 上 SQLite 锁死 |
| Y 轴冒出 `noValue` 文案 | `references/grafana-api-troubleshooting.md` | 面板设了 `decimals` |

**排障顺序**：`脚本层`（端点有没有指标）→ `采集层`（target up / 标签对不对）→
`查询层`（PromQL 单条跑有没有数据）→ `展示层`（Grafana 样式/图例）。
**从左往右逐层排除，不要在 Grafana 里瞎调样式。**

---

## 边界与人工决策

以下动作**会改变业务行为**，本技能只提示、**不自动执行**，一律向用户确认：

- 重建业务镜像（加 micrometer 依赖）→ 影响发布链路
- `management.endpoints.web.exposure.include: '*'` → **会同时暴露 env / threaddump / sbom**，
  与业务同端口。生产环境请改用独立 management 端口 + `management.server.port`，
  并评估 `management.security.enabled` 的取舍
- 改 Grafana 数据源 / 删除文件夹 / 覆盖已有 dashboard
- 调整 Prometheus 保留期、scrape 间隔 → 影响存储与集群负载

---

## 配套文件

| 文件 | 内容 |
|---|---|
| `references/pitfalls.md` | **25 条实测坑**（现象 → 原因 → 处理），排障先看这里 |
| `references/actuator-and-config.md` | actuator 依赖、management 配置、端口口径、常见 404 归因 |
| `references/servicemonitor.md` | 采集层细节：三种选择器写法、relabelings 配方、裸 Prometheus 注解版 |
| `references/grafana-dashboard.md` | 12 面板口径表、样式配方、图例列选择、Table 面板替代方案 |
| `references/grafana-api-troubleshooting.md` | Grafana API / 图表配置的 6 个坑 |
| `references/istio-metrics.md` | Istio 网格侧指标口径（附带章节） |
| `scripts/verify-actuator-endpoint.sh` | 端点探测：真指标 / 假阳性 200 / 404 三态判定 |
| `scripts/check-servicemonitor.sh` | ServiceMonitor 结构与白名单校验 |
| `scripts/gen-dashboard.py` | 12 面板 dashboard 生成器（uid / ns / 服务白名单可参数化） |
| `scripts/verify-dashboard.sh` | 逐条跑 panel 查询，标出空结果 |
| `field-reports/` | 脱敏实战报告（含失败样本） |

## 来源与可信度

内容来自一次真实接入实战（Spring PetClinic 形态 5 服务集群，2026-11 实测），
坑条目均为**实测复现**而非推测。文件里用 ✅ 标注「实测确认」、📄 标注「据文档/源码推断」。
本技能**不覆盖** OpenTelemetry Collector 链路、Prometheus Operator 之外的抓取方式、
以及告警规则设计。
