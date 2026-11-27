# 坑表：现象 → 原因 → 处理

> 全部来自一次真实接入实战（Spring PetClinic 形态 5 服务集群，2026-11 实测）。
> ✅ = 实测复现 · 📄 = 据源码/文档推断
> 排障时**先搜本文**，再翻 `field-reports/`。

---

## A. 采集层（指标没进来）

### 1. ✅ ServiceMonitor 没打 `release` 标签 → 静默失效

- **现象**：`kubectl get servicemonitor` 能看到对象，但 Prometheus 的
  `target` 数 = 0；`/api/v1/targets` 里查不到这个 job；**全程无任何报错**
- **原因**：Prometheus CR 的 `serviceMonitorSelector` 是 `matchLabels{release: kube-monitor}`，
  你的 ServiceMonitor 没有这个 label → **直接被过滤掉**，不是报错，是"不存在"
- **处理**：给 ServiceMonitor 加上 `metadata.labels.release: kube-monitor`（与
  `serviceMonitorSelector` 实际取值一致），然后 `kubectl apply` 或 patch
- **判据**：先打印选择器本身，别猜
  ```bash
  kubectl get prometheus -n <monitoring-ns> -o jsonpath='{.spec.serviceMonitorSelector}{"\n"}'
  ```

### 2. ✅ config-server 的 `/actuator/prometheus` 返回 200，但是**假阳性**

- **现象**：target `up = 1`，但拉回来的 `Content-Type` 是 `application/json`，里面是配置内容不是指标
- **原因**：Spring Cloud Config Server 把请求路径当成 `{application}/{profile}` 解析，
  `/actuator/prometheus` 恰好匹配上了；**它的镜像里根本没有 actuator/micrometer jar**
- **处理**：用 `relabelings` 的 `keep` 白名单**显式排除**配置服务器；
  判据用 `scripts/verify-actuator-endpoint.sh`（它检查响应体是否含 `# HELP` / `# TYPE`）
- **推论**：**`up=1` 不等于「采到指标了」** —— 必须看响应体内容类型

### 3. ✅ admin-server / discovery-server 的 404 ≠「没装 actuator」

- **现象**：某些服务 404
- **原因**：actuator 和 `micrometer-core` **都在镜像里**，只缺
  `micrometer-registry-prometheus` → 没有 Prometheus registry 就没有那个端点
- **处理**：加 `micrometer-registry-prometheus` 依赖并**重建镜像**；
  镜像不能重建就放弃纳入采集（或用 PodMonitor + 自建 exporter）
- **注意**：Eureka 服务（discovery-server）本身没有 HTTP 业务指标，纳入采集价值不大

### 4. ✅ 业务 Service 一个 label 都没有 → `matchLabels` / `targetLabels` 都用不了

- **现象**：`spec.selector` 想写 `matchLabels: {app: xxx}` 选不中任何 Service
- **原因**：业务 Service 的 `metadata.labels` 是空的
- **处理**：`selector: {}`（空选 = 全选）+ 用 `relabelings` 按
  `__meta_kubernetes_service_name` 做白名单 `keep`

### 5. ✅ 除数据库外，所有 Service 的端口都叫 `http` → 抓到一堆无关服务

- **现象**：只写了 `port: http`，结果 admin-server / config-server / grafana-server 全被一起抓
- **原因**：K8s 里端口名是**服务内唯一**的，同一 ns 多个 Service 可以都叫 `http`；
  ServiceMonitor 的 `port: http` 按名字匹配，**不区分哪个 Service**
- **处理**：**必须**用 `relabelings` 白名单兜底（坑 #4/#5 是同一个问题的两面）

### 6. ✅ 标签不齐 → 跨服务聚合会裂开

- **现象**：`sum by (application)` 之类的聚合只有部分服务有数据
- **原因**：有些服务在代码里加了 `application` 标签（Java 侧 `MetricConfig`），
  有些没有；yml 层也没有统一配 `management.metrics.tags`
- **处理**：在 `application.yml` 统一加
  ```yaml
  management:
    metrics:
      tags:
        application: <spring.application.name>
  ```
  或在查询里**只依赖 `service` 标签**（自己 relabeling 出来的，稳定）

### 7. ✅ 抓到了服务，但没有对应指标序列

- **现象**：target up，但 `http_server_requests_seconds_count` 查不到
- **原因**：抓的是**没业务流量**的服务，或该服务根本不是 Spring MVC 应用
- **处理**：先确认有请求打进来（`logback_events_total` 也应该有），
  再确认指标名对不对 —— Micrometer 的名字是
  `http_server_requests_seconds_count`（下划线分隔），不是 `http.server.requests`

### 8. ✅ `up` 掉 0 ≠ 指标值为 0 —— 「断流」与「零」是两件事

- **现象**：面板空图，到底是服务挂了还是没采到？
- **原因**：Grafana 里 `noValue`（没采到）和 `0`（采到了，是 0）视觉上很容易混
- **处理**：**至少两个信号交叉判断**
  - `up{job="x"}` 掉 0 → 抓取本身失败（服务死了 / 端口不通 / 路径 404）
  - `up = 1` 但指标值为 0 → 服务活着，只是没有这类事件
  - 用 `kube_deployment_status_replicas_available` 看「谁挂了」——**这是唯一权威答案**，
    因为它覆盖全部 deployment（含没有 Prometheus 指标的 admin/config/discovery 等）

### 9. ✅ `jvm_memory_max_bytes` 里 Eden/Survivor 的 max 是**负数**

- **现象**：算堆上限时 `sum` 出来是 0，甚至出现负值
- **原因**：G1 的 Eden/Survivor 是**无界**的，Micrometer 用负数表示
- **处理**：**不要画堆上限线**，只画「堆已用 / 非堆已用」；
  真要看上限，取 Old Gen（`area="old"`）并注意容器没设 `resources.limits` 时
  JVM 取的是**节点内存**（画出来没参考意义）

### 10. ✅ Micrometer 没有 `_bucket` → 算不了 P95

- **现象**：`histogram_quantile(0.95, ...)` 查不到东西
- **原因**：Micrometer 默认只暴露 `_count` / `_sum` / `_max`
- **处理**：耗时面板用「平均」（`sum/count`）和「最大」（`_max`）两个口径；
  真要 P95 要在业务侧显式配置 `management.metrics.distribution.percentiles-histogram`

---

## B. 展示层（数据进来了但画不出来）

### 11. ✅ 没有 5xx 时错误率面板整块空白

- **现象**：一切正常时错误率面板「坏了」
- **原因**：`(5xx / total)` 在分子为 0 时整个表达式为空
- **处理**：用 `A or 0 * B` 写法 —— 分子为空时回落到 0×分母
  ```promql
  (sum(rate(http_server_requests_seconds_count{status=~"5.."}[5m])) or 0 * sum(rate(http_server_requests_seconds_count[5m])))
  / clamp_min(sum(rate(http_server_requests_seconds_count[5m])), 0.000001)
  ```
  `clamp_min` 别省：否则**完全没有请求**时除零出 `NaN`

### 12. ✅ 响应时间子查询步长写死 → 时间范围小于步长时报错

- **现象**：把时间范围改成 1 分钟，查询直接报错
- **原因**：`max_over_time((X)[$__range:5m])` —— 范围 1m < 步长 5m，非法
- **处理**：用 `[$__range:$__interval]`，跟着 Grafana 的自适应间隔走
  （1 小时范围 → 30s 步长）

### 13. ✅ 多查询合并时出现同名列 → `organize` 把两列一起改名

- **现象**：表格里本该有的列不见了，或名字串了
- **原因**：多个查询各自保留 `job` / `area` 等原始标签 → 合并后同名列出现两次，
  `organize` 的 `renameByName` 会把**所有同名列**一起改
- **处理**：**只让第一个查询保留原始标签**，其余查询用 `sum by (svc)` 收掉
- **配套**：合并用 `joinByField`，`mode` 必须是 **`outerTabular`**（按字段值配对），
  `outer` 是按**时间**配对，对 instant 查询不适用

### 14. ✅ `topk` 同时算「峰值列」和「当前列」→ 两列对不上

- **现象**：表里峰值列和当前列的 URI 不是同一批
- **原因**：每个时刻 `topk` 选出的集合会变，两个查询各算各的
- **处理**：**要么只留一列，要么两边用同一个 topk 结果**（先 topk 再算 max/last）

### 15. ✅ Table 面板的值列名对不上 → 列名保持英文

- **现象**：`organize` 重命名没生效，列还是 `Value #A`
- **原因**：Grafana **前端** `result_transformer.ts` 的 `getValueText()` 决定值列名 ——
  同一响应里有**多个 refId** → `Value #A` / `Value #B`；**只有一个 refId** → `Value`
- **处理**：面板只有 1 个查询时 rename 必须写 `Value`；
  另外 📄 后端 Prometheus 查询模型**没有 Format 字段** → 用 `/api/ds/query` 直连测不出 table 格式，
  只能看源码 + 最终 dashboard

### 16. ✅ 图例 `sortBy` 写了 reducer id → 静默不排序

- **现象**：点了表头没反应
- **原因**：`options.legend.sortBy` 是按**列的显示名**匹配的（`stat.title === sortKey`）
- **处理**：写显示名 `Max` / `Last *` / `Total`，**不是** `max` / `lastNotNull` / `sum`

### 17. ✅ Grafana 10.x 的 legend 表头文字改不了（源码级死结）

- **现象**：图例表第一列永远是 `Name`，换中文界面也没用
- **原因**（📄 查 v10.3.3 源码确认）：
  - 第一列表头恒为字面量 `Name` —— `packages/grafana-ui/src/components/VizLegend/VizLegendTable.tsx:12`
    `const nameSortKey = 'Name'`，且 `PlotLegend.tsx:153` 把 `isSortable={true}` 写死 → **不是 i18n key**
  - 统计列表头取自 reducer 注册表固定英文名 —— `packages/grafana-data/src/transformations/fieldReducer.ts`：
    `Max` / `Last *` / `Min` / `Mean` / `Total` / `Count` / `Delta`
- **处理**：**接受这个限制，用原生 legend 表**；
  想要中文表头只能换 **Table 面板**（列名可任意自定义），代价是失去 legend 的点击隔离

### 18. ✅ 时序图样式改了「没生效」

- **现象**：JSON 里改了 `drawStyle` / `fillOpacity`，图还是老样子
- **原因**：Grafana 10 的时序样式字段在 **`fieldConfig.defaults.custom`** 下，
  不在 `defaults` 顶层；图例在**面板级** `options.legend`
- **处理**：按这个路径找，查顶层会误判成「没生效」

### 19. ✅ 面板设了 `decimals` → Y 轴冒出 `noValue` 文案

- **现象**：**有数据**时，Y 轴上平白多出几行 `noValue` 文案（每个 series 一行），
  看起来像「数据断了」，演练中会被误读成注入故障
- **原因**：`decimals` 是整数时 Grafana 按「刻度值」生成 Y 轴标签，
  此时**字符串型 `noValue`** 被当成一个额外的数值类别混进刻度
- **对照实验**（同一查询、只改一个参数）：

  | decimals | noValue | 结果 |
  |---|---|---|
  | 无 | 有 | ✅ 干净 |
  | `0` | 有 | ❌ 文案漏进 Y 轴 |
  | 无 | 有（空数据） | ✅ noValue 正常显示 |
  | 无 | 无（空数据） | 显示 "No data"（对照） |

- **处理**：**时序图面板一律不设 `decimals`**。去掉后有数据时 Y 轴干净、
  无数据时 `noValue` 照常生效，两者不冲突
- **排查顺序**：先确认是不是**数据空值**造成的（把 `up` 拉出来看采样点是否全为 1、
  零空值），排除「查询有空值」这条误判路径

### 20. ✅ 全屏截图看起来「面板重叠、标题丢失」

- **现象**：整页截图里面板内容互相压在一起
- **原因**：Grafana 的 dashboard 容器是**虚拟滚动**的，只渲染视口内的面板；
  扩展页面高度后下面的面板不会重新渲染
- **判据**：先 dump JSON 里的 `gridPos`（`x/y/w/h`）—— 坐标正确就是**截图问题**，不是布局问题
- **处理**：逐个面板 `&viewPanel=<id>` 截图，或用足够高的 viewport

---

## C. Grafana API 与环境

### 21. ✅ `POST /api/ds/query` 缺 `from`/`to` → 静默返回空

- **现象**：`frames` 里 `values` 为空，**但不报错**，看着像「没数据」
- **处理**：补顶层 `"from": "<epoch_ms>", "to": "<epoch_ms>"`
- **附**：Grafana 10.x 用 **`Authorization: Bearer <token>` 请求头**；
  传 `params.auth` 会报 `unexpected parameter "auth"`

### 22. ✅ `kubectl exec -i` 传 JSON 时加了 `< /dev/null` → `bad request data`

- **现象**：Grafana 回 `bad request data`，看着像 payload 有问题
- **原因**：`< /dev/null` 把管道掐断，`curl` 收到**空 body**
- **处理**：**不要重定向**；用 `--data-binary @-` 直接喂管道

### 23. ✅ 在 NFS 上改 Grafana 文件夹名 → 请求挂死 / 后续写请求全 500

- **现象**：`PUT /api/folders/:uid` 不返回（实测 2 分钟+ 才被 context canceled）；
  日志报 `database is locked` + `Failed to update alert rules in the folder after its title was changed`
- **原因**：Grafana 的 SQLite 跑在 NFS 上；改标题会走 ngalert「更新该文件夹内告警规则」分支 →
  拿不到写锁
- **⚠️ 容易误判**：看起来像「标题里有中文导致的」→ 实测 **ASCII 标题一样 500**（同一把锁），不是编码问题
- **处理（已验证的绕行）**：
  1. `POST /api/folders` 新建目标名文件夹
  2. `POST /api/dashboards/db` 带新 `folderUid` + `overwrite=true` 重新导入 dashboard
  3. `DELETE /api/folders/<旧 uid>` 删掉空文件夹
- **根治**：把 `grafana.db` 挪到本地盘或换 Postgres —— 属环境变更，需用户授权

---

## D. 附带（Prometheus / Grafana 环境侧）

### 24. ✅ Loki 侧：日志类面板排障三连

- **Grafana 10.3.3 的 log-volume 面板 LogQL 与 Loki 2.6.1 不兼容** →
  `drop` / `keep` stage 在 2.6.1 不存在 → 400 parse error；
  Grafana 10.3.3 **没有 feature toggle 能关掉它**（`logVolumes` 是 React 内部变量名）
- **Loki 查询并发被打爆** → 实测 429×112、499×212（query_range 累计）→ 演练前先降并发
- **Loki `reject_old_samples_max_age: 168h`** → 7 天前的日志行推入即被拒

### 25. ✅ Grafana 数据源目录被 sidecar 污染

- **现象**：datasources 目录里出现一堆不是数据源的东西
- **原因**：sidecar 会把**整个 ns 的 ConfigMap + Secret** 复制过去；
  Grafana 会把 `.yaml` 当 datasource provisioning 解析
- **处理**：给 sidecer 配 `ignoredNamespaces` / 文件名过滤，别让它复制业务 ConfigMap

---

## 新坑怎么进来

1. 按 `field-reports/TEMPLATE.md` 写一份脱敏报告
2. 逐条判断：
   - 以后还会遇到 → 写进本文（**现象 → 原因 → 处理**）
   - 能自动检测 → 在 `scripts/` 里加判定
   - 能自动修复 → 改脚本 + 补测试
   - 只是这次的特例 → 只留在报告里
3. 在报告里标注 `状态：promoted → pitfalls.md #N`
4. 更新 `CHANGELOG.md` 的 `[Unreleased]`
