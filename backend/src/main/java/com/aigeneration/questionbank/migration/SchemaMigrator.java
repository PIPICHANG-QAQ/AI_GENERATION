package com.aigeneration.questionbank.migration;

import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.ResultSet;
import java.sql.SQLException;
import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 运行时 schema 补丁迁移器。
 *
 * <p>用于在启动时补齐当前版本新增的表和列，兼容本地 H2 与已有数据库。正式生产库仍建议
 * 使用 Flyway/Liquibase 等受控迁移工具。</p>
 */
@Component
public class SchemaMigrator {
    /**
     * 数据源，用于读取数据库元数据。
     */
    private final DataSource dataSource;

    /**
     * JDBC 执行器，用于创建表和追加列。
     */
    private final JdbcTemplate jdbcTemplate;

    /**
     * 注入数据源和 JDBC 执行器。
     *
     * @param dataSource 数据源
     * @param jdbcTemplate JDBC 执行器
     */
    public SchemaMigrator(DataSource dataSource, JdbcTemplate jdbcTemplate) {
        this.dataSource = dataSource;
        this.jdbcTemplate = jdbcTemplate;
    }

    /**
     * Spring 初始化后执行 schema 补丁。
     *
     * @throws SQLException 读取数据库元数据失败时抛出
     */
    @jakarta.annotation.PostConstruct
    public void migrate() throws SQLException {
        createImportQuestionTables();
        createImportTaskSnapshotTable();
        createStorageFileTable();
        addColumnIfMissing("java_import_tasks", "paper_ocr_job_json", "TEXT");
        addColumnIfMissing("java_import_tasks", "answer_ocr_job_json", "TEXT");
        addColumnIfMissing("java_import_tasks", "paper_ocr_status", "VARCHAR(40)");
        addColumnIfMissing("java_import_tasks", "answer_ocr_status", "VARCHAR(40)");
        addColumnIfMissing("java_import_tasks", "failure_reason", "TEXT");
        addColumnIfMissing("java_callback_events", "idempotency_key", "VARCHAR(160)");
        addColumnIfMissing("java_callback_events", "max_retry_count", "INT");
        addColumnIfMissing("java_callback_events", "next_retry_at", "TIMESTAMP");
        addColumnIfMissing("java_papers", "sub_selections_json", "TEXT");
        addColumnIfMissing("java_import_questions", "image_placements_json", "TEXT");
        addColumnIfMissing("java_bank_questions", "image_placements_json", "TEXT");
    }

    /** Create the pre-canonicalization snapshot table used by rollback. */
    private void createImportTaskSnapshotTable() {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS java_import_task_snapshots (
                  id VARCHAR(80) PRIMARY KEY,
                  task_id VARCHAR(80) NOT NULL,
                  snapshot_type VARCHAR(40) NOT NULL,
                  version BIGINT NOT NULL,
                  snapshot_json TEXT NOT NULL,
                  created_at TIMESTAMP
                )
                """);
    }

    /**
     * 创建导入题和导入题图表。
     */
    private void createImportQuestionTables() {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS java_import_questions (
                  id VARCHAR(80) PRIMARY KEY,
                  task_id VARCHAR(80) NOT NULL,
                  source_question_id VARCHAR(80),
                  question_number INT,
                  status VARCHAR(40),
                  type VARCHAR(40),
                  stem_markdown TEXT,
                  manual_markdown TEXT,
                  answer TEXT,
                  analysis TEXT,
                  knowledge_point_ids_json TEXT,
                  knowledge_points_json TEXT,
                  difficulty VARCHAR(40),
                  score DOUBLE,
                  images_json TEXT,
                  image_placements_json TEXT,
                  options_json TEXT,
                  children_json TEXT,
                  math_validation_json TEXT,
                  raw_json TEXT,
                  created_at TIMESTAMP,
                  updated_at TIMESTAMP
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS java_import_question_images (
                  id VARCHAR(120) PRIMARY KEY,
                  task_id VARCHAR(80) NOT NULL,
                  question_id VARCHAR(80) NOT NULL,
                  image_index INT,
                  name VARCHAR(255),
                  path VARCHAR(1024),
                  url VARCHAR(1024),
                  raw_json TEXT,
                  created_at TIMESTAMP,
                  updated_at TIMESTAMP
                )
                """);
    }

    /**
     * 创建 Java 文件元数据表。
     */
    private void createStorageFileTable() {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS java_storage_files (
                  id VARCHAR(80) PRIMARY KEY,
                  business_type VARCHAR(80) NOT NULL,
                  business_id VARCHAR(120) NOT NULL,
                  field_name VARCHAR(80),
                  original_filename VARCHAR(255),
                  content_type VARCHAR(255),
                  size_bytes BIGINT,
                  storage_type VARCHAR(40),
                  bucket VARCHAR(255),
                  object_key VARCHAR(1024),
                  local_path VARCHAR(1024),
                  url VARCHAR(1024),
                  created_at TIMESTAMP,
                  updated_at TIMESTAMP
                )
                """);
    }

    /**
     * 在列不存在时追加列。
     *
     * @param tableName 表名
     * @param columnName 列名
     * @param definition 列定义
     * @throws SQLException 查询列信息失败时抛出
     */
    private void addColumnIfMissing(String tableName, String columnName, String definition) throws SQLException {
        if (hasColumn(tableName, columnName)) {
            return;
        }
        jdbcTemplate.execute("ALTER TABLE " + tableName + " ADD COLUMN " + columnName + " " + definition);
    }

    /**
     * 判断表中是否存在指定列。
     *
     * @param tableName 表名
     * @param columnName 列名
     * @return true 表示列已存在
     * @throws SQLException 查询数据库元数据失败时抛出
     */
    private boolean hasColumn(String tableName, String columnName) throws SQLException {
        try (Connection connection = dataSource.getConnection()) {
            DatabaseMetaData metaData = connection.getMetaData();
            return hasColumn(metaData, tableName, columnName)
                    || hasColumn(metaData, tableName.toUpperCase(java.util.Locale.ROOT), columnName.toUpperCase(java.util.Locale.ROOT));
        }
    }

    /**
     * 使用数据库元数据查询列是否存在。
     *
     * @param metaData 数据库元数据
     * @param tableName 表名
     * @param columnName 列名
     * @return true 表示列存在
     * @throws SQLException 查询失败时抛出
     */
    private boolean hasColumn(DatabaseMetaData metaData, String tableName, String columnName) throws SQLException {
        try (ResultSet columns = metaData.getColumns(null, null, tableName, columnName)) {
            return columns.next();
        }
    }
}
