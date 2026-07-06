package com.aigeneration.questionbank.engine.service;

import com.aigeneration.questionbank.capability.service.CapabilityCatalogService;
import com.aigeneration.questionbank.engine.model.EngineModels.DeliveryBoundary;
import com.aigeneration.questionbank.engine.model.EngineModels.EngineCatalog;
import com.aigeneration.questionbank.engine.model.EngineModels.EngineInterfaceDescriptor;
import com.aigeneration.questionbank.engine.model.EngineModels.EngineModuleDescriptor;
import com.aigeneration.questionbank.engine.model.EngineModels.PlatformRequirement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * Question Engine 目录服务。
 *
 * <p>该服务提供 engine 总目录、四个核心模块、补充能力、平台依赖、交付边界以及接口清单。
 * 返回数据是平台集成契约，不直接执行导入、题库或组卷业务。</p>
 */
@Service
public class EngineCatalogService {
    /**
     * Engine 在平台能力体系中的稳定编码。
     */
    public static final String ENGINE_CODE = "question-engine";

    /**
     * 接口清单解析时支持识别的 HTTP 方法集合。
     */
    private static final Set<String> HTTP_METHODS = Set.of("GET", "POST", "PUT", "DELETE", "PATCH");

    /**
     * 补充能力目录服务，用于合并 review-workbench、AI、导出、文件、回调和 SDK 能力。
     */
    private final CapabilityCatalogService capabilityCatalogService;

    /**
     * 注入补充能力目录服务。
     *
     * @param capabilityCatalogService 能力目录服务
     */
    public EngineCatalogService(CapabilityCatalogService capabilityCatalogService) {
        this.capabilityCatalogService = capabilityCatalogService;
    }

    /**
     * 返回 question-engine 总目录。
     *
     * @return engine 总目录
     */
    public EngineCatalog catalog() {
        return new EngineCatalog(
                ENGINE_CODE,
                "题库加工能力发动机",
                "只提供试卷识别、题目加工、题库题目管理、组卷和知识点基础能力；不承载平台用户、租户、权限、组织、课程班级、审核流、最终发布和统一文件中心。",
                modules(),
                supplementalCapabilities(),
                platformRequirements(),
                deliveryBoundary()
        );
    }

    /**
     * 返回 engine 四个核心模块描述。
     *
     * @return 模块描述列表
     */
    public List<EngineModuleDescriptor> modules() {
        return List.of(questionImport(), questionBank(), paperAssembly(), knowledgeBase());
    }

    /**
     * 按模块编码查询单个模块。
     *
     * @param code 模块编码
     * @return 模块描述
     */
    public EngineModuleDescriptor module(String code) {
        return modules().stream()
                .filter(module -> module.code().equals(code))
                .findFirst()
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Engine module not found"));
    }

    /**
     * 返回交付时可由平台复用或改造的补充能力。
     *
     * @return 补充能力列表
     */
    public List<Map<String, Object>> supplementalCapabilities() {
        return capabilityCatalogService.deliveryCapabilities();
    }

    /**
     * 返回平台侧运行 question-engine 时需要提供的外部能力。
     *
     * @return 平台依赖清单
     */
    public List<PlatformRequirement> platformRequirements() {
        return List.of(
                new PlatformRequirement(
                        "identity-and-tenant",
                        "平台提供用户、教师、学校/机构、租户和权限上下文；engine 只接收上下文标识，不做登录和权限判定。",
                        "可通过请求头或网关注入 tenantId、operatorId、schoolId。",
                        List.of("ENGINE_TENANT_HEADER", "ENGINE_OPERATOR_HEADER")
                ),
                new PlatformRequirement(
                        "database",
                        "企业部署使用 MySQL 保存 engine 业务状态和快照；本地开发可继续使用 H2。",
                        "平台也可接管最终题库主表，engine 输出 question-package 后由平台入库。",
                        List.of("SPRING_PROFILES_ACTIVE", "DB_URL", "DB_USERNAME", "DB_PASSWORD")
                ),
                new PlatformRequirement(
                        "object-storage",
                        "平台应提供对象存储或文件中心，用于试卷原文件、题图、OCR 产物和导出文件。",
                        "本地模式可使用 java-storage.local-root；企业模式建议 MinIO 或平台文件中心。",
                        List.of("ENTERPRISE_MINIO_ENABLED", "MINIO_ENDPOINT", "MINIO_BUCKET", "JAVA_STORAGE_LOCAL_ROOT")
                ),
                new PlatformRequirement(
                        "python-workers",
                        "Python 只作为必要能力 worker：OCR provider、AI 标准化、AI 解析、公式处理和 Pandoc 导出。",
                        "后续可把 worker 放到内网，仅允许 Java engine 调用。",
                        List.of("PYTHON_WORKER_BASE_URL", "PYTHON_WORKER_ENABLED")
                ),
                new PlatformRequirement(
                        "ocr-provider",
                        "平台需要配置 OCR-Flow provider；当前默认 MinerU，未来可替换其它开源 OCR/版面解析项目。",
                        "不同 provider 可通过后缀配置和 provider 实现扩展。",
                        List.of("OCR_FLOW_PROVIDER", "OCR_FLOW_EXTENSIONS", "MINERU_COMMAND")
                ),
                new PlatformRequirement(
                        "llm",
                        "如需自动拆题、AI 标准化、AI 解析和答案解析匹配，平台需配置大模型 API。",
                        "未配置时 engine 保留本地规则和人工校验闭环。",
                        List.of("DASHSCOPE_API_KEY", "DASHSCOPE_MODEL", "ENABLE_LLM_SPLIT")
                ),
                new PlatformRequirement(
                        "async-and-observability",
                        "生产环境应由平台提供异步任务、重试、限流、日志链路和监控指标接入。",
                        "当前 Java 已提供 TraceId 和 Prometheus actuator 入口，MQ/Redis 可分阶段启用。",
                        List.of("ENTERPRISE_REDIS_ENABLED", "ENTERPRISE_MQ_ENABLED", "ROCKETMQ_NAME_SERVER")
                )
        );
    }

    /**
     * 返回 question-engine 的交付边界。
     *
     * <p>边界明确哪些源码、资源、Python worker 和文档属于 engine 交付，哪些本地演示平台
     * 或生成物不属于企业平台交付内容。</p>
     *
     * @return 交付边界描述
     */
    public DeliveryBoundary deliveryBoundary() {
        return new DeliveryBoundary(
                List.of(
                        "backend/src/main/java/com/aigeneration/questionbank/engine",
                        "backend/src/main/java/com/aigeneration/questionbank/capability",
                        "backend/src/main/java/com/aigeneration/questionbank/domain",
                        "backend/src/main/java/com/aigeneration/questionbank/common",
                        "backend/src/main/java/com/aigeneration/questionbank/config",
                        "backend/src/main/java/com/aigeneration/questionbank/migration",
                        "backend/src/main/resources",
                        "backend/python-worker/app",
                        "backend/python-worker/app/ocr_flow.py",
                        "backend/python-worker/app/llm_splitter.py",
                        "backend/python-worker/app/math_normalizer.py",
                        "docs/product/OCR_PHASE_1_SPEC.md",
                        "docs/architecture/ENGINE_DELIVERY_BOUNDARY.md"
                ),
                List.of(
                        "local-platform",
                        "历史 protocal 原型仓库",
                        "backend/storage",
                        "docs/renders",
                        "本地演示数据、截图、Replit 原型代码和小平台页面实现"
                ),
                List.of(
                        "四个模块能力目录和 Java API",
                        "导入任务元数据、题目题图快照、题库题、试卷、知识点的数据层",
                        "文件存储元数据和原文件预览",
                        "能力 API、标准题目包和平台交付契约",
                        "review-workbench、ai-flow、export-flow、file-flow、callback-flow、sdk/openapi 能力目录"
                ),
                List.of(
                        "OCR-Flow provider 执行",
                        "AI 标准化和 AI 解析",
                        "LaTeX/公式处理",
                        "Pandoc DOCX/PDF 导出"
                ),
                List.of(
                        "Vite React 本地小平台",
                        "题目导入、题库中心、组卷中心、知识点库页面",
                        "Replit 原型和截图资产",
                        "演示用 H2/JSON 数据文件"
                )
        );
    }

    /**
     * 汇总 question-engine 面向平台的 Java API 清单。
     *
     * <p>清单由 engine 自身目录、四个核心模块和补充能力目录展开得到；当能力目录只声明路径、
     * 未声明 HTTP 方法时使用 ANY，且去重时优先保留带明确 HTTP 方法的条目。</p>
     */
    public List<EngineInterfaceDescriptor> interfaces() {
        List<EngineInterfaceDescriptor> items = new ArrayList<>();

        addInterface(items, "engine-catalog", "Engine 能力目录", "GET /api/engine",
                "查看 question-engine 总目录、模块清单、补充能力、平台要求和交付边界。",
                "platform-api", "engine-catalog");
        addInterface(items, "engine-catalog", "Engine 能力目录", "GET /api/engine/modules",
                "查看 question-engine 四个可二次开发模块。",
                "platform-api", "engine-catalog");
        addInterface(items, "engine-catalog", "Engine 能力目录", "GET /api/engine/modules/{code}",
                "按模块编码查看单个模块的能力、依赖、平台输入和数据契约。",
                "platform-api", "engine-catalog");
        addInterface(items, "engine-catalog", "Engine 能力目录", "GET /api/engine/supplemental-capabilities",
                "查看 review-workbench、ai-flow、export-flow、file-flow、callback-flow 和 sdk-openapi 等补充能力。",
                "platform-api", "engine-catalog");
        addInterface(items, "engine-catalog", "Engine 能力目录", "GET /api/engine/platform-requirements",
                "查看平台侧必须提供或建议提供的用户、租户、对象存储、worker、大模型和可观测能力。",
                "platform-api", "engine-catalog");
        addInterface(items, "engine-catalog", "Engine 能力目录", "GET /api/engine/delivery-boundary",
                "查看 question-engine 交付包含路径、排除路径、Java 归属和 Python 补充边界。",
                "platform-api", "engine-catalog");
        addInterface(items, "engine-catalog", "Engine 能力目录", "GET /api/engine/interfaces",
                "获取 question-engine 面向平台的 Java API 扁平清单。",
                "platform-api", "engine-catalog");
        addInterface(items, "capability-catalog", "能力总目录", "GET /api/capabilities",
                "查看 question-engine 暴露的主能力和补充能力目录。",
                "platform-api", "core-capability");
        addInterface(items, "ocr-flow", "OCR-Flow 试卷识别加工能力", "GET /api/capabilities/ocr-flow",
                "查看 OCR provider 合约、配置键、Java API、worker API 和替换 provider 策略。",
                "platform-api", "core-capability");
        addInterface(items, "ocr-flow", "OCR-Flow 试卷识别加工能力", "GET /api/capabilities/ocr-flow/runtime",
                "查看 Python worker 和当前 OCR provider 的运行时诊断信息。",
                "platform-api", "core-capability");

        modules().forEach(module -> module.javaApis().forEach(endpoint -> addInterface(
                items,
                module.code(),
                module.name(),
                endpoint,
                module.responsibility(),
                "platform-api",
                "engine-module"
        )));

        supplementalCapabilities().forEach(capability -> {
            String code = String.valueOf(capability.getOrDefault("code", "supplemental-capability"));
            String name = String.valueOf(capability.getOrDefault("name", code));
            String boundary = String.valueOf(capability.getOrDefault("boundary", ""));
            Object javaEndpoints = capability.get("javaEndpoints");
            if (javaEndpoints instanceof List<?> endpoints) {
                endpoints.forEach(endpoint -> addInterface(
                        items,
                        code,
                        name,
                        String.valueOf(endpoint),
                        boundary,
                        "platform-api",
                        "supplemental-capability"
                ));
            }
        });

        return deduplicate(items);
    }

    /**
     * 构造题目导入模块描述。
     *
     * @return 题目导入模块
     */
    private EngineModuleDescriptor questionImport() {
        return new EngineModuleDescriptor(
                "question-import",
                "题目导入能力",
                "接收试卷/答案文件，创建 OCR-Flow job，同步导入任务元数据、OCR 状态、导入题、题图和原文件预览，输出待校验题目和标准题目包。",
                "Java 管任务元数据、状态机、文件记录和题目题图快照；Python 只执行 OCR/AI worker。",
                List.of("ocr-flow", "question-processing", "review-workbench", "ai-flow", "file-flow", "callback-flow", "source-file-preview", "manual-review-snapshot"),
                List.of(
                        "GET /api/capabilities/question-processing",
                        "GET /api/capabilities/question-processing/jobs",
                        "POST /api/capabilities/question-processing/jobs",
                        "GET /api/capabilities/question-processing/jobs/{jobId}",
                        "GET /api/capabilities/question-processing/jobs/{jobId}/question-package",
                        "POST /api/import-tasks",
                        "GET /api/import-tasks",
                        "GET /api/import-tasks/{taskId}",
                        "GET /api/import-tasks/{taskId}/source/{paper|answer}"
                ),
                List.of("/worker/ocr-flow", "/worker/ocr", "/worker/ai/standardize", "/worker/ai/analysis"),
                List.of("ocr-flow", "knowledge-base", "question-bank"),
                List.of("用户/租户上下文", "对象存储策略", "大模型配置", "任务回调地址或轮询策略"),
                List.of("OCR provider", "答案解析匹配策略", "校验工作台嵌入页", "任务完成回调", "平台文件中心适配"),
                List.of("ProcessingJob", "question-package.v1", "SourceFilePreview", "ImportQuestionSnapshot")
        );
    }

    /**
     * 构造题库模块描述。
     *
     * @return 题库模块
     */
    private EngineModuleDescriptor questionBank() {
        return new EngineModuleDescriptor(
                "question-bank",
                "题库能力",
                "保存和查询标准化题目，支持题干、选项、答案、解析、题图、知识点候选、难度、分值和来源追踪。",
                "Java 管题库题目主快照；平台可选择接收 question-package 后写入自己的最终题库。",
                List.of("bank-question-crud", "question-search-filter", "question-image-metadata", "ai-flow", "file-flow", "ai-analysis-entry"),
                List.of(
                        "GET /api/question-bank/questions",
                        "POST /api/question-bank/questions",
                        "GET /api/question-bank/questions/{id}",
                        "PUT /api/question-bank/questions/{id}",
                        "DELETE /api/question-bank/questions/{id}",
                        "POST /api/import-tasks/{taskId}/questions/{questionId}/bank",
                        "POST /api/import-tasks/{taskId}/bank"
                ),
                List.of("/worker/ai/standardize", "/worker/ai/analysis"),
                List.of("knowledge-base", "question-import"),
                List.of("题目分类体系", "平台最终题库版本策略", "审核和发布规则"),
                List.of("重复题检测", "题目版本管理", "题目审核状态", "平台知识点映射"),
                List.of("BankQuestion", "QuestionImage", "QuestionSourceEvidence")
        );
    }

    /**
     * 构造组卷模块描述。
     *
     * @return 组卷模块
     */
    private EngineModuleDescriptor paperAssembly() {
        return new EngineModuleDescriptor(
                "paper-assembly",
                "组卷能力",
                "基于题库题目创建试卷，支持手动选题、规则选题、排序、赋分、卷头、预览和导出。",
                "Java 管试卷定义、题目引用和分值；Python 暂时补充 Pandoc/LaTeX 导出 worker。",
                List.of("paper-crud", "question-selection", "paper-preview", "export-flow", "file-flow", "paper-export"),
                List.of(
                        "GET /api/papers",
                        "POST /api/papers",
                        "GET /api/papers/{id}",
                        "PUT /api/papers/{id}",
                        "DELETE /api/papers/{id}",
                        "GET /api/papers/{id}/export"
                ),
                List.of("/worker/export"),
                List.of("question-bank", "knowledge-base"),
                List.of("试卷模板策略", "发布审核流", "考试/作业业务归属"),
                List.of("模板渲染", "导出格式", "组卷规则", "发布前校验"),
                List.of("Paper", "PaperQuestionRef", "PaperExportRequest")
        );
    }

    /**
     * 构造知识点库模块描述。
     *
     * @return 知识点库模块
     */
    private EngineModuleDescriptor knowledgeBase() {
        return new EngineModuleDescriptor(
                "knowledge-base",
                "知识点库能力",
                "提供知识点基础树、学科、年级、描述和题目关联候选；支持本地闭环，也可对接平台权威知识点主数据。",
                "Java 管本地知识点快照；企业平台若已有权威主数据，engine 应只做读取和映射缓存。",
                List.of("knowledge-point-crud", "knowledge-search", "question-knowledge-mapping", "sdk/openapi"),
                List.of(
                        "GET /api/knowledge-points",
                        "POST /api/knowledge-points",
                        "PUT /api/knowledge-points/{id}",
                        "DELETE /api/knowledge-points/{id}"
                ),
                List.of(),
                List.of(),
                List.of("平台权威学科/年级/教材/知识点编码", "知识点同步或查询接口"),
                List.of("知识点编码映射", "教材版本", "多级树约束", "平台只读模式"),
                List.of("KnowledgePoint", "KnowledgePointMapping")
        );
    }

    /**
     * 将 endpoint 字符串追加为标准接口描述项。
     *
     * @param items 输出接口列表
     * @param groupCode 接口所属能力或模块编码
     * @param groupName 接口所属能力或模块名称
     * @param endpoint 原始端点字符串，可带 HTTP 方法
     * @param description 接口说明
     * @param audience 接口面向的调用方
     * @param source 接口来源分类
     */
    private void addInterface(
            List<EngineInterfaceDescriptor> items,
            String groupCode,
            String groupName,
            String endpoint,
            String description,
            String audience,
            String source
    ) {
        ParsedEndpoint parsedEndpoint = parseEndpoint(endpoint);
        items.add(new EngineInterfaceDescriptor(
                groupCode,
                groupName,
                parsedEndpoint.method(),
                parsedEndpoint.path(),
                description,
                audience,
                source
        ));
    }

    /**
     * 对接口清单按方法和路径去重。
     *
     * <p>当同一路径同时存在 ANY 和明确 HTTP 方法时保留明确方法，避免能力目录中的粗粒度
     * 路径覆盖控制器真实接口。</p>
     *
     * @param items 原始接口列表
     * @return 去重后的接口列表
     */
    private List<EngineInterfaceDescriptor> deduplicate(List<EngineInterfaceDescriptor> items) {
        Map<String, EngineInterfaceDescriptor> deduplicated = new LinkedHashMap<>();
        items.forEach(item -> {
            String key = item.method() + " " + item.path();
            if ("ANY".equals(item.method())) {
                boolean hasExplicitMethod = deduplicated.values().stream()
                        .anyMatch(existing -> item.path().equals(existing.path()) && !"ANY".equals(existing.method()));
                if (hasExplicitMethod) {
                    return;
                }
            } else {
                deduplicated.remove("ANY " + item.path());
            }
            deduplicated.putIfAbsent(key, item);
        });
        return List.copyOf(deduplicated.values());
    }

    /**
     * 解析接口端点字符串。
     *
     * @param endpoint 原始端点字符串，例如 {@code GET /api/engine}
     * @return 解析后的 HTTP 方法和路径
     */
    private ParsedEndpoint parseEndpoint(String endpoint) {
        String trimmed = endpoint == null ? "" : endpoint.trim();
        int firstSpace = trimmed.indexOf(' ');
        if (firstSpace > 0) {
            String method = trimmed.substring(0, firstSpace).toUpperCase(Locale.ROOT);
            if (HTTP_METHODS.contains(method)) {
                return new ParsedEndpoint(method, trimmed.substring(firstSpace + 1).trim());
            }
        }
        return new ParsedEndpoint("ANY", trimmed);
    }

    /**
     * 表示从端点字符串解析得到的 HTTP 方法和路径。
     *
     * @param method HTTP 方法，无法识别时为 ANY
     * @param path 接口路径
     */
    private record ParsedEndpoint(String method, String path) {
    }
}
