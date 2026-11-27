#!/usr/bin/env bash
# check-servicemonitor.sh —— 校验 ServiceMonitor / PodMonitor 的采集配置
#
# 校验三件最容易静默失效的事：
#   1. 缺 release 标签 → 被 Prometheus 的 serviceMonitorSelector 静默丢弃（对象存在、target=0、无报错）
#   2. selector 为空却没有 keep 白名单 → 抓到一堆无关服务（端口都叫 http 时尤其致命）
#   3. path 不是 /actuator/prometheus → 必然 404
#
# 用法：
#   bash check-servicemonitor.sh --namespace <ns> --name <sm-name> [--expect-services a,b] [--file sm.yaml]
#   bash check-servicemonitor.sh --file sm.yaml --expect-services a,b     # 离线校验（CI 用）
#
# 退出码：0=通过 · 1=发现问题 · 2=用法错误
set -uo pipefail

NAMESPACE=""
NAME=""
EXPECT_SERVICES=""
FILE=""
RELEASE_LABEL="kube-monitor"

usage() {
  cat <<'EOF'
用法: check-servicemonitor.sh (--namespace <ns> --name <sm> | --file <yaml>) [选项]
  --namespace        ServiceMonitor 所在命名空间（用 kubectl 读取时必填）
  --name             ServiceMonitor 名称
  --file             离线校验：直接读本地 YAML（CI / 无集群时用）
  --expect-services  期望被采集的服务名，逗号分隔（校验 keep 白名单是否覆盖）
  --release-label    Prometheus 的 serviceMonitorSelector 用的 label 值（默认 kube-monitor）
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --namespace)       NAMESPACE="${2:-}"; shift 2 ;;
    --name)            NAME="${2:-}"; shift 2 ;;
    --file)            FILE="${2:-}"; shift 2 ;;
    --expect-services) EXPECT_SERVICES="${2:-}"; shift 2 ;;
    --release-label)   RELEASE_LABEL="${2:-}"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 2 ;;
  esac
done

if [ -z "$FILE" ] && { [ -z "$NAMESPACE" ] || [ -z "$NAME" ]; }; then
  echo "错误: 需要 --file，或 --namespace + --name" >&2
  usage
  exit 2
fi

PROBLEMS=0
note() { echo "  $1"; }
bad()  { echo "  ✗ $1"; PROBLEMS=$((PROBLEMS + 1)); }
ok()   { echo "  ✓ $1"; }

# ── 取 YAML ────────────────────────────────────────────────────────
YAML=""
if [ -n "$FILE" ]; then
  [ -f "$FILE" ] || { echo "错误: 文件不存在: $FILE" >&2; exit 2; }
  YAML="$(cat "$FILE")"
else
  command -v kubectl >/dev/null 2>&1 || { echo "错误: 需要 kubectl 或 --file" >&2; exit 2; }
  YAML="$(kubectl get servicemonitor "$NAME" -n "$NAMESPACE" -o yaml 2>/dev/null)"
  [ -z "$YAML" ] && { echo "错误: 读不到 ServiceMonitor $NAME/$NAMESPACE" >&2; exit 2; }
fi

echo "[1] release 标签（selector 硬门槛）"
# metadata.labels 下的 release
if printf '%s' "$YAML" | grep -A20 '^metadata:' | grep -qE "release:[[:space:]]*[\"']?$RELEASE_LABEL"; then
  ok "metadata.labels 命中 release: $RELEASE_LABEL"
else
  bad "metadata.labels 里没有 release: $RELEASE_LABEL"
  note "→ Prometheus 的 serviceMonitorSelector 是 matchLabels{release: <值>} 时,"
  note "  缺这个 label 会让本对象被**静默丢弃**：对象存在、target 数 = 0、全程无报错。"
  note "→ 先确认实际取值: kubectl get prometheus -n <monitoring-ns> -o jsonpath='{.spec.serviceMonitorSelector}'"
fi

echo "[2] 采集路径"
if printf '%s' "$YAML" | grep -qE 'path:[[:space:]]*/actuator/prometheus'; then
  ok "path = /actuator/prometheus"
else
  bad "path 不是 /actuator/prometheus"
  note "→ Spring Boot 没有 /metrics 这个路径，写错必然 404。"
fi

echo "[3] 白名单（selector 为空时必须有 keep）"
SELECTOR_EMPTY=0
if printf '%s' "$YAML" | grep -qE '^[[:space:]]*selector:[[:space:]]*\{\}[[:space:]]*$'; then
  SELECTOR_EMPTY=1
  ok "selector 为空（全选）"
elif printf '%s' "$YAML" | grep -qE '^[[:space:]]*selector:[[:space:]]*$'; then
  note "selector 块存在（按 label 选）—— 确认它命中目标 Service"
else
  note "未发现 selector 字段 —— 确认是否被省略"
fi

KEEP_REGEX=""
if printf '%s' "$YAML" | grep -q 'action:[[:space:]]*keep'; then
  KEEP_REGEX="$(printf '%s' "$YAML" | grep -B4 'action:[[:space:]]*keep' | grep -E 'regex:' | tail -1 | sed -E 's/.*regex:[[:space:]]*["'\'']?([^"'\'']*)["'\'']?.*/\1/')"
  if [ -n "$KEEP_REGEX" ]; then
    ok "存在 keep 规则: regex = $KEEP_REGEX"
  else
    bad "有 action: keep 但读不出 regex"
  fi
else
  if [ "$SELECTOR_EMPTY" -eq 1 ]; then
    bad "selector 为空却没有 keep 白名单"
    note "→ 空 selector = 选中本 ns 全部 Service；而同一 ns 里多个 Service 的端口常都叫 http，"
    note "  会把 admin-server / config-server / grafana-server 一起抓进来。"
  else
    ok "按 label 选择，无需 keep 白名单"
  fi
fi

echo "[4] 服务名覆盖"
if [ -n "$EXPECT_SERVICES" ]; then
  IFS=',' read -ra WANT <<< "$EXPECT_SERVICES"
  for svc in "${WANT[@]}"; do
    svc="$(echo "$svc" | tr -d ' ')"
    [ -z "$svc" ] && continue
    if [ -n "$KEEP_REGEX" ]; then
      if printf '%s' "$KEEP_REGEX" | grep -qF "$svc"; then
        ok "白名单覆盖 $svc"
      else
        bad "白名单里没有 $svc（regex = $KEEP_REGEX）"
        note "→ relabelings 的 regex 是**完全匹配**，不是子串。"
      fi
    else
      note "无 keep 规则，跳过 $svc 的覆盖检查"
    fi
  done
else
  note "未提供 --expect-services，跳过覆盖检查"
fi

echo "[5] 稳定标签（service）"
if printf '%s' "$YAML" | grep -q 'targetLabel:[[:space:]]*service'; then
  ok "把服务名提升成 service 标签（面板按它聚合）"
else
  note "没有 targetLabel: service —— 面板将依赖 job 标签"
  note "→ Operator 自动打的 job 标签在不同版本下形态可能不一致，建议自己 relabel 一个。"
fi

echo "[6] Pod 名标签"
if printf '%s' "$YAML" | grep -A3 'action:[[:space:]]*drop' | grep -q '__meta_kubernetes_pod_name'; then
  ok "已 drop Pod 名标签（series 不会随发布膨胀）"
else
  note "未 drop Pod 名标签 —— 每次滚动发布 series 数会翻倍"
fi

echo
if [ "$PROBLEMS" -gt 0 ]; then
  echo "❌ 发现 $PROBLEMS 个问题"
  exit 1
fi
echo "✅ 采集层配置检查通过"
echo
echo "还没验的（需要集群）："
echo "  kubectl -n <monitoring-ns> exec <prom-pod> -- \\"
echo "    wget -qO- 'http://localhost:9090/api/v1/targets?state=active' | jq '.data.activeTargets[] | {scrapePool,health,lastError}'"
echo "  ↑ target up 只说明抓到了；还要确认响应体是真指标（用 verify-actuator-endpoint.sh）"
exit 0
