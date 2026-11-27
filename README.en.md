# spring-boot-metrics-lighthouse

🗼 **A lighthouse for Spring Boot metrics** — wire Spring Boot microservice metrics into
Prometheus and build Grafana dashboards you can actually make decisions from.

Not a "Prometheus tutorial". This is a **distillation of a real onboarding run**:
every metric expression was validated, and every pitfall is recorded as
**symptom → cause → fix**.

```
scrape:  /actuator/prometheus  ←  micrometer-registry-prometheus  ←  ServiceMonitor
display: 12-panel dashboard      ←  per-query verified PromQL
```

## Why a skill repo instead of a knowledge base

| | Knowledge base | This repo |
|---|---|---|
| Form | long prose | runnable scripts + decision tables |
| Retrieval | AI greps keywords, misses context | step-by-step, each step has a pass condition |
| Verification | unclear which sentence is reliable | every claim tagged **measured / inferred** |
| Failure samples | usually omitted | **deliberately recorded** (how the wrong call was made) |
| Updates | relies on someone remembering | `CHANGELOG` + CI + semantic versioning |
| Confidentiality | easy to leak real details | `check_repo.py` hard scan + gitleaks |

## Quick start

```bash
git clone https://github.com/zejun-moon/spring-boot-metrics-lighthouse.git

# the main flow
cat spring-boot-metrics-lighthouse/skills/spring-boot-metrics-lighthouse/SKILL.md

# troubleshooting starts here
grep -n "symptom" spring-boot-metrics-lighthouse/skills/spring-boot-metrics-lighthouse/references/pitfalls.md
```

### For AI agents

Drop `skills/spring-boot-metrics-lighthouse/` into your skills directory, or install
it as a Claude Code plugin:

```bash
claude plugin install ./spring-boot-metrics-lighthouse
```

The SKILL.md frontmatter carries **bilingual trigger phrases**, so an agent should
pick this skill up when the conversation mentions microservice monitoring,
"ServiceMonitor target is 0", "actuator/prometheus returns 404",
"Grafana panel has no data", and similar.

### Run it yourself

```bash
# does the endpoint really expose metrics? (three-way verdict)
bash skills/spring-boot-metrics-lighthouse/scripts/verify-actuator-endpoint.sh \
     --url http://<svc>.<ns>.svc.cluster.local:8080/actuator/prometheus

# is the scrape config sane?
bash skills/spring-boot-metrics-lighthouse/scripts/check-servicemonitor.sh \
     --file ./my-servicemonitor.yaml --expect-services svc-a,svc-b

# generate the 12-panel dashboard
python3 skills/spring-boot-metrics-lighthouse/scripts/gen-dashboard.py \
     --datasource-uid <prom-uid> --namespace <ns> --services svc-a,svc-b \
     --output dashboard.json

# verify every query (a successful import does NOT mean the panels have data)
bash skills/spring-boot-metrics-lighthouse/scripts/verify-dashboard.sh \
     --dashboard dashboard.json --prometheus http://<prom>:9090
```

## Layout

```text
skills/spring-boot-metrics-lighthouse/
  SKILL.md                      # main flow: 4 steps + troubleshooting entry + boundaries
  references/
    pitfalls.md                 # 25 measured pitfalls — read this first
    actuator-and-config.md      # deps / management config / port semantics / metric names
    servicemonitor.md           # 3 scrape modes + relabelings recipes + 3-layer verification
    grafana-dashboard.md        # panel semantics + styling + legend columns + Table alternative
    grafana-api-troubleshooting.md
    istio-metrics.md            # service-mesh metric semantics (side note)
  scripts/
    verify-actuator-endpoint.sh
    check-servicemonitor.sh
    gen-dashboard.py
    verify-dashboard.sh
field-reports/                  # desensitized field reports (including failures)
tools/check_repo.py             # structure + version + desensitization self-check
tests/                          # scanner unit tests
```

## Coverage

✅ Spring Boot 2/3 · actuator + micrometer · ServiceMonitor / PodMonitor / annotation
scraping · kube-prometheus-stack · Grafana 10.x dashboard generation and verification

❌ OpenTelemetry Collector pipelines · custom Prometheus Operator setups ·
alerting rule design · non-Spring-Boot runtimes

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The core rule: **write the desensitized field
report first, then promote the conclusion into `references/pitfalls.md`**, and
`python3 tools/check_repo.py` must exit 0 before you push.

## License

[MIT](LICENSE)
