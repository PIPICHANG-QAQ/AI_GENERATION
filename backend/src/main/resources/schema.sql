-- 知识点快照表：保存本地知识点树和学科/年级描述。
CREATE TABLE IF NOT EXISTS java_knowledge_points (
  id VARCHAR(80) PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  parent_id VARCHAR(80),
  subject VARCHAR(80),
  grade VARCHAR(80),
  description TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- 题库题快照表：保存标准化题目、答案解析、题图、选项、子题和来源追踪。
CREATE TABLE IF NOT EXISTS java_bank_questions (
  id VARCHAR(80) PRIMARY KEY,
  source_import_task_id VARCHAR(80),
  source_import_question_id VARCHAR(80),
  source VARCHAR(255),
  stage VARCHAR(80),
  subject VARCHAR(80),
  grade VARCHAR(80),
  region VARCHAR(120),
  question_year VARCHAR(40),
  title VARCHAR(255),
  question_number INT,
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
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- 导入任务表：保存试卷/答案 OCR job、任务状态、失败原因和 worker 原始快照。
CREATE TABLE IF NOT EXISTS java_import_tasks (
  id VARCHAR(80) PRIMARY KEY,
  stage VARCHAR(80),
  subject VARCHAR(80),
  grade VARCHAR(80),
  region VARCHAR(120),
  task_year VARCHAR(40),
  title VARCHAR(255),
  status VARCHAR(80),
  paper_file_json TEXT,
  answer_file_json TEXT,
  paper_ocr_job_id VARCHAR(80),
  answer_ocr_job_id VARCHAR(80),
  paper_ocr_job_json TEXT,
  answer_ocr_job_json TEXT,
  paper_ocr_status VARCHAR(40),
  answer_ocr_status VARCHAR(40),
  failure_reason TEXT,
  question_count INT,
  raw_json TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- 导入任务结构快照：在 canonicalization 应用前保存任务和题目，支持审计与回滚。
CREATE TABLE IF NOT EXISTS java_import_task_snapshots (
  id VARCHAR(80) PRIMARY KEY,
  task_id VARCHAR(80) NOT NULL,
  snapshot_type VARCHAR(40) NOT NULL,
  version BIGINT NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TIMESTAMP
);

-- 导入题表：保存导入任务拆出的题目快照、人工 Markdown、AI 回写和公式校验结果。
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
);

-- 导入题图表：按任务和题目索引保存从 OCR 或人工上传得到的题图引用。
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
);

-- Java 文件元数据表：统一记录本地/MinIO 文件位置和业务归属。
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
);

-- 试卷定义表：保存组卷题目 ID、规则、分值、卷头和答案展示配置。
CREATE TABLE IF NOT EXISTS java_papers (
  id VARCHAR(80) PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  subject VARCHAR(80),
  grade VARCHAR(80),
  question_ids_json TEXT,
  rules_json TEXT,
  answer_display VARCHAR(40),
  scores_json TEXT,
  sub_selections_json TEXT,
  header_json TEXT,
  status VARCHAR(40),
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- 导出 job 表：记录试卷导出请求、状态、失败原因和导出文件 ID。
CREATE TABLE IF NOT EXISTS java_export_jobs (
  id VARCHAR(80) PRIMARY KEY,
  paper_id VARCHAR(80) NOT NULL,
  export_format VARCHAR(20),
  variant VARCHAR(40),
  status VARCHAR(40),
  file_id VARCHAR(80),
  failure_reason TEXT,
  request_json TEXT,
  response_json TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- AI job 表：记录 AI 标准化/解析请求、响应、状态和失败原因。
CREATE TABLE IF NOT EXISTS java_ai_jobs (
  id VARCHAR(80) PRIMARY KEY,
  target_type VARCHAR(80),
  target_id VARCHAR(120),
  operation VARCHAR(80),
  status VARCHAR(40),
  retry_count INT,
  failure_reason TEXT,
  request_json TEXT,
  response_json TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- 回调事件表：记录 callback-flow 投递状态、幂等键、重试次数和死信时间。
CREATE TABLE IF NOT EXISTS java_callback_events (
  id VARCHAR(80) PRIMARY KEY,
  event_type VARCHAR(120),
  aggregate_type VARCHAR(80),
  aggregate_id VARCHAR(120),
  status VARCHAR(40),
  callback_url VARCHAR(1024),
  idempotency_key VARCHAR(160),
  payload_json TEXT,
  response_json TEXT,
  failure_reason TEXT,
  retry_count INT,
  max_retry_count INT,
  next_retry_at TIMESTAMP,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
