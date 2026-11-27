# CLAUDE.md

本仓库是 **Claude Code 插件**形态的技能包。

- 技能入口：`skills/spring-boot-metrics-lighthouse/SKILL.md`
- 插件清单：`.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`
- 维护规则见根目录 [`AGENTS.md`](AGENTS.md)（**开始工作前先读它**）

## 本地开发

```bash
# 结构 / 版本 / 脱敏自检（提交前必跑）
python3 tools/check_repo.py

# 单元测试
python3 -m unittest discover -s tests

# 插件清单校验
claude plugin validate .
```

## 装成本地插件试用

```bash
claude plugin install ./spring-boot-metrics-lighthouse
```

## 发布

改版本号要同步三处（`plugin.json` 的 `version`、`marketplace.json` 的
`metadata.version` 与 `plugins[0].version`）以及 `CHANGELOG.md`，
`tools/check_repo.py` 会校验一致性。
