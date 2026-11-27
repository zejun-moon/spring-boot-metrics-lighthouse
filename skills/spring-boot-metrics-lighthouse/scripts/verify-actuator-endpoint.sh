#!/usr/bin/env bash
# verify-actuator-endpoint.sh —— 探测 Spring Boot actuator 指标端点，三态判定
#
# 为什么需要它：target up=1 **不等于**采到指标了。
#   - 配置服务器会把 /actuator/prometheus 当成 {application}/{profile} 解析 → 返回 200 + JSON（假阳性）
#   - 缺 micrometer-registry-prometheus → 返回 404
#   - 真的装了 registry → 返回 200 + 文本指标（内容含 # HELP / # TYPE）
#
# 用法：
#   bash verify-actuator-endpoint.sh --url http://svc.ns.svc.cluster.local:8080/actuator/prometheus
#   bash verify-actuator-endpoint.sh --url ... --expect-metrics jvm_memory_used_bytes,http_server_requests_seconds_count
#
# 退出码：0=有真指标 · 1=假阳性 200 · 2=404/其它错误 · 3=用法错误
set -uo pipefail

URL=""
EXPECT_METRICS=""
TIMEOUT=10

usage() {
  cat <<'EOF'
用法: verify-actuator-endpoint.sh --url <url> [--expect-metrics a,b] [--timeout <sec>]
  --url              指标端点完整 URL（通常是 http://<svc>.<ns>.svc.cluster.local:<port>/actuator/prometheus）
  --expect-metrics  逗号分隔的期望指标名，缺任意一个即判定为「没有指标」
  --timeout          单次请求超时秒数（默认 10）
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --url)            URL="${2:-}"; shift 2 ;;
    --expect-metrics) EXPECT_METRICS="${2:-}"; shift 2 ;;
    --timeout)        TIMEOUT="${2:-}"; shift 2 ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 3 ;;
  esac
done

if [ -z "$URL" ]; then
  echo "错误: 必须提供 --url" >&2
  usage
  exit 3
fi

command -v curl >/dev/null 2>&1 || { echo "错误: 需要 curl" >&2; exit 3; }

BODY_FILE="$(mktemp)"
HDR_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE" "$HDR_FILE"' EXIT

HTTP_CODE="$(curl -sS --max-time "$TIMEOUT" -o "$BODY_FILE" -D "$HDR_FILE" -w '%{http_code}' "$URL" 2>/dev/null || echo 000)"
CONTENT_TYPE="$(grep -i '^content-type:' "$HDR_FILE" 2>/dev/null | head -1 | tr -d '\r' | cut -d' ' -f2- | tr -d ' ')"

echo "URL         : $URL"
echo "HTTP 状态   : $HTTP_CODE"
echo "Content-Type: ${CONTENT_TYPE:-<none>}"

# ── 1) 404 / 网络错误 ─────────────────────────────────────────────
if [ "$HTTP_CODE" = "000" ]; then
  echo
  echo "❌ 判定: 连不上"
  echo "   排查: 服务没起？端口对不对？Service 的 targetPort 是多少？"
  exit 2
fi

if [ "$HTTP_CODE" = "404" ]; then
  echo
  echo "❌ 判定: 404 —— 没有这个端点"
  echo "   常见原因（按可能性排序）："
  echo "     1. 路径写成 /metrics —— Spring Boot 没有这个路径，必须是 /actuator/prometheus"
  echo "     2. 缺 micrometer-registry-prometheus 依赖（actuator + micrometer-core 装了也不够）"
  echo "     3. management.endpoints.web.exposure.include 没包含 prometheus"
  echo "   验证依赖: unzip -l <app>.jar | grep micrometer-registry-prometheus"
  exit 2
fi

if [ "$HTTP_CODE" != "200" ]; then
  echo
  echo "❌ 判定: HTTP $HTTP_CODE"
  echo "   403 → management 端口有安全策略（检查 management.security.enabled）"
  echo "   5xx → 服务侧异常，看服务日志"
  exit 2
fi

# ── 2) 200 但不是指标（假阳性）─────────────────────────────────────
IS_METRICS=0
if grep -qE '^# (HELP|TYPE)' "$BODY_FILE" 2>/dev/null; then
  IS_METRICS=1
fi

if [ "$IS_METRICS" -eq 0 ]; then
  echo
  echo "❌ 判定: 200 但是**假阳性** —— 返回的不是指标"
  echo "   Content-Type 是 ${CONTENT_TYPE:-<none>}，响应体开头："
  head -c 200 "$BODY_FILE" | sed 's/^/     /'
  echo
  echo "   典型场景: 配置服务器（config-server）把 /actuator/prometheus 当成"
  echo "             {application}/{profile} 解析 → 返回 JSON 配置内容。"
  echo "   它的镜像里根本没有 actuator/micrometer jar，本就不该被采集。"
  echo "   处理: 用 ServiceMonitor 的 relabelings keep 白名单排除它。"
  exit 1
fi

# ── 3) 是真指标 ────────────────────────────────────────────────────
METRIC_COUNT="$(grep -cE '^[a-zA-Z_:][a-zA-Z0-9_:]*\{' "$BODY_FILE" 2>/dev/null || echo 0)"
echo
echo "✅ 判定: 真指标端点"
echo "   指标行数: $METRIC_COUNT"

MISSING=""
if [ -n "$EXPECT_METRICS" ]; then
  IFS=',' read -ra WANT <<< "$EXPECT_METRICS"
  for m in "${WANT[@]}"; do
    m="$(echo "$m" | tr -d ' ')"
    [ -z "$m" ] && continue
    if ! grep -q "^${m}\(\{\| \|$\)" "$BODY_FILE" 2>/dev/null; then
      MISSING="${MISSING:+$MISSING, }$m"
    fi
  done
  if [ -n "$MISSING" ]; then
    echo "   ⚠️ 缺少期望指标: $MISSING"
    echo "      → 可能是该服务没这个能力（如网关不连库就没有 hikaricp_*）"
    echo "      → 或 micrometer 版本差异导致指标名不同"
    exit 0
  fi
  echo "   期望指标全部命中: $EXPECT_METRICS"
fi

echo
echo "下一步: 用 check-servicemonitor.sh 验采集层，用 verify-dashboard.sh 验展示层。"
exit 0
