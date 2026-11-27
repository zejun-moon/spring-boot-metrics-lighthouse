---
date: 2026-11-25
environment: Grafana 10.3.3（SQLite on NFS）+ Prometheus（kube-prometheus-stack）
result: success
skill_version: 0.1.0
operator: agent
---

# Grafana 面板排障：三个「看起来像数据问题」其实是配置问题

> 脱敏报告。本篇记录的是**展示层**的三次误判 —— 每次都先怀疑数据，
> 最后发现是 Grafana 的配置/环境问题。

## 1. 背景

要给混沌演练配一块「故障速查」dashboard：每个面板 = 一个可观测信号 +
一句「这个现象说明什么」。核心诉求是**演练时 30 秒内判断出谁挂了**。

数据源已经是现成的（Prometheus + 5 个业务服务的指标）。

## 2. 第一次误判：Y 轴冒出 `noValue` 文案

- **现象**：面板**明明有数据**，Y 轴上却平白多出几行 `noValue` 文案，每个 series 一行。
  在演练里这会被直接误读成「数据断流」
- **第一反应**：查数据源 → 正常；查 Prometheus → 有数据；查查询表达式 → 正常
- **对照实验**（同一查询，只改一个参数，逐个截图比对）：

  | 面板 | `decimals` | `noValue` | 结果 |
  |---|---|---|---|
  | P | 无 | 有 | ✅ 干净 |
  | Q | `0` | 有 | ❌ 文案漏进 Y 轴 |
  | M | 无 | 有（**空数据**） | ✅ noValue 正常显示 |
  | N | 无 | 无（空数据） | 显示 "No data"（对照组） |

- **根因**：`decimals` 是整数时，Grafana 按「刻度值」生成 Y 轴标签，
  此时**字符串型 `noValue`** 被当成一个额外的数值类别混进刻度
- **结论**：**时序图面板一律不设 `decimals`**
- **顺带排除的误判路径**：先把 `up` 拉出来看采样点 —— 241 个点全是 `1`、零空值，
  排除了「查询有空值」这条路径

> **教训**：先做**对照实验**（一次只改一个参数），再下结论。
> 「感觉像数据问题」是最贵的错误起点。

## 3. 第二次误判：截图看起来「面板重叠、标题丢失」

- **现象**：整页截图里面板内容互相压在一起，标题也不见了
- **第一反应**：以为布局算错了 → 想去改 `gridPos`
- **判据**：先把 dashboard JSON 里的 `gridPos`（`x/y/w/h`）dump 出来 → **坐标完全正确**
- **根因**：Grafana 的 dashboard 容器是**虚拟滚动**的，只渲染视口内的面板；
  扩展页面高度后下面的面板**不会重新渲染** → 截图假象
- **正确验法**：逐个面板 `&viewPanel=<id>` 截图，或用足够高的 viewport

> **教训**：截图异常**先 dump JSON 坐标**。坐标对 = 截图问题，不是布局问题。
> 否则会为了一个不存在的 bug 去改本来正确的布局。

## 4. 第三次误判：改文件夹名 → 请求挂死

- **现象**：`PUT /api/folders/:uid` 不返回（实测 2 分钟+ 才被 context canceled），
  后续写请求被拖成 500
- **第一反应**：怀疑是**标题里有中文**导致的编码问题
- **实测**：ASCII 标题**一样 500** → 同一把锁，不是编码问题
- **日志**：`database is locked` + `Failed to update alert rules in the folder after its title was changed`
- **根因**：Grafana 的 SQLite 跑在 **NFS** 上；改标题会走 ngalert
  「更新该文件夹内告警规则」分支 → 拿不到写锁
- **绕行（已验证）**：
  1. `POST /api/folders` 新建目标名文件夹
  2. `POST /api/dashboards/db` 带新 `folderUid` + `overwrite=true` 重新导入
  3. `DELETE /api/folders/<旧 uid>` 删掉空文件夹
- **根治**：把 `grafana.db` 挪到本地盘或换 Postgres → **环境变更，需授权**（未做）

## 5. 顺带沉淀的两个 API 坑

| # | 坑 | 表现 | 正解 |
|---|---|---|---|
| 1 | `POST /api/ds/query` 缺顶层 `from`/`to` | `frames.values` 为空但**不报错** | 补 `"from"` / `"to"`（epoch ms） |
| 2 | Grafana 10.x 改用 `Authorization: Bearer` 头 | 传 `params.auth` → `unexpected parameter "auth"` | 用请求头 |

外加 `kubectl exec -i` 传 JSON 时**不要 `< /dev/null`**（管道被掐断 → 空 body）。

## 6. 设计上的一条结论

这块板的每个面板都写成「**一个信号 + 一句这个现象说明什么**」，
标题与 description 双写。另外专门加了一个 `state-timeline` 状态带面板
（数据源 `kube_deployment_status_replicas_available`，覆盖**全部** deployment）。

**为什么必须用它**：只有 Prometheus 指标的服务是少数
（admin / config / discovery / grafana / mysql / tracing **都没有**指标），
所以「谁挂了」的**唯一权威答案**是 deployment 可用副本数，不是某个 Prometheus 指标。

> 踩坑收益：**config-server 挂了 → 其他服务指标完全正常**（配置是启动时从 git 后端拉的），
> 只是服务重启后拿不到配置 → 表现为「Pod 起不来」而不是「指标消失」。
> 光看指标面板会完全看不出来。

## 7. 状态提升

| 问题 | 去向 |
|---|---|
| `decimals` + 字符串 noValue | `pitfalls.md` #19 |
| fullPage 截图 = 虚拟滚动 | `pitfalls.md` #20 |
| NFS 上改文件夹名挂死 | `pitfalls.md` #23 |
| ds/query 缺 from/to | `pitfalls.md` #21 |
| Bearer 头 | `pitfalls.md` #21 |
| exec -i 加重定向 | `pitfalls.md` #22 |
| 断流 vs 值为 0 | `pitfalls.md` #8 |
