---
date: 2026-11-12
environment: Kubernetes 1.29 / kube-prometheus-stack v3.13.0 / Grafana 10.3.3 · 5 个 Spring Boot 业务服务
result: success
duration_hours: 3
skill_version: 0.1.0
operator: agent
---

# 首次接入：5 个 Spring Boot 微服务上 Prometheus + Grafana

> 脱敏报告。真实 IP / 域名 / uid / 命名空间 / 私有仓库地址**一律替换**，
> 示例值统一用 `10.0.0.x` 与 `example.com`。

## 1. 开工前的状态

- 业务镜像里**已经有** `micrometer-registry-prometheus`（1.16.1）→ **不用重建镜像**
- `management:` 配置块已在线生效（`endpoint.prometheus.enabled` +
  `metrics.export.prometheus.enabled` + `exposure.include: '*'`）
- 主 Prometheus 在 `monitoring` ns（kube-prometheus-stack，19 job / 50 active target）
- Grafana 是集群里**唯一一套真 Grafana**（在 `loki-stack` ns），kube-prometheus-stack 自带的那个被禁用了

**结论**：容器与配置层已经具备，**只差采集层和展示层** → 这是最好的起点。

## 2. 采集层

新建一个 ServiceMonitor，本以为一次过，实际踩了三个坑：

### 坑 1：忘打 `release` 标签 → 静默失效 ✅

第一次 `kubectl apply` 成功、`kubectl get servicemonitor` 能看到对象，
但 Prometheus 的 target 数一直是 0，**没有任何报错**。

排查过程：
1. `kubectl get servicemonitor` → 对象在 ✅
2. Prometheus `/api/v1/targets` → 没有这个 job ❌
3. 打印 Prometheus CR 的选择器 → `matchLabels{release: kube-monitor}`
4. 对比自己的对象 metadata.labels → **没有 release** ❌

补上 label 后立刻生效。

> **教训**：Operator 的 selector 是**静默过滤**，不是校验。
> 写清单之前先打印选择器，不要照抄别人仓库里的 label 值。

### 坑 2：Service 一个 label 都没有 ✅

业务 Service 的 `metadata.labels` 是空的 → `matchLabels` 和 `targetLabels` 都用不了。

改用：`selector: {}`（全选）+ relabelings 白名单。

### 坑 3：端口名全叫 `http` ✅

同一 ns 里除数据库外**所有** Service 的端口都叫 `http`，
只写 `port: http` 会把 admin-server / config-server / grafana-server 一起抓进来。

最终配方：

```yaml
relabelings:
  - sourceLabels: [__meta_kubernetes_service_name]
    regex: "api-gateway|customers-service|visits-service|vets-service|genai-service"
    action: keep
  - sourceLabels: [__meta_kubernetes_service_name]
    targetLabel: service
    action: replace
```

## 3. 验收（这一步才发现第二个问题）

target up 了（5/5），**但其中两个是假阳性**：

| 服务 | up | 实际 |
|---|---|---|
| api-gateway / customers / visits / vets / genai | 1 | ✅ 真指标 |
| config-server | 1 | ❌ **200 但返回 JSON** —— 配置服务器把路径当 `{application}/{profile}` 解析了，镜像里根本没有 actuator |
| admin-server | 0 | ❌ 404 —— 缺 `micrometer-registry-prometheus`（actuator 本身是有的） |

→ 用 relabelings 白名单把 config-server 排除；
admin-server / discovery-server 决定**不纳入采集**（没有 registry，且要重建镜像，收益低）。

最终 **5 个 target 全 up 且全是真指标**。

> **教训**：`up=1` ≠ 采到指标。必须看响应体是不是文本指标。
> 这也是后来写 `verify-actuator-endpoint.sh` 的直接原因。

## 4. 展示层：12 个面板

生成器写的，不是手搓的。第一版跑出来一堆空面板，逐条查出来是**口径问题**：

| 面板 | 第一版问题 | 修法 |
|---|---|---|
| 错误率 | 无 5xx 时整块空白 | `A or 0*B` 写法 |
| 平均响应时间 | 用了 P95 → 查不到 | Micrometer **无 `_bucket`**，改成 sum/count |
| JVM 内存 | 画了堆上限线，值是 0 | Eden/Survivor 的 max 是负数（无界），只画已用 |
| 线程数 | 用了 `tomcat_threads_*` → 空 | 改 `jvm_threads_live_threads` |
| DB 连接池 | 网关面板空 | **正常** —— 网关不连库，没有 HikariCP 指标 |
| 日志级别分布 | 25 条系列挤成一团 | 试过独占整行，最终用户决定回退为一行两项 |

图例踩了两个坑：

- `sortBy` 写的是**列显示名**（`Max` / `Last *`），不是 reducer id → 写错静默不排序
- 想用中文表头 → Grafana 10.x **写死了**（源码级），只能换 Table 面板，代价是失去点击隔离

## 5. Grafana 侧两个环境坑

- **`PUT /api/folders/:uid` 改文件夹名会挂死** —— SQLite 在 NFS 上，
  `database is locked`。绕行：新建文件夹 → 导 dashboard → 删旧文件夹
- **`kubectl exec -i` 传 JSON 时加了 `< /dev/null`** → 管道被掐断，
  Grafana 回 `bad request data`（看着像 payload 有问题，实际是 body 是空的）

## 6. 结果

| 项 | 结果 |
|---|---|
| 采集 | 5 个业务服务，target 全 up，全是真指标 |
| 展示 | 12 面板，**209 条查询逐条验证**有数据 |
| 图例 | table 模式放右侧，可点击联动；每面板按需选统计列 |
| 沉淀 | 25 条坑进 `references/pitfalls.md`，4 个脚本进 `scripts/` |

## 7. 没做的事

- admin-server / discovery-server 未纳入采集（缺 registry，需重建镜像）
- P95 未做（需要开 histogram，会显著增加 series 数与存储量 → 容量变更，需确认）
- 生产安全的 management 独立端口未做（`exposure.include: '*'` 暴露了 56 个端点，
  与业务同端口）→ 属安全变更，未擅自改

## 8. 状态提升

| 问题 | 去向 |
|---|---|
| release 标签静默失效 | `pitfalls.md` #1 |
| config-server 假阳性 200 | `pitfalls.md` #2 |
| admin 404 ≠ 没装 actuator | `pitfalls.md` #3 |
| Service 无 label / 端口名撞车 | `pitfalls.md` #4 #5 |
| 无 `_bucket` / JVM max 负数 | `pitfalls.md` #9 #10 |
| 错误率空图 | `pitfalls.md` #11 |
| legend sortBy 写错 | `pitfalls.md` #16 |
| 文件夹改名挂死 | `pitfalls.md` #23 |
| exec -i 加重定向 | `pitfalls.md` #22 |
