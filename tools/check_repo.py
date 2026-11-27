#!/usr/bin/env python3
"""check_repo.py —— 仓库自检（提交前本地跑，CI 也会跑）。

检查四类问题：

  1. 技能结构：SKILL.md 的 YAML frontmatter（name == 目录名、description 存在且 <= 1024 字符）、
     正文 < 500 行；SKILL.md 里提到的每个 scripts/ references/ assets/ 路径都真实存在；
     shell 脚本有 shebang 且带可执行位。
  2. 版本一致：.claude-plugin/plugin.json == marketplace.json（metadata.version 与 plugins[0].version）
     == CHANGELOG.md 里最新的发布版本号。
  3. 实战报告：field-reports/ 每份报告的 frontmatter 键齐全，且都被 field-reports/README.md 索引。
  4. 敏感信息：真实 IP、内网域名、私有镜像地址、内部 uid、账号 / 口令 / 私钥 / token / 邮箱。

敏感信息扫描的豁免：在某一行写 `check_repo: allow` 即可豁免该行（要写清楚理由）。

退出码 = 问题数（0 = 干净）。Python 3.6+，只用标准库。

用法：
    python3 tools/check_repo.py
    python3 -m unittest discover -s tests      # 单元测试
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

problems = []
checks_run = 0


def bad(msg):
    problems.append(msg)
    print("  x " + msg)


def ok(msg):
    global checks_run
    checks_run += 1
    print("  o " + msg)


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


# ---------------------------------------------------------------- 扫描规则
# 一律用行内豁免标记 `check_repo: allow` 放行
ALLOW_MARKER = "check_repo: allow"

# 允许出现的 IP（协议常量，不是真实主机）
IP_ALLOW = {
    "0.0.0.0",
    "127.0.0.1",
    "255.255.255.255",
    "::1",
}

# 内网/真实主机名特征（本仓只允许 example.com 这类保留域）
# 注意：不拦 `*.svc.cluster.local` —— 那是 K8s 通用 DNS 形态，
# 文档里写 `<svc>.<ns>.svc.cluster.local` 不泄露任何真实信息；
# 真正的内部标识（ns 前缀、人名）由下面的 IDENTITY_PATTERNS 负责。
HOST_PATTERNS = [
    (re.compile(r"\b[\w.-]+\.test\.local\b"), "内网测试域名（*.test.local）"),
    (re.compile(r"\b[\w.-]+\.test\.com\b"), "内网测试域名（*.test.com）"),
    (re.compile(r"\b[\w.-]+\.internal\b"), "内部域名（*.internal）"),
    (re.compile(r"\bdocker\.m\.daocloud\.io\b"), "内部镜像加速源"),
    (re.compile(r"\bharbor\.[\w.-]+\b"), "私有镜像仓库地址"),
    (re.compile(r"\bgitlab\.[\w.-]+\b"), "私有 GitLab 地址"),
]

# 个人 / 组织标识（本仓是公开仓，不能带任何个人痕迹）
# 注意：仓库自己的公开账号（owner/repo 路径）不算泄露，不在此列。
IDENTITY_PATTERNS = [
    (re.compile(r"\bzhongzj\b", re.I), "个人标识 zhongzj"),  # check_repo: allow —— 这是规则本身
    (re.compile(r"\bzzj-[a-z]", re.I), "内部命名空间前缀 zzj-"),  # check_repo: allow —— 这是规则本身
    (re.compile(r"\bseaworld008\b", re.I), "第三方账号标识"),  # check_repo: allow —— 这是规则本身
    (re.compile(r"钟泽军"), "真实姓名"),  # check_repo: allow —— 这是规则本身
]

# 凭据特征
CREDENTIAL_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥文件内容"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS AccessKey"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), "GitHub token (ghp_)"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub token (github_pat_)"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}"), "GitHub token (gho_)"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"), "GitLab token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)"
                r"\s*[:=]\s*[\"'][^\"'\s$<>{}]{6,}[\"']"), "疑似明文口令/密钥赋值"),
    (re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer token"),
]

# 内部资源 uid（本仓不使用 uuid，仪表盘/文件夹 uid 一律参数化）
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b(?![0-9])")


def _is_real_ipv4(text):
    """八位组全部 <= 255 才算合法 IPv4（否则只是数字串，如版本号 999.999.999.999）。"""
    for part in text.split("."):
        if len(part) > 1 and part[0] == "0":
            return False
        if int(part) > 255:
            return False
    return True

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# 文档里允许的示例邮箱（占位）
EMAIL_ALLOW = {
    "user@example.com",
    "you@example.com",
    "admin@example.com",
    "noreply@example.com",
}


def scan_line(path, lineno, line):
    """返回该行命中的问题列表（供单元测试直接调用）。"""
    hits = []
    if ALLOW_MARKER in line:
        return hits

    for m in IPV4_RE.finditer(line):
        ip = m.group(0)
        if ip in IP_ALLOW:
            continue
        # 形如 10.0.0.x / 192.168.2.x 的占位写法不算真实 IP
        if re.search(r"\.x\b", line[max(0, m.start() - 4):m.end() + 2]):
            continue
        if not _is_real_ipv4(ip):
            continue
        hits.append("真实 IPv4 地址: %s" % ip)

    for rx, why in HOST_PATTERNS:
        for m in rx.finditer(line):
            hits.append("%s: %s" % (why, m.group(0)))

    for rx, why in IDENTITY_PATTERNS:
        for m in rx.finditer(line):
            hits.append("%s: %s" % (why, m.group(0)))

    for rx, why in CREDENTIAL_PATTERNS:
        if rx.search(line):
            hits.append(why)

    for m in UUID_RE.finditer(line):
        hits.append("内部资源 uid（uuid）: %s" % m.group(0))

    for m in EMAIL_RE.finditer(line):
        if m.group(0).lower() in EMAIL_ALLOW:
            continue
        hits.append("邮箱地址: %s" % m.group(0))

    return ["%s:%d  %s" % (path, lineno, h) for h in hits]


def tracked_files():
    """已跟踪 + 未忽略的新文件。"""
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT, stderr=subprocess.DEVNULL)
        files = [f for f in out.decode("utf-8", "replace").splitlines() if f]
        if files:
            return files
    except Exception:
        pass
    skip = {".git", "__pycache__", "node_modules", "_private"}
    res = []
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in skip]
        for f in files:
            res.append(rel(os.path.join(d, f)))
    return res


TEXT_EXT = {
    ".md", ".txt", ".yaml", ".yml", ".json", ".py", ".sh", ".bash", ".cfg",
    ".ini", ".toml", ".env", ".example", ".xml", ".html", ".js", ".ts", "",
}


def is_text_file(path):
    if os.path.splitext(path)[1].lower() in TEXT_EXT:
        return True
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            f.read(4096)
        return True
    except Exception:
        return False


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------- 检查各部分
def check_skill_structure():
    print("[1] 技能结构")
    skills_dir = os.path.join(ROOT, "skills")
    skill_names = []
    if not os.path.isdir(skills_dir):
        bad("skills/ 目录不存在")
        return
    for name in sorted(os.listdir(skills_dir)):
        sd = os.path.join(skills_dir, name)
        if not os.path.isdir(sd):
            continue
        skill_names.append(name)
        sk = rel(os.path.join(sd, "SKILL.md"))
        if not os.path.exists(os.path.join(ROOT, sk)):
            bad("%s 缺失" % sk)
            continue
        text = read(sk)
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        if not m:
            bad("%s: 缺少 YAML frontmatter" % sk)
            continue
        fm, body = m.group(1), m.group(2)

        fname = re.search(r"^name:\s*(.+)$", fm, re.M)
        desc = re.search(r"^description:\s*(.+)$", fm, re.M)
        if not fname or fname.group(1).strip() != name:
            bad("%s: frontmatter name 必须等于目录名 '%s'" % (sk, name))
        else:
            ok("%s: frontmatter name == 目录名" % sk)

        if not desc or not desc.group(1).strip():
            bad("%s: frontmatter 缺 description" % sk)
        else:
            d = desc.group(1).strip()
            if len(d) > 1024:
                bad("%s: description 过长 (%d > 1024 字符)" % (sk, len(d)))
            else:
                ok("%s: description %d 字符 (<=1024)" % (sk, len(d)))
            has_cn = bool(re.search(r"[\u4e00-\u9fff]", d))
            has_en = bool(re.search(r"[A-Za-z]{3,}", d))
            if not (has_cn and has_en):
                bad("%s: description 建议同时含中文与英文触发词（当前 cn=%s en=%s）"
                    % (sk, has_cn, has_en))

        body_lines = len(body.split("\n"))
        if body_lines > 500:
            bad("%s: 正文 %d 行，超过 500 行（细节请拆到 references/）" % (sk, body_lines))
        else:
            ok("%s: 正文 %d 行 (<500)" % (sk, body_lines))

        # SKILL.md 里提到的相对路径必须存在
        refs = set()
        for pm in re.finditer(
                r"`((?:scripts|references|assets)/[A-Za-z0-9_.\-/]+)`", body):
            refs.add(pm.group(1))
        for pm in re.finditer(
                r"\]\((?:\./)?((?:skills/[^)]*?/)?(?:scripts|references|assets)/[^)]+)\)",
                body):
            refs.add(pm.group(1))
        missing_refs = []
        for r in sorted(refs):
            cands = [
                os.path.join(ROOT, r),
                os.path.join(ROOT, "skills", skill_names[0] if skill_names else "", r),
            ]
            if not any(os.path.exists(c) for c in cands):
                missing_refs.append(r)
        if missing_refs:
            for r in missing_refs:
                bad("%s: 引用了不存在的路径 %s" % (sk, r))
        elif refs:
            ok("%s: 引用的 %d 个 scripts/references 路径全部存在" % (sk, len(refs)))

        # shell 脚本：shebang + 可执行位
        for root, dirs, files in os.walk(sd):
            dirs[:] = [x for x in dirs if x not in {".git", "__pycache__"}]
            for f in sorted(files):
                if not f.endswith((".sh", ".bash")):
                    continue
                sp = os.path.join(root, f)
                srel = rel(sp)
                with open(sp, encoding="utf-8", errors="replace") as fh:
                    first = fh.readline()
                if not first.startswith("#!"):
                    bad("%s: 缺少 shebang" % srel)
                elif not os.access(sp, os.X_OK):
                    bad("%s: 缺少可执行位（chmod +x）" % srel)
                else:
                    ok("%s: shebang + 可执行位正常" % srel)


def check_versions():
    print("[2] 版本一致")
    plugin_json = os.path.join(ROOT, ".claude-plugin", "plugin.json")
    market_json = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
    changelog = os.path.join(ROOT, "CHANGELOG.md")

    versions = {}
    if os.path.exists(plugin_json):
        try:
            versions["plugin.json"] = json.load(
                open(plugin_json, encoding="utf-8")).get("version")
        except Exception as e:
            bad("plugin.json 解析失败: %s" % e)
    else:
        bad(".claude-plugin/plugin.json 缺失")

    if os.path.exists(market_json):
        try:
            mk = json.load(open(market_json, encoding="utf-8"))
            versions["marketplace.json:metadata"] = (mk.get("metadata") or {}).get("version")
            plugs = mk.get("plugins") or []
            versions["marketplace.json:plugins[0]"] = plugs[0].get("version") if plugs else None
        except Exception as e:
            bad("marketplace.json 解析失败: %s" % e)
    else:
        bad(".claude-plugin/marketplace.json 缺失")

    if os.path.exists(changelog):
        m = re.search(r"^##\s*\[?v?(\d+\.\d+\.\d+)\]?", read(changelog), re.M)
        if m:
            versions["CHANGELOG.md"] = m.group(1)
        else:
            bad("CHANGELOG.md 里找不到版本号标题")
    else:
        bad("CHANGELOG.md 缺失")

    vals = [v for v in versions.values() if v]
    if vals and len(set(vals)) == 1:
        ok("版本一致: %s" % vals[0])
    elif vals:
        bad("版本不一致: %s" % ", ".join(
            "%s=%s" % (k, v) for k, v in sorted(versions.items())))


def check_field_reports():
    print("[3] 实战报告索引")
    fr_dir = os.path.join(ROOT, "field-reports")
    if not os.path.isdir(fr_dir):
        bad("field-reports/ 目录缺失")
        return
    reports = sorted(f for f in os.listdir(fr_dir)
                     if f.endswith(".md") and f not in ("README.md", "TEMPLATE.md"))
    if not reports:
        bad("field-reports/ 下没有报告")
        return
    index_path = os.path.join(fr_dir, "README.md")
    index_text = read(index_path) if os.path.exists(index_path) else ""
    for r in reports:
        text = read(os.path.join(fr_dir, r))
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if not m:
            bad("field-reports/%s: 缺少 frontmatter" % r)
            continue
        fm = m.group(1)
        missing = [k for k in ("date", "environment", "result")
                   if not re.search(r"^%s:\s*\S" % k, fm, re.M)]
        if missing:
            bad("field-reports/%s: frontmatter 缺 %s" % (r, ", ".join(missing)))
        if r not in index_text:
            bad("field-reports/%s 没有被 field-reports/README.md 索引" % r)
        else:
            ok("field-reports/%s: frontmatter 齐全且已索引" % r)


def check_sensitive():
    print("[4] 敏感信息扫描")
    files = tracked_files()
    scanned = 0
    hits = 0
    for path in files:
        if not os.path.isfile(os.path.join(ROOT, path)):
            continue
        if not is_text_file(path):
            continue
        scanned += 1
        for lineno, line in enumerate(read(path).split("\n"), 1):
            for h in scan_line(path, lineno, line):
                bad(h)
                hits += 1
    if hits == 0:
        ok("扫描 %d 个文本文件，0 命中" % scanned)
    else:
        print("  （共 %d 个文件被扫描，%d 处命中）" % (scanned, hits))


def main():
    check_skill_structure()
    check_versions()
    check_field_reports()
    check_sensitive()

    print()
    print("=" * 50)
    if problems:
        print("发现 %d 个问题：" % len(problems))
        for p in problems:
            print("  - %s" % p)
        print()
        print("豁免方式：在该行加 `check_repo: allow` 并写清理由。")
        return len(problems)
    print("全部检查通过（%d 项检查）" % checks_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
