# -*- coding: utf-8 -*-
"""Add a Windows Firewall inbound rule for the web server port.

Must be run as Administrator. Uses netsh only, so it works with any
Python interpreter (no pywin32 needed).
"""
import ctypes
import os
import subprocess
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 5000))
RULE_NAME = "HuiNongAI-%d" % PORT


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run(args):
    return subprocess.run(
        ["netsh", "advfirewall", "firewall"] + args,
        capture_output=True, text=True, encoding="gbk", errors="ignore",
    )


def rule_exists():
    r = run(["show", "rule", "name=" + RULE_NAME])
    return r.returncode == 0 and RULE_NAME in (r.stdout or "")


def main():
    print("=" * 52)
    print("  慧农 AI 平台 —— 手机访问端口放行工具")
    print("=" * 52)
    print()

    if not is_admin():
        print("  当前不是管理员权限，无法修改防火墙。")
        print()
        print("  请先右键本文件所在目录的『手机访问放行.bat』，")
        print("  选择『以管理员身份运行』，再按提示操作。")
        print()
        return 1

    if rule_exists():
        print("  端口 %d 已经放行过，无需重复操作。" % PORT)
    else:
        run(["delete", "rule", "name=" + RULE_NAME])  # 清掉残留
        r = run(["add", "rule",
                 "name=" + RULE_NAME,
                 "dir=in",
                 "action=allow",
                 "protocol=TCP",
                 "localport=%d" % PORT])
        if r.returncode != 0:
            print("  添加失败：")
            print(" ", (r.stdout or "").strip()[:300] or (r.stderr or "").strip()[:300])
            return 1
        print("  已放行端口 %d（TCP 入站）" % PORT)

    print()
    print("  现在手机与电脑连同一个 WiFi，在手机浏览器输入：")
    print()
    print("     http://<电脑内网IP>:%d" % PORT)
    print()
    print("  内网 IP 可以在电脑上启动服务后从窗口里看到。")
    print()
    print("=" * 52)
    return 0


if __name__ == "__main__":
    sys.exit(main())
