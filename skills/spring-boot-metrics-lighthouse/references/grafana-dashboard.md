# Grafana 面板：口径、样式、图例

> 展示层的**做法与口径**。API 层的坑见 `grafana-api-troubleshooting.md`。
> 关联坑：`pitfalls.md` #9 #10 #11 #12 #13 #14 #15 #16 #17 #18 #19

## 1. 12 面板口径表（已实测校正）

| # | 面板 | 维度 | 单位 | 统计列 | 口径要点 |
|---|---|---|---|---|---|
| 1 | 请求量 (req/s) | 服务 | reqps | 峰值 / 当前 | `rate(http_server_requests_seconds_count[5m])` |
| 2 | 错误率 (5xx 占比) | 服务 | percentunit | 峰值 / 当前 | **`A or 0*B` 写法**，否则无错误时整块空白 |
| 3 | 平均响应时间 | 服务 | s | 峰值 / 当前 | `sum/count`，**无 `_bucket` 算不了 P95** |
| 4 | 最大响应时间 | 服务 | s | 峰值 / 当前 | Micrometer decaying max |
| 5 | JVM 内存（堆 / 非堆） | 服务 / 内存区 | bytes | 峰值 / 当前 | **不画上限线**（Eden/Survivor max 为负） |
| 6 | GC 暂停时间 | 服务 | s | 峰值 / 当前 / **累计** | 累计暂停才是关键 |
| 7 | 线程数 | 服务 | short | 峰值 / 当前 | `jvm_threads_live_threads`（**无 `tomcat_threads_*`**） |
| 8 | 进程 CPU 占用 | 服务 | percentunit | 峰值 / 当前 | `process_cpu_usage` |
| 9 | DB 连接池 (HikariCP) | 服务 / 连接状态 | short | 峰值 / 当前 | 网关类服务不连库 → **无此指标** |
| 10 | 日志级别分布 | 服务 / 级别 | short | 当前 | 5 服务 × 5 级别 = **25 条系列** |
| 11 | 错误日志速率 | 服务 | short | 峰值 | 错误稀疏，**只列峰值** |
| 12 | 请求 Top URI（含状态码） | 服务 / URI | reqps | 峰值 / 当前 | `topk` **不能同时算峰值和当前** |

> 「统计列」指的是**右侧 legend 表显示哪几列**。Grafana 只能选 reducer，
> 列名由它写死（`max`→`Max`、`lastNotNull`→`Last *`、`sum`→`Total`），
> 但**每个面板可以按监控项的实际需要选不同的列组合**。

## 2. 表达式收敛成单一维度

所有面板的表达式都收敛成**一个 `svc` 标签**，这样：

- legend 表的系列名 = 表格的 join 字段 = 同一个字符串
- 表格的 `joinByField` 恒为 `svc`，不用为每个面板改

```promql
# label_join 把多个标签拼成一个字符串标签；sum by (svc) 把其余标签全丢掉
sum by (svc) (label_join(<expr>, "svc", " · ", "job", "area"))
```

维度是「服务 / 内存区」时：

```promql
sum by (svc) (label_join(<expr>, "svc", " · ", "job", "area"))
```

「服务 / URI」时（Top URI 面板把状态码也拼进去）：

```promql
sum by (svc) (label_join(<expr>, "svc", " ", "job", "uri", "st"))
```

## 3. 样式配方（Grafana 10.x）

### 时序图

```json
"fieldConfig": {
  "defaults": {
    "unit": "reqps",
    "color": { "mode": "palette-classic" },
    "custom": {
      "drawStyle": "line",
      "lineWidth": 1,
      "fillOpacity": 0,
      "gradientMode": "none",
      "showPoints": "never",
      "spanNulls": false,
      "stacking": { "mode": "none", "group": "A" },
      "axisPlacement": "left",
      "scaleDistribution": { "type": "linear" }
    }
  },
  "overrides": []
}
```

### 三个必记的路径

| 东西 | 在哪 |
|---|---|
| 时序图样式 | `fieldConfig.defaults.custom` |
| 图例 | **面板级** `options.legend` |
| 仪表盘变量 | `templating.list[]` |

**查顶层 `fieldConfig.defaults.drawStyle` 会误判成「样式没生效」** ✅。

### 图例：table 模式放右侧

```json
"options": {
  "legend": {
    "displayMode": "table",
    "placement": "right",
    "showLegend": true,
    "calcs": ["max", "lastNotNull"],
    "sortBy": "Max",
    "sortDesc": true,
    "alignAsTable": true,
    "rightValue": false
  },
  "tooltip": { "mode": "multi", "sort": "desc" }
}
```

**为什么用 table 而不是 list**：table 模式每行带色块 + 统计值，
而且**点一行能在图里只看那条线**（Grafana 原生隔离行为），list 模式没有。

**`sortBy` 写列的显示名**（`Max` / `Last *` / `Total`），**不是** reducer id
（`max` / `lastNotNull` / `sum`）—— 写错就静默不排序 ✅。

### 按监控项选统计列

| 监控项 | `calcs` | 为什么 |
|---|---|---|
| 多数（请求量/错误率/耗时/JVM/线程/CPU） | `["max","lastNotNull"]` | 峰值 + 当前值 |
| GC 暂停 | `["max","lastNotNull","sum"]` | **累计暂停**才是关键 |
| 日志级别分布 | `["lastNotNull"]` | 构成关系只看当前速率 |
| 错误日志速率 | `["max"]` | 错误稀疏，当前值常年 0 |

## 4. 布局

一行两项（`w=12`, `h=8`，共 6 行）：

```python
x, y = 0, 0
for it in ITEMS:
    w = 24 if it.get("wide") else 12
    if x + w > 24:
        x, y = 0, y + 8
    panels.append(chart_panel(it, x, y, w, 8))
    x += w
    if x >= 24:
        x, y = 0, y + 8
```

**`wide=True` 的面板独占整行**（`w=24`）→ 用于系列特别多的项
（如「日志级别分布」25 条系列，半宽时右侧 legend 表会把绘图区挤窄）。

> ⚠️ 实测教训：给「日志级别分布」独占整行后，**用户决定回退**为一行两项。
> → 布局是**产品决策**，不是技术最优。生成器里保留 `wide` 开关，默认关闭。

### 面板 id 必须写

```python
for i, p in enumerate(panels, start=1):
    p["id"] = i
```

**不写 id 的话 Grafana 导入后 id 留空** → 面板级书签 `#viewPanel=N` 失效。
固定 id 让重复导入保持幂等（改内容重导不会让旧书签全部指向别的面板）。

## 5. 仪表盘变量

```json
"templating": {
  "list": [{
    "name": "service",
    "label": "服务",
    "type": "query",
    "datasource": { "type": "prometheus", "uid": "<uid>" },
    "definition": "label_values(up{namespace=\"<ns>\"}, job)",
    "query": { "query": "label_values(up{namespace=\"<ns>\"}, job)", "refId": "StandardVariableQuery" },
    "multi": true,
    "includeAll": true,
    "allValue": ".*",
    "refresh": 2,
    "sort": 1
  }]
}
```

面板表达式用 `job=~"$service"` 引用它。**多选 + includeAll** 是必须的，
否则只能看一个服务。

## 6. 备选方案：Table 面板自建右侧表

**什么时候用**：想用**中文表头**、想给「服务」列挂 data link（点一下跳到按该服务过滤的视图）。

**代价**（都要权衡）：

- 面板数翻倍（12 → 24）
- **失去 legend 的点击隔离行为**（Table 面板是静态表格）
- 颜色 ↔ 系列名的对应关系要靠图例补

**配方**（Grafana 前端 `transformDFToTable` 决定列名）：

```json
"transformations": [
  { "id": "joinByField", "options": { "byField": "svc", "mode": "outerTabular" } },
  { "id": "organize", "options": {
      "excludeByName": { "Time": true },
      "renameByName": { "svc": "服务", "Value #A": "峰值", "Value #B": "当前" },
      "indexByName": { "svc": 0, "Value #A": 1, "Value #B": 2 }
  } }
]
```

**三个必须记住的点** ✅：

1. `joinByField` 的 `mode` 必须是 **`outerTabular`**（按字段值配对）；
   `outer` 是按**时间**配对，对 instant 查询不适用
2. 值列名：**多个 refId → `Value #A` / `Value #B`；单个 refId → `Value`**
   → 单查询面板 rename 必须写 `Value`，写 `Value #A` 匹配不上
3. 合并后字段顺序 = `[join 字段, 帧A其余字段…, 帧B其余字段…]` →
   **`Time` 列会出现两次**，`excludeByName: {"Time": true}` 会把两个都排除 ✅

生成器里用 `USE_EXTRA_TABLE` 开关切换，默认 `False`（用原生 legend 表）。

## 7. 常用 PromQL 片段

### 错误率（无错误时显示 0）

```promql
(
  sum by (svc) (rate(http_server_requests_seconds_count{status=~"5.."}[5m]))
  or 0 * sum by (svc) (rate(http_server_requests_seconds_count[5m]))
)
/
clamp_min(sum by (svc) (rate(http_server_requests_seconds_count[5m])), 0.000001)
```

### 平均响应时间

```promql
sum by (svc) (rate(http_server_requests_seconds_sum[5m]))
/
clamp_min(sum by (svc) (rate(http_server_requests_seconds_count[5m])), 0.000001)
```

### 堆 / 非堆已用（不画上限）

```promql
label_replace(
  label_replace(jvm_memory_used_bytes, "area", "堆", "area", "^heap$"),
  "area", "非堆", "area", "^nonheap$")
```

> ⚠️ 正则**必须锚定**（`^heap$`）。不锚定的话 `^heap$` 之外的部分也会命中，
> `nonheap` 会被错误归类。

### GC 暂停速率

```promql
rate(jvm_gc_pause_seconds_sum[5m])
```

### 连接池三态（HikariCP）

```promql
label_replace(hikaricp_connections_active,   "state", "活跃", "job", "^(.*)$")
or label_replace(hikaricp_connections_pending, "state", "等待", "job", "^(.*)$")
or label_replace(hikaricp_connections_max,     "state", "上限", "job", "^(.*)$")
```

### 区间峰值 / 累计（子查询步长用 `$__interval`）

```promql
max_over_time((<expr>)[$__range:$__interval])     # 峰值
sum_over_time((<expr>)[$__range:$__interval])     # 累计
```

> ⚠️ **不要写死步长**：`[$__range:5m]` 在时间范围 < 5m 时非法会报错。

## 8. 面板自检清单

- [ ] 每个面板的 PromQL **单独跑一遍**有数据（不是只看 dashboard 导入成功）
- [ ] 表达式只依赖**自己 relabeling 出来的标签**，不依赖 `job` 的具体形态
- [ ] 无数据时不会「看起来像坏了」→ 用 `A or 0*B` 兜底
- [ ] 除法都加了 `clamp_min` 防止除零出 `NaN`
- [ ] 子查询步长用 `$__interval`
- [ ] 多查询合并时只有第一个保留原始标签
- [ ] 面板 id 已固定编号
- [ ] 样式字段在 `fieldConfig.defaults.custom` 下
- [ ] `sortBy` 写的是列显示名
- [ ] 时序图**没有设 `decimals`**
- [ ] legend 的 `calcs` 按监控项区分，不是清一色
