# -*- coding: utf-8 -*-
"""慧农 AI 智慧农业助农服务平台 —— 启动器。

双击桌面快捷方式后由 run.bat 调用本脚本，负责：
    1. 自动挑选可用端口，避开已被占用的端口（避免启动失败）
    2. 以后台方式启动 Flask 服务
    3. 等服务真正就绪后自动打开浏览器
    4. 关闭窗口即停止服务，不会留下后台残留
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE_DIR, "app.py")
START_PORT = int(os.environ.get("PORT", 5000))


def p(msg=""):
    """立即输出，避免与子进程输出混在一起时被缓冲住。"""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def pick_python():
    """挑一个已被 Windows 防火墙放行的解释器来运行 app.py。

    Windows 防火墙的入站规则是绑定程序路径的。本机放行的是 WorkBuddy 的
    基础解释器，而项目依赖装在 venv 里，若用 venv 的解释器启动，手机等
    外部设备会被防火墙拦在门外。所以这里优先用基础解释器（依赖已装到它
    名下），保证局域网设备能直接访问。
    """
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".workbuddy", "binaries", "python",
                     "versions", "3.13.12", "python.exe"),
        os.path.join(home, ".workbuddy", "binaries", "python",
                     "envs", "default", "Scripts", "python.exe"),
    ]
    for exe in candidates:
        if not os.path.exists(exe):
            continue
        try:
            r = subprocess.run([exe, "-c", "import flask, PIL, numpy"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
            if r.returncode == 0:
                return exe
        except Exception:
            continue
    return sys.executable


def lan_ip():
    """取本机连向外网的那个内网 IP（手机要访问的就是它）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


def detect_running(port):
    """端口上是否已经有本站实例在跑（用页面特征判断，避免误判别的程序）。"""
    try:
        r = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=2)
        body = r.read(8000).decode("utf-8", "ignore")
        return ("慧农" in body) or ("smart-agri" in body)
    except Exception:
        return False


def print_addr(port):
    """打印手机可以直接输入的完整网址。"""
    ip = lan_ip()
    if ip:
        p("  手机访问： http://%s:%d" % (ip, port))
        p("  （手机需与电脑连同一个 WiFi）")
    else:
        p("  手机访问： http://<电脑内网IP>:%d" % port)


def find_free_port(start, tries=20):
    """从 start 开始找第一个真正空闲的端口。

    两个 Windows 陷阱：
    1. 不能设 SO_REUSEADDR，否则能绑定到已被监听的端口，检测"假通过"；
    2. 必须绑 0.0.0.0 而不是 127.0.0.1。Windows 上即便已有服务监听
       0.0.0.0:port，绑定 127.0.0.1:port 仍会成功，检测同样会"假通过"，
       导致新实例真正启动时（Flask 绑 0.0.0.0）直接失败退出。
    """
    for p in range(start, start + tries):
        s = socket.socket()
        try:
            s.bind(("0.0.0.0", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    return start


def wait_ready(url, timeout=60):
    """轮询首页，直到服务真正可以响应。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.6)
    return False


def main():
    # 已经有本站实例在跑时，直接打开浏览器，不再起新进程
    if detect_running(START_PORT):
        url = "http://127.0.0.1:%d/" % START_PORT
        p("")
        p("  服务已在运行，直接打开浏览器")
        p("  --------------------------------------------------")
        print_addr(START_PORT)
        p("")
        webbrowser.open(url)
        return

    port = find_free_port(START_PORT)
    url = "http://127.0.0.1:%d/" % port

    p("")
    p("  慧农 AI · 智慧农业助农服务平台")
    p("  --------------------------------------------------")
    p("  正在启动服务，请稍候...")

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["FLASK_DEBUG"] = "0"          # 关闭调试重载器，避免重复派生进程
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen([pick_python(), APP], cwd=BASE_DIR, env=env)

    if port != START_PORT:
        p("  注意：%d 端口已被占用，已自动切换到 %d" % (START_PORT, port))

    if wait_ready(url):
        p("  服务已就绪：%s" % url)
        p("  演示账号：admin/admin123   farmer/farmer123   demo/demo123")
        p("  --------------------------------------------------")
        print_addr(port)
        p("  关闭本窗口或按 Ctrl+C 即可停止服务")
        p("")
        webbrowser.open(url)
    else:
        p("  服务启动超时，请查看上方报错信息。")
        p("")

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
