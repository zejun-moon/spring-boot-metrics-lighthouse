#!/usr/bin/env python3
"""check_repo.py 的单元测试。

重点验证**敏感信息扫描器真的有牙** —— 一个扫不出东西的扫描器比没有更危险。
所以这里用大量阳性样本（真 IP、真 token、真域名……）逐条断言必须命中，
再用阴性样本断言不得误报。

⚠️ **本文件里的敏感样本一律在运行时拼接**，源码里不出现完整字面量。
原因有两个：
  1. 否则扫描器会把自己的测试样本也扫出来（自指误报）
  2. 否则 gitleaks 会把假 token 当真密钥，CI 直接红
运行时拼接不影响测试有效性 —— 被测的是正则与规则，不是常量。

运行：
    python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))

import check_repo  # noqa: E402


def hits(line):
    return check_repo.scan_line("fixture.md", 1, line)


# ── 运行时拼接的敏感样本 ────────────────────────────────────────────
S = {
    "ip": "192.168." + "2.31",
    "ip2": "10.20." + "30.40",
    "bad_ip": "999.999." + "999.999",
    "host_test_com": "grafana." + "test.com",
    "host_test_local": "zhong" + "zj.config.petclinic.test." + "local",
    "host_harbor": "harbor." + "test." + "local",
    "host_mirror": "docker.m." + "daocloud." + "io",
    "ident": "zhong" + "zj",
    "ident_ns": "zz" + "j-spring-petclinic",
    "ident3": "sea" + "world008",
    "ident_cn": "钟" + "泽军",
    "aws": "AKIA" + "IOSFODNN7EXAMPLE",
    "ghp": "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz0123",
    "pk": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "bearer": "Bearer " + "eyJhbGciOiJIUzI1NiJ9abcdefgh",
    "uuid": "d461de83-2d17-4839-" + "9e95-be02dc6be42f",
    "email": "zhang.san@" + "corp-internal.cn",
    "pwd": "pass" + "word: \"Super" + "Secret123\"",
}


class TestSensitiveScanner(unittest.TestCase):
    """阳性样本：必须命中"""

    def test_real_ipv4_is_detected(self):
        self.assertTrue(hits("服务跑在 %s 上" % S["ip"]))
        self.assertTrue(hits("node02 = %s" % S["ip2"]))

    def test_invalid_ipv4_is_not_detected(self):
        # 版本号这类数字串不是 IP
        self.assertFalse(hits("版本号 %s" % S["bad_ip"]))

    def test_internal_hostname_is_detected(self):
        self.assertTrue(hits("入口 http://%s/d/petclinic" % S["host_test_com"]))
        self.assertTrue(hits("域名 %s" % S["host_test_local"]))
        self.assertTrue(hits("镜像 %s/xx/yy:1.0" % S["host_harbor"]))
        self.assertTrue(hits("走 %s 加速" % S["host_mirror"]))

    def test_identity_marker_is_detected(self):
        self.assertTrue(hits("仓库属于 %s" % S["ident"]))
        self.assertTrue(hits("命名空间 %s" % S["ident_ns"]))
        self.assertTrue(hits("参考 %s 的做法" % S["ident3"]))
        self.assertTrue(hits("维护者 %s" % S["ident_cn"]))

    def test_credentials_are_detected(self):
        self.assertTrue(hits(S["pwd"]))
        self.assertTrue(hits("api_key = '%s'" % S["aws"]))
        self.assertTrue(hits("token: %s" % S["ghp"]))
        self.assertTrue(hits(S["pk"]))
        self.assertTrue(hits("Authorization: %s" % S["bearer"]))

    def test_uuid_is_detected(self):
        self.assertTrue(hits("folder uid = %s" % S["uuid"]))

    def test_email_is_detected(self):
        self.assertTrue(hits("联系 %s" % S["email"]))


class TestScannerNegatives(unittest.TestCase):
    """阴性样本：不得误报"""

    def test_loopback_and_wildcards_are_allowed(self):
        self.assertFalse(hits("curl http://127.0.0.1:9090"))
        self.assertFalse(hits("listen 0.0.0.0:3000"))

    def test_placeholder_ip_is_allowed(self):
        self.assertFalse(hits("示例 IP：10.0.0.x"))

    def test_placeholder_email_is_allowed(self):
        self.assertFalse(hits("联系 user@example.com"))

    def test_public_docs_domain_is_allowed(self):
        self.assertFalse(hits("见 https://prometheus.io/docs/"))

    def test_generic_k8s_dns_is_allowed(self):
        # 通用 K8s DNS 形态不泄露真实信息
        self.assertFalse(hits("地址 http://svc.ns.svc.cluster.local:8080/x"))

    def test_allow_marker_whitelists_line(self):
        self.assertFalse(hits("%s  # check_repo: allow —— 示例，来自官方文档" % S["ip"]))

    def test_empty_line(self):
        self.assertFalse(hits(""))


class TestRepoIsClean(unittest.TestCase):
    """集成测试：本仓自己必须干净"""

    def test_repo_passes_self_check(self):
        rc = check_repo.main()
        self.assertEqual(
            rc, 0,
            "仓库自检未通过（%d 个问题）——发布前必须先脱敏" % rc)


if __name__ == "__main__":
    unittest.main()
