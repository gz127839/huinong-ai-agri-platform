# -*- coding: utf-8 -*-
"""模拟云端启动：注入 PORT，确认服务能在该端口起来并响应。"""
import os
import subprocess
import sys
import time
import urllib.request

DST = r"D:\_deploy_agri"
PY = r"C:\Users\异乡人\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
PORT = "5099"

env = dict(os.environ)
env["PORT"] = PORT
env.pop("FLASK_DEBUG", None)

p = subprocess.Popen([PY, "app.py"], cwd=DST, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
ok = False
try:
    for _ in range(60):
        time.sleep(0.5)
        if p.poll() is not None:
            break
        try:
            with urllib.request.urlopen("http://127.0.0.1:%s/login" % PORT, timeout=2) as r:
                body = r.read()
                print("HTTP", r.status, "登录页字节", len(body))
                ok = r.status == 200 and "登录".encode() in body
                break
        except Exception:
            continue
finally:
    p.terminate()
    try:
        p.wait(timeout=10)
    except Exception:
        p.kill()
    out = p.stdout.read().decode("utf-8", "replace")
    print("--- 进程输出 ---")
    print(out[:1200])

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("启动自检:", "PASS" if ok else "FAIL")
