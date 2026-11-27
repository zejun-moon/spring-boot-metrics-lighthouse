# Grafana API 与图表配置排障

> Grafana 侧的 6 个坑。前 3 个是 API，后 3 个是渲染/配置。
> 关联坑：`pitfalls.md` #19 #20 #21 #22 #23 #25

## 1. ✅ `POST /api/ds/query` 缺 `from`/`to` → 静默返回空

- **现象**：`frames` 里 `values` 为空，**但不报错**，看着像「没数据」
- **原因**：该端点不默认推断时间范围，缺了就不查
- **处理**：补顶层时间戳

```bash
curl -sS -X POST "$GRAFANA/api/ds/query" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"from\":\"$(date +%s000)\",\"to\":\"$(date +%s000)\",\"queries\":[...]}"
```

- **⚠️ 另一个限制** 📄：后端 Prometheus 查询模型**没有 Format 字段** →
  用这个端点**测不出 table 格式的列名**，只能看源码 + 最终 dashboard

## 2. ✅ Grafana 10.x 用 `Authorization: Bearer` 请求头

- **现象**：传 `params.auth` → 报 `unexpected parameter "auth"`
- **原因**：10.x 改成请求头传 token
- **处理**：

```bash
-H "Authorization: Bearer $TOKEN"
```

> ⚠️ **别把 token 写进 URL 或命令行参数**（会进 shell history / ps 输出）。
> 用环境变量或 header 文件。

## 3. ✅ `kubectl exec -i` 传 JSON 时不要加 `< /dev/null`

- **现象**：Grafana 回 `bad request data`，看着像 payload 有问题
- **原因**：`< /dev/null` 把管道掐断，`curl` 收到**空 body**
- **处理**：**不要重定向**，直接喂管道

```bash
kubectl exec -i <grafana-pod> -n <ns> -- curl -sS -X POST \
  http://localhost:3000/api/dashboards/db \
  -H 'Content-Type: application/json' --data-binary @- < dashboard.json
```

## 4. ✅ 在 NFS 上改文件夹名 → 请求挂死

- **现象**：`PUT /api/folders/:uid` 不返回（实测 2 分钟+ 才被 context canceled）；
  后续写请求被重试风暴拖成 500
- **日志**：`database is locked` + `Failed to update alert rules in the folder after its title was changed`
- **原因**：Grafana 的 SQLite 跑在 NFS 上；改标题会走 ngalert「更新该文件夹内告警规则」分支 →
  拿不到写锁
- **⚠️ 常见误判**：像「标题里有中文导致的」→ 实测 **ASCII 标题一样 500**（同一把锁），不是编码问题
- **处理（已验证的绕行）**：

```bash
# ① 新建目标名文件夹
curl -sS -X POST "$GRAFANA/api/folders" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"title":"<新标题>"}'
# ② 把 dashboard 导进新文件夹
curl -sS -X POST "$GRAFANA/api/dashboards/db" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --slurpfile d dashboard.json '{dashboard:$d[0],folderUid:"<新uid>",overwrite:true}')"
# ③ 删掉旧空文件夹
curl -sS -X DELETE "$GRAFANA/api/folders/<旧uid>" -H "Authorization: Bearer $TOKEN"
```

- **根治**：把 `grafana.db` 挪到本地盘或换 Postgres → **环境变更，需用户授权**

## 5. ✅ `decimals` + 字符串型 `noValue` → Y 轴冒出文案

- **现象**：**有数据**时，Y 轴上平白多出几行 `noValue` 文案（每个 series 一行），
  看起来像「数据断了」
- **原因**：`decimals` 是整数时 Grafana 按「刻度值」生成 Y 轴标签，
  此时**字符串型 `noValue`** 被当成一个额外的数值类别混进刻度
- **对照实验**（同一查询、只改一个参数）：

  | decimals | noValue | 结果 |
  |---|---|---|
  | 无 | 有 | ✅ 干净 |
  | `0` | 有 | ❌ 文案漏进 Y 轴 |
  | 无 | 有（空数据） | ✅ noValue 正常显示 |
  | 无 | 无（空数据） | 显示 "No data"（对照） |

- **处理**：**时序图面板一律不设 `decimals`**
- **排查顺序**：先确认是不是**数据空值**造成的 —— 把 `up` 拉出来看采样点是否全为 1、
  零空值，排除「查询有空值」这条误判路径

## 6. ✅ 全屏截图看起来「面板重叠、标题丢失」

- **现象**：整页截图里面板内容互相压在一起、标题不见了
- **原因**：Grafana 的 dashboard 容器是**虚拟滚动**的，只渲染视口内的面板；
  扩展页面高度后下面的面板**不会重新渲染**
- **判据**：先 dump JSON 里的 `gridPos`（`x/y/w/h`）——
  **坐标正确就是截图问题，不是布局问题**
- **处理**：逐个面板 `&viewPanel=<id>` 截图，或用足够高的 viewport

## 7. ✅ 数据源目录被 sidecar 污染

- **现象**：datasources 目录里出现一堆不是数据源的东西
- **原因**：Prometheus Operator 的 sidecar 会把**整个 ns 的 ConfigMap + Secret** 复制过去；
  Grafana 会把 `.yaml` 当 datasource provisioning 解析 → 一堆报错
- **处理**：给 sidecar 配忽略规则（`ignoredNamespaces` / 文件名过滤），
  别让它复制业务 ConfigMap

## 8. ✅ Grafana 健康检查用错端点

- **`/api/health` 是免认证的** → 用它验不出 token 对不对
- **验 token 要打 `/api/datasources`**（需要认证）

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$GRAFANA/api/datasources" \
  -H "Authorization: Bearer $TOKEN"     # 期望 200
```

## 9. ✅ 容器 env 里的管理员口令改不动

- **现象**：改了 `GF_SECURITY_ADMIN_PASSWORD` 还是登不进去
- **原因**：Grafana 10 起，admin 相关的 env **只在首次启动生效**；
  之后改了密码就以 DB 里的为准
- **处理**：`admin` 用户在 DB 里，login = `admin`；
  口令以 DB 为准，不要指望改 env

## 10. 排障顺序

```
① token 能用吗      → GET /api/datasources（不是 /api/health）
② 数据源能连上吗    → GET /api/datasources/<uid>/health
③ 查询有数据吗      → POST /api/ds/query（带 from/to）
④ 面板表达式对吗    → 逐条跑 PromQL
⑤ 渲染配置对吗      → dump JSON 的 gridPos / fieldConfig / options
```

**不要一上来就在 UI 里调样式。** 前三步能定位 90% 的问题。
