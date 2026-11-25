package com.example.prometheusdemo;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 端到端集成测试：业务端口与管理端口分离场景下的指标端点验证。
 *
 * <p>说明：Spring Boot Test 默认关闭可观测性（不创建 PrometheusMeterRegistry），
 * 必须加 {@link AutoConfigureObservability} 才能在测试环境注册 /actuator/prometheus 端点。</p>
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "management.server.port=0"
})
@AutoConfigureObservability
class PrometheusDemoApplicationTests {

    @Autowired
    private TestRestTemplate rest;

    @LocalServerPort
    private int businessPort;

    @LocalManagementPort
    private int managementPort;

    @Test
    void managementHealthShouldBeUp() {
        ResponseEntity<String> resp = rest.getForEntity(managementUrl("/actuator/health"), String.class);
        assertEquals(HttpStatus.OK, resp.getStatusCode());
        assertTrue(resp.getBody().contains("\"status\""));
    }

    @Test
    void prometheusEndpointShouldExposeJvmMetrics() {
        String body = getPrometheusText();
        assertTrue(body.contains("jvm_memory_used_bytes"), "应包含 JVM 内存指标");
        assertTrue(body.contains("process_uptime_seconds"), "应包含进程存活时间指标");
    }

    @Test
    void businessMetricsShouldAppearAfterTriggering() {
        rest.postForEntity(businessUrl("/api/demo/orders"), null, String.class);
        rest.postForEntity(businessUrl("/api/demo/tasks/start"), null, String.class);

        String body = getPrometheusText();
        // 订单 Counter：Micrometer 点号命名会被 Prometheus Registry 规范化（以实际输出为准）
        assertTrue(body.contains("demo_orders_"), "应包含订单指标（前缀 demo_orders_）");
        // 订单 Timer：含 _seconds_count / _seconds_sum / _seconds_bucket 序列
        assertTrue(body.contains("demo_orders_create_duration_seconds_bucket"), "应包含订单耗时直方图桶");
        // 活跃任务 Gauge
        assertTrue(body.contains("demo_tasks_active"), "应包含活跃任务 Gauge");
        // 全局公共标签 application 已注入
        assertTrue(body.contains("application=\"prometheus-demo\""), "指标应带 application 标签");
    }

    @Test
    void httpServerRequestHistogramShouldBeEnabled() {
        rest.getForEntity(businessUrl("/api/demo/tasks"), String.class);
        String body = getPrometheusText();
        assertTrue(body.contains("http_server_requests_seconds_bucket"), "HTTP 请求直方图应已启用");
    }

    @Test
    void metricsEndpointShouldListMetricNames() {
        HttpHeaders headers = new HttpHeaders();
        headers.setAccept(java.util.List.of(MediaType.APPLICATION_JSON));
        ResponseEntity<String> resp = rest.exchange(managementUrl("/actuator/metrics"),
                HttpMethod.GET, new HttpEntity<>(headers), String.class);
        assertEquals(HttpStatus.OK, resp.getStatusCode());
        assertTrue(resp.getBody().contains("jvm.memory.used"));
    }

    @Test
    void taskFinishShouldNotGoNegative() {
        rest.postForEntity(businessUrl("/api/demo/tasks/finish"), null, String.class);
        rest.postForEntity(businessUrl("/api/demo/tasks/finish"), null, String.class);
        ResponseEntity<String> resp = rest.getForEntity(businessUrl("/api/demo/tasks"), String.class);
        assertEquals(HttpStatus.OK, resp.getStatusCode());
        assertTrue(resp.getBody().contains("\"activeTasks\":0"), "连续 finish 后活跃任务数应保持 0 下限");
    }

    private String getPrometheusText() {
        HttpHeaders headers = new HttpHeaders();
        // Prometheus 端点产出 text/plain，用纯 JSON Accept 会得到 406
        headers.setAccept(java.util.List.of(MediaType.TEXT_PLAIN));
        ResponseEntity<String> resp = rest.exchange(managementUrl("/actuator/prometheus"),
                HttpMethod.GET, new HttpEntity<>(headers), String.class);
        assertEquals(HttpStatus.OK, resp.getStatusCode());
        return resp.getBody();
    }

    private String managementUrl(String path) {
        return "http://localhost:" + managementPort + path;
    }

    private String businessUrl(String path) {
        return "http://localhost:" + businessPort + path;
    }
}
