#!/usr/bin/env python3
"""gen-dashboard.py —— 生成 Spring Boot 微服务监控的 Grafana dashboard JSON。

12 个面板的口径**已按实测校正**，直接照抄官方示例会踩的坑在这里都绕开了：

  - http_server_requests_seconds 只有 _count/_sum/_max，**没有 _bucket** → 算不了 P95，
    耗时面板用「平均」和「最大值」两个口径
  - 没有 tomcat_threads_* → 不做 Tomcat 线程面板
  - jvm_memory_max_bytes 里 G1 Eden/Survivor 的 max 是负数（无界），sum 后抵消成 0
    → 不画「堆上限」线，改画 堆/非堆 已用
  - 错误率必须用 `A or 0*B` 写法，否则没有 5xx 时整个表达式为空（图看起来像坏了）
  - 每个监控项的表达式都收敛成**单个 svc 标签** → 表格的 join 字段恒为 svc，
    图例和表格用的是同一套名字

用法：
    python3 gen-dashboard.py --datasource-uid <prom-uid> --namespace <ns> \
        --services svc-a,svc-b,svc-c --output dashboard.json

    # 也可以直接产出带 folderUid 的导入 payload
    python3 gen-dashboard.py ... --folder-uid <uid> --import-payload

依赖：Python 3.6+，只用标准库。
"""
import argparse
import json
import sys

DEFAULTS = {
    "namespace": "spring-petclinic-microservices",
    "dim_label": "service",
    "dashboard_uid": "spring-boot-microservices",
    "title": "Spring Boot 微服务监控",
}


def build_parser():
    p = argparse.ArgumentParser(
        description="生成 Spring Boot 微服务监控的 Grafana dashboard JSON")
    p.add_argument("--datasource-uid", required=True,
                   help="Prometheus 数据源 uid（GET /api/datasources 里拿）")
    p.add_argument("--namespace", default=DEFAULTS["namespace"],
                   help="业务命名空间（default: %(default)s）")
    p.add_argument("--services", default="",
                   help="被采集的服务名，逗号分隔（写进 dashboard 描述，便于溯源）")
    p.add_argument("--dim-label", default=DEFAULTS["dim_label"],
                   help="用于聚合的维度标签，必须与 ServiceMonitor relabeling 出的标签一致"
                        "（default: %(default)s）")
    p.add_argument("--dashboard-uid", default=DEFAULTS["dashboard_uid"],
                   help="dashboard uid（default: %(default)s）")
    p.add_argument("--title", default=DEFAULTS["title"],
                   help="dashboard 标题（default: %(default)s）")
    p.add_argument("--folder-uid", default="",
                   help="目标文件夹 uid；给了就同时产出导入 payload")
    p.add_argument("--import-payload", action="store_true",
                   help="额外输出带 folderUid/overwrite 的导入 payload")
    p.add_argument("--use-extra-table", action="store_true",
                   help="改用 Table 面板自建右侧表（中文表头，但失去 legend 点击隔离）")
    p.add_argument("--output", default="dashboard.json", help="输出文件（default: %(default)s）")
    return p


def main():
    args = build_parser().parse_args()

    if not args.datasource_uid:
        print("错误: --datasource-uid 必填", file=sys.stderr)
        return 2

    ds = {"type": "prometheus", "uid": args.datasource_uid}
    ns = args.namespace
    dim = args.dim_label
    sel = '%s=~"$service"' % dim
    base = 'namespace="%s"' % ns

    services = [s.strip() for s in args.services.split(",") if s.strip()]
    svc_desc = "、".join(services) if services else "（未指定）"

    # —— 基础表达式：标签选择器必须闭合正确 ——
    rate_all = 'http_server_requests_seconds_count{%s,%s}' % (base, sel)
    rate_5xx = 'http_server_requests_seconds_count{%s,%s,status=~"5.."}' % (base, sel)
    sum_all = 'http_server_requests_seconds_sum{%s,%s}' % (base, sel)
    max_all = 'http_server_requests_seconds_max{%s,%s}' % (base, sel)

    def svc(expr, *labels, agg="sum", sep=" · "):
        """把表达式收敛成**单个 svc 标签**。

        label_join 把若干标签拼成一个字符串标签；`agg by (svc)` 把其余标签
        （namespace / instance / pod / application …）全部丢掉
        → 每个监控项只剩一个维度，表格的 join 字段恒为 `svc`。
        """
        srcs = ", ".join('"%s"' % label for label in labels)
        return '%s by (svc) (label_join(%s, "svc", "%s", %s))' % (agg, expr, sep, srcs)

    def item(name, title, unit, dimname, expr, desc, stats, h=7, wide=False):
        """登记一个监控项。

        stats = [(想要的名字, 计算方式)]，计算方式：
          max  → max_over_time((expr)[$__range:$__interval])   峰值
          last → expr                                           当前值（instant）
          sum  → sum_over_time((expr)[$__range:$__interval])    区间累计

        stats 同时决定**右侧 legend 表显示哪几列**（Grafana 只能选 reducer，
        列名由它写死：max→Max、lastNotNull→Last *、sum→Total，
        但**每个面板可以按监控项的实际需要选不同的列组合**）。
        """
        calc_of = {"max": "max", "last": "lastNotNull", "sum": "sum"}
        calcs = [calc_of[kind] for _, kind in stats]
        sort_by = {"max": "Max", "lastNotNull": "Last *", "sum": "Total"}[calcs[0]]
        return {
            "name": name, "title": title, "unit": unit, "dim": dimname,
            "expr": expr, "desc": desc, "stats": stats, "h": h, "wide": wide,
            "calcs": calcs, "sort_by": sort_by,
        }

    items = []

    # ── 1. 流量与错误 ───────────────────────────────────────────────
    _rate = svc('rate(%s[5m])' % rate_all, dim)
    _rate5xx = svc('rate(%s[5m])' % rate_5xx, dim)

    items.append(item(
        "请求量", "请求量 (req/s)", "reqps", "服务", _rate,
        "按服务统计的 HTTP 请求速率（5 分钟滑动窗口）",
        [("峰值", "max"), ("当前", "last")]))

    items.append(item(
        "错误率", "错误率 (5xx 占比)", "percentunit", "服务",
        "(%s or 0 * %s) / clamp_min(%s, 0.000001)" % (_rate5xx, _rate, _rate),
        "HTTP 5xx 请求数 / 总请求数。用 `A or 0*B` 写法：**没有错误时显示 0 而不是空图**",
        [("峰值", "max"), ("当前", "last")]))

    # ── 2. 响应时间 ────────────────────────────────────────────────
    _sum = svc('rate(%s[5m])' % sum_all, dim)

    items.append(item(
        "平均响应时间", "平均响应时间", "s", "服务",
        "%s / clamp_min(%s, 0.000001)" % (_sum, _rate),
        "**无 _bucket 桶**（实测 0 series），故用 sum/count 求平均",
        [("峰值", "max"), ("当前", "last")]))

    items.append(item(
        "最大响应时间", "最大响应时间", "s", "服务",
        svc(max_all, dim, agg="max"),
        "Micrometer 的 decaying max（窗口内出现过的最大响应时间）",
        [("峰值", "max"), ("当前", "last")]))

    # ── 3. JVM ─────────────────────────────────────────────────────
    # area: heap → 堆 / nonheap → 非堆（正则必须锚定，否则 nonheap 会被误命中）
    _jvm_raw = 'jvm_memory_used_bytes{%s,%s}' % (base, sel)
    _jvm = ('label_replace(label_replace(%s, "area", "堆", "area", "^heap$"), '
            '"area", "非堆", "area", "^nonheap$")' % _jvm_raw)

    items.append(item(
        "JVM 内存", "JVM 内存（堆 / 非堆）", "bytes", "服务 / 内存区",
        svc(_jvm, dim, "area"),
        "**不画上限线**：实测 G1 Eden/Survivor 的 max 是负数（无界），sum 后抵消成 0",
        [("峰值", "max"), ("当前", "last")]))

    items.append(item(
        "GC 暂停时间", "GC 暂停时间", "s", "服务",
        svc('rate(jvm_gc_pause_seconds_sum{%s,%s}[5m])' % (base, sel), dim),
        "GC 总暂停时长速率。**多一列「累计」** —— GC 最该看的是这段时间窗里的累计暂停",
        [("峰值", "max"), ("当前", "last"), ("累计", "sum")]))

    items.append(item(
        "线程数", "线程数", "short", "服务",
        svc('jvm_threads_live_threads{%s,%s}' % (base, sel), dim),
        "存活线程数（按服务汇总）",
        [("峰值", "max"), ("当前", "last")]))

    items.append(item(
        "进程 CPU", "进程 CPU 占用", "percentunit", "服务",
        svc('process_cpu_usage{%s,%s}' % (base, sel), dim),
        "进程 CPU 使用率（按服务汇总）",
        [("峰值", "max"), ("当前", "last")]))

    # ── 4. 连接池与日志 ────────────────────────────────────────────
    # state: 用 label_replace 给三种连接状态打标签，再 label_join 成「服务 · 状态」
    def _state(metric, label):
        return ('label_replace(%s{%s,%s}, "state", "%s", "%s", "^(.*)$")'
                % (metric, base, sel, label, dim))

    _conn = "(%s or %s or %s)" % (
        _state("hikaricp_connections_active", "活跃"),
        _state("hikaricp_connections_pending", "等待"),
        _state("hikaricp_connections_max", "上限"))

    items.append(item(
        "DB 连接池", "DB 连接池 (HikariCP)", "short", "服务 / 连接状态",
        svc(_conn, dim, "state"),
        "只有连库的服务才有 HikariCP 指标；网关类服务（不连库）此面板为空是**正常的**",
        [("峰值", "max"), ("当前", "last")]))

    items.append(item(
        "日志级别分布", "日志级别分布", "short", "服务 / 级别",
        svc('rate(logback_events_total{%s,%s}[5m])' % (base, sel), dim, "level"),
        "logback_events_total 按级别。**行 = 服务 · 级别**；系列数 = 服务数 × 级别数"
        "（实测 5 服务 × 5 级别 = 25 条），半宽时右侧 legend 表会把绘图区挤窄",
        [("当前", "last")], h=9))

    items.append(item(
        "错误日志速率", "错误日志速率", "short", "服务",
        svc('rate(logback_events_total{%s,%s,level="error"}[5m])' % (base, sel), dim),
        "ERROR 级别日志速率。**错误是稀疏事件**，只列峰值 —— 当前值常年为 0",
        [("峰值", "max")]))

    # ── 5. Top URI ─────────────────────────────────────────────────
    # uri + status → svc = 「<服务> <uri> [<status>]」
    _topk = 'topk(5, sum by (%s, uri, status) (rate(%s[5m])))' % (dim, rate_all)
    _topk_tagged = 'label_replace(%s, "st", "[$1]", "status", "^(.*)$")' % _topk

    items.append(item(
        "请求 Top URI", "请求 Top URI（含状态码）", "reqps", "服务 / URI",
        svc(_topk_tagged, dim, "uri", "st", sep=" "),
        "流量最大的 URI Top5（带状态码）。不限定 5xx —— 否则一切正常时是空图。"
        "⚠️ topk 不能同时算「峰值列」和「当前列」：两个查询各算各的 topk → 合并后对不上",
        [("峰值", "max"), ("当前", "last")]))

    # ══════════════════════════════════════════════════════════════
    # 面板生成
    # ══════════════════════════════════════════════════════════════

    def chart_panel(it, x, y, w, h):
        """时序图 + **右侧可点击的 legend 表**。

        legend 用 **table 模式**：每行 = 一条系列，带色块 + 当前窗口统计值；
        **点一行就能在图里只看那一条线**（Grafana 原生交互）。
        """
        return {
            "type": "timeseries", "title": it["title"],
            "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "datasource": ds,
            "description": it["desc"],
            "fieldConfig": {
                "defaults": {
                    "unit": it["unit"],
                    "color": {"mode": "palette-classic"},
                    "custom": {
                        "drawStyle": "line", "lineWidth": 1,
                        "fillOpacity": 0,
                        "showPoints": "never", "spanNulls": False,
                        "stacking": {"mode": "none", "group": "A"},
                        "axisPlacement": "left",
                        "scaleDistribution": {"type": "linear"},
                        "gradientMode": "none",
                        # ⚠️ 不要设 decimals —— 整数 decimals 会让字符串型 noValue
                        #    被当成额外数值类别混进 Y 轴刻度
                    },
                },
                "overrides": [],
            },
            "options": {
                "legend": {
                    "displayMode": "table",
                    "placement": "right",
                    "showLegend": True,
                    "calcs": it["calcs"],
                    # ⚠️ sortBy 按**列显示名**匹配，不是 reducer id
                    "sortBy": it["sort_by"],
                    "sortDesc": True,
                    "alignAsTable": True, "rightValue": False,
                },
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
            "targets": [{
                "refId": "A", "expr": it["expr"], "legendFormat": "{{svc}}",
                "format": "time_series", "interval": "", "datasource": ds,
            }],
        }

    def stat_expr(base_expr, kind):
        if kind == "max":
            return 'max_over_time((%s)[$__range:$__interval])' % base_expr
        if kind == "sum":
            return 'sum_over_time((%s)[$__range:$__interval])' % base_expr
        return base_expr

    def table_panel(it, x, y, w, h):
        """右上角明细表：标题 = 监控项名字，列名 = 自定义中文。

        值列命名规则（Grafana 前端 result_transformer.ts 的 getValueText）：
          该响应里**有多个 refId** → `Value #<refId>`；**只有一个 refId** → `Value`
        → 面板只有一个查询时，重命名必须用 `Value`，否则 organize 匹配不上、列名保持英文
        """
        targets, rename, index = [], {}, {}
        multi = len(it["stats"]) > 1
        for i, (col, kind) in enumerate(it["stats"]):
            ref = chr(ord("A") + i)
            targets.append({
                "refId": ref, "expr": stat_expr(it["expr"], kind),
                "format": "table",
                "instant": True, "range": False,
                "legendFormat": "{{svc}}",
                "interval": "", "intervalMs": 15000, "maxDataPoints": 100,
                "editorMode": "code", "datasource": ds,
            })
            value_col = "Value #%s" % ref if multi else "Value"
            rename[value_col] = col
            index[value_col] = i + 1
        rename["svc"] = it["dim"]
        index["svc"] = 0
        return {
            "type": "table", "title": it["name"],
            "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "datasource": ds,
            "description": "行 = %s，列 = 统计值" % it["dim"],
            "targets": targets,
            "transformations": [
                # ⚠️ mode 必须是 outerTabular（按字段值配对）；outer 是按时间配对，
                #    对 instant 查询不适用
                {"id": "joinByField", "options": {"byField": "svc", "mode": "outerTabular"}},
                {"id": "organize", "options": {
                    # 合并后 Time 列会出现两次，excludeByName 会把两个都排除
                    "excludeByName": {"Time": True},
                    "renameByName": rename,
                    "indexByName": index,
                }},
            ],
            "options": {
                "showHeader": True, "cellHeight": "sm",
                "footer": {"show": False},
                "sortBy": [{"desc": False, "displayName": it["dim"]}],
            },
            "fieldConfig": {
                "defaults": {
                    "unit": it["unit"],
                    "color": {"mode": "thresholds"},
                    "thresholds": {"mode": "absolute", "steps": [{"color": "text", "value": None}]},
                    "custom": {"align": "auto", "cellOptions": {"type": "auto"}},
                },
                "overrides": [],
            },
        }

    panels = []
    if args.use_extra_table:
        # 备选布局：一行一项 = 左侧时序图 + 右上角真表（中文表头，但**不可点击联动**）
        y = 0
        for it in items:
            panels.append(chart_panel(it, 0, y, 18, it["h"]))
            panels.append(table_panel(it, 18, y, 6, it["h"]))
            y += it["h"]
    else:
        # 默认布局：每项 = 时序图 + **右侧原生 legend 表**（可点击、可联动、实时）
        x, y = 0, 0
        for it in items:
            w = 24 if it.get("wide") else 12
            if x + w > 24:
                x, y = 0, y + 8
            panels.append(chart_panel(it, x, y, w, 8))
            x += w
            if x >= 24:
                x, y = 0, y + 8

    # 面板 id：按生成顺序固定编号 → 重复导入幂等，面板级书签 #viewPanel=N 不失效
    for i, p in enumerate(panels, start=1):
        p["id"] = i

    dashboard = {
        "uid": args.dashboard_uid,
        "title": args.title,
        "description": (
            "Spring Boot 微服务的 JVM / HTTP / 连接池 / 日志指标。"
            "每个监控项 = 左侧时序图 + 右侧原生 legend 表（可点击联动）。"
            "采集入口 = ServiceMonitor（path=/actuator/prometheus）；"
            "维度标签 = %s；命名空间 = %s；采集服务 = %s。"
            % (dim, ns, svc_desc)),
        "tags": ["spring-boot", "microservices", "prometheus", "grafana"],
        "timezone": "browser",
        "editable": True,
        "schemaVersion": 39,
        "version": 1,
        "refresh": "",
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m", "15m"]},
        "templating": {"list": [{
            "name": "service", "label": "服务", "type": "query",
            "datasource": ds,
            "definition": 'label_values(up{%s}, %s)' % (base, dim),
            "query": {"query": 'label_values(up{%s}, %s)' % (base, dim),
                      "refId": "StandardVariableQuery"},
            "multi": True, "includeAll": True, "allValue": ".*",
            "refresh": 2, "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
            "options": [],
        }]},
        "panels": panels,
        "annotations": {"list": [{
            "builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard",
        }]},
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)
    print("已生成 %s（%d 个面板）" % (args.output, len(panels)))

    if args.import_payload:
        payload = {"dashboard": dashboard, "overwrite": True}
        if args.folder_uid:
            payload["folderUid"] = args.folder_uid
        payload_file = args.output.rsplit(".", 1)[0] + ".import.json"
        with open(payload_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("已生成导入 payload: %s" % payload_file)
        print("导入: POST /api/dashboards/db  -H 'Authorization: Bearer <token>' "
              "-H 'Content-Type: application/json' --data-binary @%s" % payload_file)

    print()
    print("自检提醒：")
    print("  1. 用 verify-dashboard.sh 逐条跑查询 —— 导入成功 ≠ 面板有数据")
    print("  2. 导入时用 Authorization: Bearer <token> 请求头（Grafana 10.x）")
    print("  3. kubectl exec -i 传 JSON 时不要加 '< /dev/null'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
