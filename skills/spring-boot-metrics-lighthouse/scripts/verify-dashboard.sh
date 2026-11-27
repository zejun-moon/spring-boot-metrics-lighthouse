#!/usr/bin/env bash
# verify-dashboard.sh —— 逐条跑 dashboard 里的 PromQL，标出空结果
#
# 为什么需要它：**「dashboard 导入成功」不等于「面板有数据」**。
# 导入接口只校验 JSON 结构，不校验查询有没有结果。
# 空结果的面板绝大多数不是 Grafana 的问题，而是**指标口径不对**
# （表达式里的标签不存在 / 指标名写错 / 没有流量 / bucket 缺失）。
#
# 用法：
#   bash verify-dashboard.sh --dashboard dashboard.json --prometheus http://prometheus:9090
#   bash verify-dashboard.sh --dashboard dashboard.json --prometheus http://prometheus:9090 \
#        --range 3600 --interval 60
#
# 退出码：0=全部有数据 · 1=存在空结果 · 2=用法/连接错误
set -uo pipefail

DASHBOARD=""
PROMETHEUS=""
RANGE=3600
INTERVAL=60
AUTH_HEADER=""

usage() {
  cat <<'EOF'
用法: verify-dashboard.sh --dashboard <json> --prometheus <url> [选项]
  --dashboard   dashboard JSON 文件
  --prometheus  Prometheus 地址（如 http://prometheus.monitoring.svc:9090）
  --range       时间范围秒数（默认 3600）—— 替换 $__range
  --interval    步长秒数（默认 60）        —— 替换 $__interval
  --auth        Authorization 头值（如 'Bearer <token>'）
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dashboard)  DASHBOARD="${2:-}"; shift 2 ;;
    --prometheus) PROMETHEUS="${2:-}"; shift 2 ;;
    --range)      RANGE="${2:-}"; shift 2 ;;
    --interval)   INTERVAL="${2:-}"; shift 2 ;;
    --auth)       AUTH_HEADER="${2:-}"; shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$DASHBOARD" ] || [ -z "$PROMETHEUS" ]; then
  echo "错误: 需要 --dashboard 和 --prometheus" >&2
  usage
  exit 2
fi

[ -f "$DASHBOARD" ] || { echo "错误: 文件不存在: $DASHBOARD" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "错误: 需要 python3" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "错误: 需要 curl" >&2; exit 2; }

PROMETHEUS="${PROMETHEUS%/}"

# 用 Prometheus 自己的 API 做健康检查
if ! curl -sS --max-time 10 "$PROMETHEUS/-/ready" >/dev/null 2>&1; then
  curl -sS --max-time 10 "$PROMETHEUS/api/v1/query?query=up" >/dev/null 2>&1 || {
    echo "错误: 连不上 Prometheus: $PROMETHEUS" >&2
    exit 2
  }
fi

echo "Prometheus : $PROMETHEUS"
echo "Dashboard  : $DASHBOARD"
echo "时间范围   : ${RANGE}s   步长: ${INTERVAL}s"
echo

# ── 抽出所有 panel 的表达式 ────────────────────────────────────────
EXPRS="$(python3 - "$DASHBOARD" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
for p in d.get('panels', []):
    title = p.get('title', '?')
    for t in p.get('targets', []):
        e = t.get('expr')
        if e:
            print('%s\t%s' % (title, e.replace('\n', ' ')))
PY
)"

if [ -z "$EXPRS" ]; then
  echo "错误: dashboard 里没找到任何 expr" >&2
  exit 2
fi

TOTAL=0
EMPTY=0
FAILED=0

while IFS=$'\t' read -r TITLE EXPR; do
  [ -z "$EXPR" ] && continue
  TOTAL=$((TOTAL + 1))

  # Grafana 变量 → Prometheus 能懂的东西
  Q="$EXPR"
  Q="${Q//\$__range/$RANGE}"
  Q="${Q//\$__interval/$INTERVAL}"
  Q="${Q//\$service/.*}"
  Q="${Q//\$__all/.*}"

  URL="$PROMETHEUS/api/v1/query?query=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$Q")"

  RESP="$(curl -sS --max-time 20 ${AUTH_HEADER:+-H "$AUTH_HEADER"} "$URL" 2>/dev/null)"
  COUNT="$(printf '%s' "$RESP" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('PARSE_ERROR'); raise SystemExit
if d.get('status') != 'success':
    print('ERROR'); raise SystemExit
r = d.get('data', {}).get('result', [])
print(len(r))
" 2>/dev/null)"

  case "$COUNT" in
    PARSE_ERROR|ERROR)
      FAILED=$((FAILED + 1))
      echo "⚠️  查询失败: $TITLE"
      printf '     %s\n' "$Q"
      printf '     %s\n' "$(printf '%s' "$RESP" | head -c 240)"
      ;;
    0)
      EMPTY=$((EMPTY + 1))
      echo "❌ 空结果: $TITLE"
      printf '     %s\n' "$Q"
      ;;
    *)
      echo "✅ $COUNT 条系列: $TITLE"
      ;;
  esac
done <<< "$EXPRS"

echo
echo "──────────────────────────────"
echo "共 $TOTAL 条查询：空结果 $EMPTY · 查询失败 $FAILED"
if [ "$EMPTY" -gt 0 ] || [ "$FAILED" -gt 0 ]; then
  echo
  echo "排障方向（**先口径后样式**）："
  echo "  1. 空结果 → 指标名对不对？（Micrometer 用下划线：http_server_requests_seconds_count）"
  echo "  2. 空结果 → 标签对不对？（面板依赖的是自己 relabeling 出来的 service 标签）"
  echo "  3. 空结果 → 这个服务真的没有这类事件吗？（网关不连库就没有 hikaricp_*）"
  echo "  4. 查询失败 → 表达式语法错误，看上面的错误信息"
  echo "  5. 全都对但图是空的 → 才去查 Grafana 渲染（decimals / noValue / 样式路径）"
  exit 1
fi
echo "✅ 全部查询有数据"
exit 0
