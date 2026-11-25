# prometheus-demo —— Spring Boot 3 整合 Prometheus 监控实战

以一个 Spring Boot Web 项目为例，把应用运行指标（JVM、HTTP、自定义业务指标）暴露给 Prometheus 采集，并在 Grafana 中查询与展示。业务流量走 8080，管理端点独立在 8081，Prometheus 只抓取管理端口。

## 1、项目简介

- Spring Boot 单体应用的监控接入完整闭环：Actuator 指标暴露 → Prometheus 定时抓取 → PromQL 查询 → Grafana 可视化；
- 三类自定义业务指标（Counter / Timer / Gauge）配套订单与任务演示接口，指标有真实样本；
- 业务端口与管理端口分离，生产环境可对 8081 做网络隔离。

## 2、技术栈与版本

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| JDK | 17 | LTS 版本 |
| Spring Boot | 3.5.16 | Web + Actuator，版本由 parent 统一管理 |
| Micrometer | 1.15.x（Boot BOM 托管） | 指标门面，业务代码只面向 MeterRegistry |
| micrometer-registry-prometheus | Boot BOM 托管 | 把指标转换为 Prometheus 文本格式并注册端点 |
| Prometheus | 3.16.0 | 本机已运行的实例，抓取周期 15s |
| Grafana | 13.3.1 | 本机已运行的实例，连接 Prometheus 展示 |

## 3、环境要求

- JDK 17、Maven 3.9+；
- Prometheus 与 Grafana 已在本机运行（9090 / 3000），无需重新安装；
- 8080（业务）、8081（管理）端口空闲。

## 4、快速开始

```bash
# 构建（含 6 个集成测试）
mvn -B clean package

# 启动
java -jar target/prometheus-demo-1.0.0.jar
```

启动后自检：

| 检查项 | 地址 | 预期 |
| --- | --- | --- |
| 健康检查 | http://localhost:8081/actuator/health | 200，status 正常 |
| 指标文本 | http://localhost:8081/actuator/prometheus | 200，含 jvm/process/demo 指标 |
| 应用信息 | http://localhost:8081/actuator/info | 200，含 app name/version |
| 下单接口 | POST http://localhost:8080/api/demo/orders | 200，返回订单号 |

Prometheus 接入后的验证：

```bash
# targets 应显示 spring-boot -> http://localhost:8081/actuator/prometheus 为 UP
python tools/verify_endpoints.py     # 应用侧 24 项断言
python tools/verify_prometheus.py    # Prometheus 侧 11 项断言
```

## 5、工程结构

```
prometheus-demo
├─ pom.xml
├─ src
│  ├─ main
│  │  ├─ java/com/example/prometheusdemo
│  │  │  ├─ PrometheusDemoApplication.java
│  │  │  └─ controller/DemoController.java
│  │  └─ resources/application.yml
│  └─ test/java/com/example/prometheusdemo
│     └─ PrometheusDemoApplicationTests.java
├─ docs/SpringBoot3整合Prometheus监控实战教程.md
└─ tools
   ├─ verify_endpoints.py
   └─ verify_prometheus.py
```

## 6、关键配置说明（application.yml）

- `management.server.port: 8081`：管理端点独立端口，业务口 8080 不暴露任何 actuator 端点（实测 404）；
- `management.endpoints.web.exposure.include: health,info,prometheus,metrics`：只暴露需要的四个端点，env 返回 404；
- `management.metrics.tags.application`：所有指标注入公共标签，多应用环境按 application 筛选；
- `management.metrics.distribution.percentiles-histogram.http.server.requests: true` + `slo: 100ms,300ms,1s`：HTTP 请求直方图桶，支持 P95 估算与 SLO 档位观察；
- `management.info.env.enabled: true`：**Boot 3.5 起 env 型 info 贡献者默认关闭**，不开启则 `/actuator/info` 恒为 `{}`（本机实测踩坑）。

## 7、接口清单

| 方法 | 路径 | 说明 | 对应指标 |
| --- | --- | --- | --- |
| POST | /api/demo/orders | 创建订单（含 30~120ms 模拟耗时） | Counter demo.orders.created、Timer demo.orders.create.duration |
| POST | /api/demo/tasks/start | 活跃任务 +1 | Gauge demo.tasks.active |
| POST | /api/demo/tasks/finish | 活跃任务 -1（下限 0） | Gauge demo.tasks.active |
| GET | /api/demo/tasks | 查询当前活跃任务数 | — |

## 8、自定义指标与命名转换（实测）

| Micrometer 注册名 | Prometheus 实际输出 | 类型 |
| --- | --- | --- |
| demo.orders.created | **demo_orders_total** | Counter |
| demo.orders.create.duration | demo_orders_create_duration_seconds_count / _sum / _bucket / _max | Timer（直方图） |
| demo.tasks.active | demo_tasks_active | Gauge |

注意：Counter `demo.orders.created` 的 `.created` 段在 Prometheus 命名规范化中会被收敛，最终输出 `demo_orders_total` 而非直觉上的 `demo_orders_created_total`。写 PromQL 前先到 `/actuator/prometheus` 里确认实际序列名，不要按注册名拼。

## 9、Prometheus 接入（复用本机已有实例）

在已运行的 Prometheus 配置（`prometheus.yml`）中追加抓取任务（修改前先备份）：

```yaml
scrape_configs:
  - job_name: "spring-boot"
    metrics_path: "/actuator/prometheus"
    scrape_interval: 15s
    static_configs:
      - targets: ["localhost:8081"]
        labels:
          application: "prometheus-demo"
          env: "dev"
```

配置生效方式（本机实例未启用 `--web.enable-lifecycle`，`/-/reload` 返回 403，只能重启进程）：备份配置 → `promtool check config` 校验 → 重启 prometheus.exe。本机实录：重启后 spring-boot target 约 15s 内 UP，历史 TSDB 数据保留。

## 10、Grafana 接入（UI 操作）

1. 打开 http://localhost:3000 并登录；
2. Connections → Data sources → Add data source → Prometheus；
3. URL 填 `http://localhost:9090`（Grafana 与 Prometheus 都在 Windows 本机运行时用 localhost；两者都在 Docker 时用服务名）；
4. Save & test 通过后即可建面板，推荐查询见教程第 9 章。

## 11、踩坑备忘与生产化建议

踩坑（均实测复现并修复）：

1. `demo.orders.created` → `demo_orders_total`：Counter 注册名与输出序列名不按直觉对应，断言/面板先看实际输出；
2. Boot 3.5 的 `/actuator/info` 默认不展示 `info.*` 配置，需 `management.info.env.enabled: true`；
3. Prometheus 端点必须带 `Accept: text/plain` 请求（纯 JSON Accept 得 406）；
4. 集成测试里 `/actuator/prometheus` 404：Spring Boot Test 默认关闭可观测性，测试类需加 `@AutoConfigureObservability`（包名是 `...test.autoconfigure.actuate.observability`，注意是 actuate 不是 actuator）；
5. 本机 Prometheus 未启用 lifecycle API 时配置改动只能重启进程生效。

生产化建议：

- 管理端口 8081 只对监控网络开放（防火墙/安全组/NetworkPolicy），不要映射公网；
- 端点暴露保持最小集合，禁止 `include: "*"`；引入 Spring Security 时为抓取方配置专用只读身份，不要关闭安全机制整体；
- 标签禁止使用 userId / orderId / 完整 URL / requestId 等高基数值，防止时间序列爆炸；
- Grafana 生产固定镜像版本、强密码；告警通知需另接 Alertmanager 或 Grafana Alerting；
- 数据保留 15d（本机现状）按规模规划，必要时上远程存储。

## 12、验证情况汇总

| 项目 | 结果 |
| --- | --- |
| mvn clean package | BUILD SUCCESS，6 个集成测试全绿 |
| tools/verify_endpoints.py | TOTAL=24 PASS=24 FAIL=0 |
| tools/verify_prometheus.py | TOTAL=11 PASS=11 FAIL=0 |
| 应用启动 | 1.9s，双端口 8080/8081，日志零 ERROR/WARN |
| Prometheus 抓取 | spring-boot target UP，demo_orders_total 持续增长，rate/P95 查询返回数据 |
| 原始配置备份 | prometheus.yml.bak-20261124（与 prometheus.yml 同目录） |
