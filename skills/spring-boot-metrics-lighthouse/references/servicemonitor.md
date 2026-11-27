# 采集层：ServiceMonitor / PodMonitor / 注解

> 采集链路的**第二层**。指标在服务里有了，不代表 Prometheus 抓得到。
> 关联坑：`pitfalls.md` #1 #2 #4 #5 #6 #7 #8

## 1. 三种选择器，先对号入座

| 方式 | 什么时候用 | 选谁 | 典型坑 |
|---|---|---|---|
| **ServiceMonitor** | 有 Service，端口有名字 | `spec.selector` 选 Service | 端口名撞车（#5）、Service 没 label（#4） |
| **PodMonitor** | 没 Service，或要抓 sidecar / 非 Service 端点 | `spec.selector` 选 Pod（**按 label 选 Pod，不是选 Service**） | Pod 没 label → 选不到；Pod label 每次发布都变 |
| **annotations** | 裸 Prometheus（非 Operator） | Pod 注解 `prometheus.io/scrape` 等 | 注解写错不报错，只是没数据 |

## 2. ServiceMonitor 完整配方

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: <app>-services
  namespace: <app-ns>
  labels:
    # ① 必须与 Prometheus CR 的 serviceMonitorSelector 命中
    release: kube-monitor
spec:
  namespaceSelector:
    matchNames:
      - <app-ns>
  selector: {}                     # ② 空选（业务 Service 无 label）
  endpoints:
    - port: http                   # ③ 端口名（不是端口号）
      path: /actuator/prometheus  # ④ 不是 /metrics
      interval: 15s
      scrapeTimeout: 10s
      relabelings:
        # ⑤ 白名单：只放行目标服务
        - sourceLabels: [__meta_kubernetes_service_name]
          regex: "svc-a|svc-b|svc-c"
          action: keep
        # ⑥ 把服务名提升成稳定标签，供面板聚合
        - sourceLabels: [__meta_kubernetes_service_name]
          targetLabel: service
          action: replace
        # ⑦ 丢掉不稳定的标签，避免 series 爆炸
        - sourceLabels: [__meta_kubernetes_pod_name]
          regex: "svc-a-.*"
          action: drop
```

### 逐条解释

**① `release` 标签** ✅
Prometheus Operator 的选择器：

```yaml
spec:
  serviceMonitorSelector:
    matchLabels:
      release: kube-monitor
```

**你的 ServiceMonitor 没有这个 label → 被静默过滤**（对象存在、target=0、无报错）。
**先打印选择器再写清单**，不要照抄别人的 label 值：

```bash
kubectl get prometheus -n <monitoring-ns> -o jsonpath='{.spec.serviceMonitorSelector}{"\n"}'
```

**② 空 selector** ✅
`selector: {}` = 选中该 namespace 下**所有** Service。
业务 Service 常常一个 label 都没有 → `matchLabels` / `targetLabels` 用不了（#4）。
**空选必须配白名单**，否则会抓到无关服务（#5）。

**③ 端口名不是端口号**
`port: http` 指的是 **Service 端口的 `name`**，不是容器端口、也不是 Service 的 `port` 数字。
Service 没给端口起名字 → 用 `targetPort: <number>` 直接写数字。

**④ 路径**
`/actuator/prometheus`。写 `/metrics` 必然 404。

**⑤ 白名单 `keep`** ✅
`__meta_kubernetes_service_name` 是 Prometheus Operator 注入的**抓取期元标签**，
只有 relabeling 阶段可用。`regex` 是**完全匹配**（不是子串），
所以要写全名并用 `|` 分隔：

```yaml
regex: "api-gateway|customers-service|visits-service"    # ✅
regex: "customers"                                          # ❌ 完全匹配，匹配不到 customers-service
```

**⑥ 自定义 `service` 标签** ✅
Prometheus Operator 自动打的 `job` 标签**在不同版本/不同 endpoint 下形态不一致**
（可能带实例后缀）。**面板要按服务聚合就别依赖 `job`**，用自己 relabeling 出来的 `service`。
同时把 `job` 保留下来做「服务名」展示（生成器里就是这么用的）。

**⑦ 丢掉 Pod 名标签**
Pod 名每次滚动更新都变 → 不 drop 的话 series 数量随发布翻倍。
只 drop 目标服务的 Pod 名，别全 drop（会丢调试信息）。

### 常用 relabelings 配方

```yaml
# 用 namespace + service 组成唯一标识
- sourceLabels: [__meta_kubernetes_namespace, __meta_kubernetes_service_name]
  separator: "/"
  targetLabel: service_full
  action: replace

# 只抓有 annotation 的 Pod（PodMonitor 场景）
- sourceLabels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
  action: keep
  regex: "true"

# 自定义抓取路径
- sourceLabels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
  targetLabel: __metrics_path__
  action: replace
```

## 3. PodMonitor 配方（Istio sidecar 场景）

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: <app>-pods
  namespace: <app-ns>
  labels:
    release: kube-monitor
spec:
  namespaceSelector:
    matchNames: [<app-ns>]
  selector:
    matchLabels:
      app: <app>                # ⚠️ 选的是 **Pod label**，不是 Service
  podMetricsEndpoints:
    - port: http                # Pod 容器端口名
      path: /actuator/prometheus
      interval: 15s
```

**PodMonitor 选 Pod label**，这是和 ServiceMonitor 最大的区别。
`app` 标签来自 Deployment 的 `spec.template.metadata.labels` → **必须打在 Pod 模板上**，
打在 Deployment 的顶层 `metadata.labels` 上没用。

## 4. 裸 Prometheus（无 Operator）——注解版

```yaml
apiVersion: v1
kind: Service
metadata:
  name: <svc>
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
    prometheus.io/path: "/actuator/prometheus"
spec:
  ports:
    - name: http
      port: 8080
      targetPort: 8080
```

裸 Prometheus 的默认配置里 `relabel_configs` 有一长串 `keep` 规则会按
`prometheus.io/*` 注解放行 target。**注意**：

- 注解写在 **Service** 上 → 抓 Service 的 `port`（注解里的端口号）
- 注解写在 **Pod** 上 → 抓 Pod IP + 注解端口
- 两者混用会重复采集

## 5. 验收：target up ≠ 有指标 ✅

**三层验证，一步都不能省**：

```bash
# ① 对象层：ServiceMonitor 存在且带对 label
kubectl get servicemonitor -n <app-ns> <name> -o jsonpath='{.metadata.labels}{"\n"}'

# ② 抓取层：target up / lastError
kubectl -n <monitoring-ns> exec <prom-pod> -- \
  wget -qO- 'http://localhost:9090/api/v1/targets?state=active' | \
  jq --arg j "<job>" '.data.activeTargets[] | select(.labels.job==$j) | {health, lastError, scrapeUrl}'

# ③ 数据层：真的有指标序列
kubectl -n <monitoring-ns> exec <prom-pod> -- \
  wget -qO- 'http://localhost:9090/api/v1/query?query=up%7Bservice%3D%22svc-a%22%7D' | jq '.data.result'
```

**② up 但 ③ 空** → 问题在**端点**（404 / 假阳性 200），不在采集层 → 回 `actuator-and-config.md`。

**`lastError` 常见值对照**：

| lastError | 含义 |
|---|---|
| `context deadline exceeded` | 抓取超时 → 服务慢 / 路径重 / `scrapeTimeout` 太小 |
| `server returned HTTP status 404 Not Found` | 路径写错（`/metrics`）或没装 registry |
| `server returned HTTP status 403 Forbidden` | management 端口有安全策略 |
| `unexpected EOF` | 连接被断 / 服务重启中 |

## 6. 改配置的副作用 ⚠️

- **改 ServiceMonitor 是安全的**（只影响采集，不影响业务流量）
- **改 scrape 间隔** 会改变存储量与 Prometheus 负载 → 集群级变更，向用户确认
- **给 Prometheus 加 `release` label 到已有对象上** → 会突然多出/少掉一批 target，
  改完必须重新核对 target 列表

## 7. 快速自检清单

- [ ] `serviceMonitorSelector` 的实际取值已打印确认（不是猜的）
- [ ] ServiceMonitor 的 `metadata.labels` 命中该选择器
- [ ] `selector` 为空时**一定有** `keep` 白名单
- [ ] 白名单 regex 是**全名完全匹配**
- [ ] `path` 是 `/actuator/prometheus`
- [ ] 端口名与 Service 的 `ports[].name` 一致
- [ ] 面板依赖的标签（`service`）是自己 relabeling 出来的
- [ ] Pod 名标签已 drop（否则 series 随发布膨胀）
- [ ] target up **且** 指标序列非空，两层都验过
