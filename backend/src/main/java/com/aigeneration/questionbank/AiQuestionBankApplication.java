package com.aigeneration.questionbank;

import com.aigeneration.questionbank.config.EnterpriseProperties;
import com.aigeneration.questionbank.config.CorsProperties;
import com.aigeneration.questionbank.config.JavaStorageProperties;
import com.aigeneration.questionbank.config.PlatformSecurityProperties;
import com.aigeneration.questionbank.config.PythonWorkerProperties;
import com.aigeneration.questionbank.config.SmartRagStackProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.mybatis.spring.annotation.MapperScan;

/**
 * AI 题库 Java 主后端启动入口。
 *
 * <p>该类负责启动 Spring Boot 应用、扫描 MyBatis Mapper，并启用 Python worker、
 * SmartRAG 技术栈、企业化依赖和 Java 文件存储等配置属性绑定。</p>
 */
@SpringBootApplication
@MapperScan("com.aigeneration.questionbank.domain.mapper")
@EnableConfigurationProperties({
        PythonWorkerProperties.class,
        SmartRagStackProperties.class,
        EnterpriseProperties.class,
        JavaStorageProperties.class,
        PlatformSecurityProperties.class,
        CorsProperties.class
})
public class AiQuestionBankApplication {

    /**
     * 启动 Java 主后端进程。
     *
     * @param args Spring Boot 命令行参数，允许通过命令行覆盖 profile、端口和配置项
     */
    public static void main(String[] args) {
        SpringApplication.run(AiQuestionBankApplication.class, args);
    }
}
