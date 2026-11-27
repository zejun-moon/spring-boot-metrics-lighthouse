# Istio 网格侧指标口径（附带章节）

> ⚠️ **本篇是附带内容，不属于本技能的主线。**
> 主线是「Spring Boot 应用自身指标」。本篇只覆盖
> **服务网格（Istio）侧**的指标口径与易错点，供已经在网格里的环境参考。
>
> 标注：✅ 实测确认 · 📄 据源码/文档推断

## 1. 控制面指标前缀是 `pilot_*` ✅

Istio 1.31 的控制面（istiod）指标前缀是 **`pilot_`**。

**已不存在的老指标名**（照着老教程查会一无所获）：

| 老名字 | 状态 |
|---|---|
| `pilot_total_xds_rejects` | 1.31 已无 |
| `pilot_total_xds_internal_errors` | 1.31 已无 |
| `galley_validation_failed` | 1.31 已无（Galley 已下线） |
| `sidecar_injection_failure_total` | 1.31 已无 |

**查 istiod 进程指标用 `job="istiod"`** —— Prometheus **不会自动给 istiod 加 `app` 标签**，
写 `app="istiod"` 查不到东西 ✅。

## 2. sidecar 指标端口是 15090 ✅

Envoy 的 Prometheus 端点在 **`http-envoy-prom` = 15090**。

- `istio-proxy` 容器上的端口名是 `http-envoy-prom`
- PodMonitor 抓 sidecar 时 `port: http-envoy-prom`
- 用 `container: "istio-proxy"` 过滤 sidecar 指标

## 3. 时长直方图只有 milliseconds ✅

Envoy 的 duration 直方图单位是 **milliseconds**，不是 seconds。
`istio_request_duration_milliseconds_bucket` 这类名字里的 `milliseconds` 就是单位提示。

写 `histogram_quantile` 时记得换算，别把 ms 当 s 用。

## 4. Istio 1.31 在 K8s 1.29+ 用原生 sidecar ✅

**`istio-proxy` 在 `initContainers` 里，不在 `.spec.containers`**（K8s 原生 sidecar 特性）。

→ 任何按 `spec.containers[].name == "istio-proxy"` 找 sidecar 的脚本/面板，
在新集群上**会找不到**。

## 5. Service 的 app 标签与网格标签的关系

网格侧指标通常靠这几个标签聚合：

| 标签 | 来源 | 用途 |
|---|---|---|
| `reporter` | `source`/`destination` | 区分请求的哪一端观测到的 |
| `destination_service` | `destination_service` | 目标服务（`<svc>.<ns>.svc.cluster.local`） |
| `source_workload` / `destination_workload` | workoad metadata | 按工作负载聚合 |
| `security.istio.io/tlsMode` | Pod label | **可用作 PodMonitor 选择器** |

> 📄 `sidecar.istio.io/status` 是**注解**不是 label → **不能用它做 PodMonitor 选择器**
> （会选不到任何 Pod）。用 `security.istio.io/tlsMode: istio` 这个 **label**。

## 6. 归因口径 ✅

`reporter="destination"` 的指标才是**目标服务视角**的。
`reporter="source"` 是调用方视角。

一个请求在网格里会出现两条（source + destination），
**做服务视图/工作负载视图时必须选对 reporter**，否则同一个请求被算两遍。

## 7. 集群没有 metrics-server → HPA 永远报 metrics 错 ✅

集群未装 metrics-server 时，HPA 的 `resource` 指标拿不到 →
HPA 一直报 metrics 错误，**不缩容**（无害，但会持续刷告警）。

**这不是 HPA 配错，是集群缺 metrics-server。**
面板里不要把「HPA 不工作」误判成「应用有压力问题」。

## 8. cAdvisor 不暴露某些容器指标 ✅

集群的 cAdvisor **不暴露 `container_fs_usage_bytes`**。
做「容器磁盘用量」面板前先确认这个指标存在，不存在就是环境缺，不是采集配置问题。

## 9. 网格侧常见空面板归因

| 面板空 | 先查 |
|---|---|
| 控制面面板空 | `job="istiod"`（不是 `app="istiod"`）；指标前缀是不是 `pilot_*` |
| sidecar 面板空 | 端口是不是 `http-envoy-prom`；Pod 有没有注入 sidecar |
| 服务视图部分分组空 | 是不是 `mutual_tls` 分组（没配 mTLS 就没有） |
| 工作负载视图部分空 | 是不是 TCP 指标（HTTP/2 下没有） |
| 时长类面板全是 0 | 单位是 **milliseconds** |

## 10. 与本技能主线的关系

- **应用指标**（JVM / HTTP / 连接池 / 日志）→ 走主线的 ServiceMonitor
- **网格指标**（mTLS / 流量 / 延迟 / 重试）→ 走 Istio 自己的 PodMonitor
- 两者可以**共用同一个 Prometheus**，但**不要共用同一个 dashboard 的同一批面板**——
  口径、维度、reporter 语义完全不同，混在一起会互相误导。

> 网格侧的完整接入（注入、Gateway、VirtualService、mTLS、拓扑面板）
> 属于另一条工作线，不在本技能范围内。
