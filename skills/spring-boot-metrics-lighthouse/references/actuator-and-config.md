# actuator 与 management 配置

> 采集链路的**第一层**。这一层不通，后面全是空图。
> 关联坑：`pitfalls.md` #2 #3 #6 #7 #9 #10

## 1. 依赖

```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
<dependency>
  <groupId>io.micrometer</groupId>
  <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
```

### 为什么 `micrometer-registry-prometheus` 单独强调 ✅

`actuator` 和 `micrometer-core` **通常已经在镜像里**（Spring Boot starter 会带），
但 **registry 是可选实现**——没有 `micrometer-registry-prometheus` 时：

- `/actuator/prometheus` 返回 **404**
- 但 `/actuator/health`、`/actuator/info` 都正常 → **很容易误判成「端点没开」**

排查时先看镜像里有没有这个 jar：

```bash
kubectl exec <pod> -- sh -c 'ls /app/*.jar'                    # Spring Boot 3.x 是 layered jar
kubectl exec <pod> -- sh -c 'unzip -l /app/app.jar | grep -i micrometer-registry-prometheus'
```

> 📄 Spring Boot 3.2+ 默认是 **layered jar**，业务 jar 在 `/app/app.jar`，
> 依赖在 `/app/BOOT-INF/lib/`。用 `unzip -l` 查，不要只 `ls` 目录。

### 加依赖 = 重建镜像 ⚠️

这是**会改变业务行为**的动作（走发布链路、影响线上镜像引用）。
在本技能里**只提示、不自动执行**，一律向用户确认。

如果业务镜像不能重建（镜像来源不可控、离线环境）：

- 方案 A：PodMonitor + 业务侧自建 exporter（需改代码，不推荐）
- 方案 B：改用 JMX exporter sidecar（额外容器）
- 方案 C：放弃该服务，采集其他已具备 registry 的服务

## 2. management 配置

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

### 三段各自的作用

| 段 | 作用 | 漏了会怎样 |
|---|---|---|
| `endpoint.prometheus.enabled` | 开 endpoint | 404 |
| `metrics.export.prometheus.enabled` | 开导出 | endpoint 存在但空 |
| `endpoints.web.exposure.include` | 决定哪些 endpoint 暴露到 web | 默认只暴露 `health`/`info` → 其余 404 |

### 采集路径

**`/actuator/prometheus`**。Spring Boot **没有** `/metrics` 这个路径 —— 写错必然 404。

### 独立 management 端口（生产推荐）

```yaml
management:
  server:
    port: 9090
```

**为什么要独立端口** ✅：`exposure.include: '*'` 会把 `env` / `threaddump` / `sbom` /
`heapdump` / `loggers` 等端点**一起暴露**。实测一套 5 服务的配置下暴露了 **56 个端点**，
而且与应用**同端口**——等于把内部状态全开到业务入口上。

独立端口之后，ServiceMonitor 抓的端口名/端口号要跟着改（见 `servicemonitor.md`）。

> ⚠️ `management.security.enabled: false` 能关掉 Spring Security 对 management 端点的保护，
> 但这是**降低安全性**的动作 → 向用户确认，不要默认写。

## 3. 端口口径（最容易错的一环）✅

一个 Spring Boot 服务在容器里到底监听哪个端口，取决于**几个叠加的来源**：

```
命令行参数 --server.port=  >  环境变量 SERVER_PORT  >  外部配置（config server）
    >  jar 内 application-<profile>.yml  >  jar 内 application.yml
```

实战里最容易踩的两个坑：

1. **`server.port: 0`（随机端口）**
   → 真实端口由外部配置覆盖。**看 Service 的 `targetPort`**，不要看 `application.yml` 里的值。

2. **profile 覆盖只在特定 profile 下生效**
   → 基础 `application.yml` 里写 `server.port: 8080`，
     真实端口在 `config/<app>.yml` 里，而那份只写在 **`docker` profile** 下。
   → 本地跑（无 `docker` profile）时端口和线上**不一样**，
     用本地验证的结果去推线上必然对不上。

**排查动作**：直接查 Service 的端口，不要读配置文件猜。

```bash
kubectl get svc <svc> -n <ns> -o jsonpath='{.spec.ports[*].name} {targetPort} {port}{"\n"}'
```

## 4. 指标名对照（Micrometer → Prometheus）

Micrometer 的 `dot` 名会被翻译成 `underscore` 名：

| Micrometer | Prometheus | 备注 |
|---|---|---|
| `http.server.requests` | `http_server_requests_seconds_count` / `_sum` / `_max` | **无 `_bucket`** |
| `jvm.memory.used` | `jvm_memory_used_bytes` | 带 `area` 标签（`heap`/`nonheap`） |
| `jvm.gc.pause` | `jvm_gc_pause_seconds_sum` / `_count` / `_max` | |
| `jvm.threads.live` | `jvm_threads_live_threads` | **无 `tomcat_threads_*`** |
| `hikaricp.connections.*` | `hikaricp_connections_active` / `_pending` / `_max` | 只有连库的服务有 |
| `logback.events` | `logback_events_total` | 带 `level` 标签 |
| `process.cpu.usage` | `process_cpu_usage` | |
| `http.client.requests` | `http_client_requests_seconds_count` | 出站调用 |

### `_bucket` 缺失的后果 ✅

没有 `_bucket` 就**算不了 P95**：

```promql
# ❌ 查不到东西
histogram_quantile(0.95, sum by (le) (rate(http_server_requests_seconds_bucket[5m])))
# ✅ 用平均代替
sum(rate(http_server_requests_seconds_sum[5m])) / sum(rate(http_server_requests_seconds_count[5m]))
# ✅ 或用 Micrometer 的 decaying max
max_over_time(http_server_requests_seconds_max[$__range:$__interval])
```

想要真 P95，得在业务侧显式开 histogram：

```yaml
management:
  metrics:
    distribution:
      percentiles-histogram:
        http.server.requests: true
      percentiles:
        http.server.requests: 0.5, 0.95, 0.99
```

（开启会显著增加 series 数量与存储量 → 属于容量变更，向用户确认。）

## 5. 快速自检清单

- [ ] `/actuator/prometheus` 返回 **200** 且响应体是**文本指标**（含 `# HELP` / `# TYPE`），不是 JSON
- [ ] 响应体里能看到 `jvm_memory_used_bytes`、`http_server_requests_seconds_count` 这类**真实业务指标**
- [ ] `management.endpoints.web.exposure.include` 覆盖了 `prometheus`
- [ ] 端口口径已用 `kubectl get svc` 核对，不是从配置文件猜的
- [ ] 需要 P95 吗？→ 没有 `_bucket` 的话要么改口径，要么开 histogram（容量变更）
- [ ] `exposure.include: '*'` 暴露了多少端点？→ 生产环境考虑独立 management 端口
