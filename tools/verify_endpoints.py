# -*- coding: utf-8 -*-
"""prometheus-demo 端到端验证脚本：业务接口 + 管理端点 + 指标内容逐项断言。"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8080"
MGMT = "http://localhost:8081"

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS  %s" % name)
    else:
        FAIL += 1
        print("FAIL  %s  -> %s" % (name, detail))


def request(method, url, body=None, accept="application/json"):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": accept}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def prometheus_text():
    s, b = request("GET", MGMT + "/actuator/prometheus", accept="text/plain")
    return s, b


def main():
    # ---------- 管理端点 ----------
    s, b = request("GET", MGMT + "/actuator/health")
    check("管理端口 8081 health 返回 200", s == 200, "status=%s" % s)

    s, b = request("GET", MGMT + "/actuator/info")
    check("info 端点返回应用信息", s == 200 and "prometheus-demo" in b, "status=%s body=%s" % (s, b[:120]))

    s, b = request("GET", MGMT + "/actuator/prometheus", accept="text/plain")
    check("prometheus 端点返回 200 文本", s == 200 and len(b) > 1000, "status=%s len=%s" % (s, len(b)))

    # 暴露边界：未暴露的端点应 404
    s, _ = request("GET", MGMT + "/actuator/env")
    check("env 端点未暴露返回 404", s == 404, "status=%s" % s)

    # ---------- 指标内容（触发业务前） ----------
    s, text = prometheus_text()
    check("包含 JVM 内存指标 jvm_memory_used_bytes", "jvm_memory_used_bytes" in text)
    check("包含进程指标 process_uptime_seconds", "process_uptime_seconds" in text)
    check("全局标签 application=prometheus-demo", 'application="prometheus-demo"' in text)

    # ---------- 业务接口与自定义指标 ----------
    order_before = metric_value(text, "demo_orders_total")

    s, b = request("POST", BASE + "/api/demo/orders")
    check("创建订单接口 200", s == 200 and "订单创建成功" in b, "status=%s body=%s" % (s, b[:150]))
    s, b = request("POST", BASE + "/api/demo/orders")
    check("再次创建订单，订单号递增", s == 200 and "ORD-" in b, "body=%s" % b[:150])

    s, b = request("POST", BASE + "/api/demo/tasks/start")
    check("开始任务接口 200", s == 200 and '"activeTasks":1' in b, "body=%s" % b[:100])
    s, b = request("POST", BASE + "/api/demo/tasks/start")
    check("再开始一个任务 activeTasks=2", s == 200 and '"activeTasks":2' in b, "body=%s" % b[:100])

    s, text = prometheus_text()
    # 指标命名实证：Micrometer 点号名 -> Prometheus 规范名
    for expect in ("demo_orders_total", "demo_orders_create_duration_seconds_bucket",
                   "demo_orders_create_duration_seconds_sum", "demo_tasks_active"):
        check("prometheus 输出包含 %s" % expect, expect in text)
    check("Gauge demo_tasks_active 值为 2", metric_value(text, "demo_tasks_active") == 2.0,
          "value=%s" % metric_value(text, "demo_tasks_active"))

    # HTTP 请求直方图（业务口的请求会产生 http_server_requests 样本）
    check("http_server_requests_seconds_bucket 已启用", "http_server_requests_seconds_bucket" in text)
    check("SLO 桶 0.1 出现", 'le="0.1"' in text)

    # Counter 增量
    order_after = metric_value(text, "demo_orders_total")
    check("订单计数从 %s 增至 %s" % (order_before, order_after),
          order_after is not None and (order_before is None or order_after - order_before == 2.0),
          "before=%s after=%s" % (order_before, order_after))

    # ---------- 任务结束与下限 ----------
    s, b = request("POST", BASE + "/api/demo/tasks/finish")
    check("结束任务 activeTasks=1", s == 200 and '"activeTasks":1' in b, "body=%s" % b[:100])
    s, b = request("POST", BASE + "/api/demo/tasks/finish")
    s, b = request("POST", BASE + "/api/demo/tasks/finish")
    check("连续 finish 不出现负数", s == 200 and '"activeTasks":0' in b, "body=%s" % b[:100])

    # ---------- metrics 端点 ----------
    s, b = request("GET", MGMT + "/actuator/metrics")
    names = json.loads(b).get("names", []) if s == 200 else []
    check("metrics 端点列出 demo 指标", "demo.orders.created" in names and "demo.tasks.active" in names,
          "status=%s" % s)

    s, b = request("GET", MGMT + "/actuator/metrics/demo.tasks.active")
    check("单指标查询 demo.tasks.active", s == 200 and "measurements" in b, "status=%s" % s)

    # ---------- 业务口不暴露管理端点（端口隔离） ----------
    s, _ = request("GET", BASE + "/actuator/health")
    check("业务口 8080 不暴露 actuator（404）", s == 404, "status=%s" % s)

    print()
    print("TOTAL=%d PASS=%d FAIL=%d" % (PASS + FAIL, PASS, FAIL))
    sys.exit(1 if FAIL else 0)


def metric_value(text, name):
    """从 Prometheus 文本中取指定指标（不带 # 前缀样本行）的最后一个值。"""
    for line in text.splitlines():
        if line.startswith(name + "{") or line.startswith(name + " "):
            try:
                return float(line.rsplit(" ", 1)[1])
            except (ValueError, IndexError):
                continue
    return None


if __name__ == "__main__":
    main()
