package com.example.prometheusdemo.controller;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 业务演示接口：配套三类自定义指标。
 *
 * <ul>
 *   <li>Counter（demo.orders.created）——订单创建累计次数，只增不减；</li>
 *   <li>Timer（demo.orders.create.duration）——订单创建业务耗时，含直方图桶，可用于分位数估算；</li>
 *   <li>Gauge（demo.tasks.active）——当前活跃任务数，反映瞬时值。</li>
 * </ul>
 *
 * 被观测对象（AtomicInteger / AtomicLong）作为字段持有强引用，避免被垃圾回收后 Gauge 失去数据来源。
 */
@RestController
@RequestMapping("/api/demo")
public class DemoController {

    private static final DateTimeFormatter TIME_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final Counter orderCreatedCounter;
    private final Timer orderCreateTimer;
    private final AtomicInteger activeTasks = new AtomicInteger(0);
    private final AtomicLong orderSequence = new AtomicLong(0);

    public DemoController(MeterRegistry registry) {
        this.orderCreatedCounter = Counter.builder("demo.orders.created")
                .description("订单创建累计次数")
                .tag("channel", "web")
                .register(registry);

        this.orderCreateTimer = Timer.builder("demo.orders.create.duration")
                .description("订单创建业务耗时")
                .publishPercentileHistogram()
                .register(registry);

        Gauge.builder("demo.tasks.active", activeTasks, AtomicInteger::get)
                .description("当前活跃任务数量")
                .register(registry);
    }

    /**
     * 创建订单：Timer 记录整段业务耗时，Counter 在成功后递增。
     */
    @PostMapping("/orders")
    public Map<String, Object> createOrder() {
        return orderCreateTimer.record(() -> {
            orderCreatedCounter.increment();
            String orderNo = "ORD-" + LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                    + "-" + String.format("%04d", orderSequence.incrementAndGet() % 10000);
            // 模拟下单业务处理耗时（30~120ms），让 Timer 的耗时分布有真实样本
            simulateBusinessCost();
            return Map.of(
                    "orderNo", orderNo,
                    "channel", "web",
                    "message", "订单创建成功",
                    "createdAt", LocalDateTime.now().format(TIME_FORMAT)
            );
        });
    }

    /**
     * 开始任务：活跃任务数 +1，Gauge 随之上升。
     */
    @PostMapping("/tasks/start")
    public Map<String, Integer> startTask() {
        return Map.of("activeTasks", activeTasks.incrementAndGet());
    }

    /**
     * 结束任务：活跃任务数 -1，下限为 0，避免连续 finish 造成负数。
     */
    @PostMapping("/tasks/finish")
    public Map<String, Integer> finishTask() {
        activeTasks.updateAndGet(current -> Math.max(0, current - 1));
        return Map.of("activeTasks", activeTasks.get());
    }

    /**
     * 查询当前活跃任务数，便于验证 Gauge 数值。
     */
    @GetMapping("/tasks")
    public Map<String, Integer> currentTasks() {
        return Map.of("activeTasks", activeTasks.get());
    }

    private void simulateBusinessCost() {
        try {
            long millis = 30 + (long) (Math.random() * 90);
            TimeUnit.MILLISECONDS.sleep(millis);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }
}
