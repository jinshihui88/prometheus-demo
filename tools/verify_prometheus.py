# -*- coding: utf-8 -*-
"""Prometheus 侧端到端验证：targets 状态、业务指标入 TSDB、PromQL 查询。

前提：Prometheus 运行于 9090 且已配置 spring-boot 抓取任务（目标 localhost:8081），
prometheus-demo 应用运行中（业务 8080 / 管理 8081）。
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PROM = "http://localhost:9090"
BASE = "http://localhost:8080"

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


def api(path):
    with urllib.request.urlopen(PROM + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def query(q):
    return api("/api/v1/query?query=" + urllib.parse.quote(q))["data"]["result"]


def fire(n):
    """制造 n 次下单流量，保证指标有新样本。"""
    for _ in range(n):
        req = urllib.request.Request(BASE + "/api/demo/orders", method="POST")
        urllib.request.urlopen(req, timeout=30).read()


def main():
    # Prometheus 就绪
    try:
        build = api("/api/v1/status/buildinfo")["data"]
        check("Prometheus API 可达（%s）" % build.get("version"), True)
    except Exception as e:
        check("Prometheus API 可达", False, str(e))
        finish()

    # targets
    try:
        targets = api("/api/v1/targets")["data"]["activeTargets"]
    except Exception as e:
        check("targets API", False, str(e))
        finish()
    sb = [t for t in targets if t["labels"].get("job") == "spring-boot"]
    check("存在 spring-boot 抓取任务", bool(sb))
    if sb:
        check("spring-boot target 状态 UP", sb[0]["health"] == "up",
              "health=%s err=%s" % (sb[0]["health"], sb[0].get("lastError")))
        check("抓取地址为 http://localhost:8081/actuator/prometheus",
              sb[0]["scrapeUrl"] == "http://localhost:8081/actuator/prometheus", sb[0]["scrapeUrl"])

    # 指标入 TSDB
    up = query('up{job="spring-boot"}')
    check('up{job="spring-boot"} == 1', up and up[0]["value"][1] == "1", str(up))

    before = query("demo_orders_total")
    before_val = float(before[0]["value"][1]) if before else None
    fire(3)
    time.sleep(20)  # 等待至少一轮抓取
    after = query("demo_orders_total")
    after_val = float(after[0]["value"][1]) if after else None
    check("demo_orders_total 从 %s 增至 %s" % (before_val, after_val),
          after_val is not None and (before_val is None or after_val - before_val == 3.0),
          "before=%s after=%s" % (before_val, after_val))

    r = query("demo_tasks_active")
    check("Gauge 指标 demo_tasks_active 已入库", bool(r), str(r))

    r = query('jvm_memory_used_bytes{area="heap",job="spring-boot"}')
    check("JVM 堆内存序列已入库", bool(r), str(r))

    fire(5)
    time.sleep(35)  # 累积足够样本点供 rate 计算
    r = query("sum(rate(demo_orders_total[2m]))")
    check("rate(demo_orders_total[2m]) 有值", bool(r) and float(r[0]["value"][1]) > 0, str(r))

    r = query("sum(rate(http_server_requests_seconds_count{job=\"spring-boot\"}[2m]))")
    check("HTTP 请求速率可查询", bool(r) and float(r[0]["value"][1]) > 0, str(r))

    r = query("histogram_quantile(0.95, sum by (le) (rate(demo_orders_create_duration_seconds_bucket[2m])))")
    check("业务 Timer P95 分位数可估算", bool(r), str(r))

    finish()


def finish():
    print()
    print("TOTAL=%d PASS=%d FAIL=%d" % (PASS + FAIL, PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
