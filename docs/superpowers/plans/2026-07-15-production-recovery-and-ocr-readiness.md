# Production Recovery and OCR Readiness Implementation Plan

> **执行要求：** 使用 `subagent-driven-development` 或 `executing-plans` 逐任务执行；每个代码修复先写失败测试，再实现最小修复。任何服务启动成功、OCR 成功或测试通过的结论，都必须附本轮新鲜命令输出。

**Goal:** 恢复本地和服务器运行态，修复服务器 MinerU OCR 的损坏依赖，补上能够识别“命令存在但运行时不可用”的健康门禁，重试既有任务并完成可回滚的运行态验收；只同步已有证据支撑的计划勾选状态。

**Architecture:** 保持 Java 编排、Python worker、宿主机 MinerU venv 和 Docker 组合不变。新增 MinerU 深度 runtime probe，并由 provider 状态、安装检查、容器启动门禁共同复用。服务器在同一文件系统内构建并验证新 venv，使用目录重命名原子切换；应用发布采用 staging、备份和显式排除持久数据的同步流程。

**Tech Stack:** Python 3.10、FastAPI、Java 17、Spring Boot、React/Vite、Docker Compose、MinerU 3.4.2、unittest、Maven、Vitest、Bash、SSH。

**Design:** `docs/superpowers/specs/2026-07-15-production-recovery-and-ocr-readiness-design.md`

---

## 执行纪律与已知约束

- 当前工作分支为 `codex/production-recovery-20260715`；设计提交为 `b6413b1`。
- 当前工作区包含此前 provider 解耦的未提交改动。先做补丁备份和测试检查点，再提交；不得用 reset、checkout 或 clean 丢弃它们。
- 本地 `vendor/mineru-wheelhouse` 是 macOS ARM64 制品，禁止上传到 Linux x86_64 服务器安装。服务器 venv 必须在服务器端联网解析 Linux wheel。
- 服务器凭据只在交互式 SSH/SCP 提示中输入，不写入命令行、脚本、配置、日志、计划或 shell history。
- 服务器应用目录 `/home/user/AI_GENERATION_DOCKER` 不是 Git 仓库，发布必须使用带 manifest 和 SHA-256 的 delivery archive。
- 服务器持久目录、数据库、上传文件、任务状态、模型缓存和 `.env` 不进入覆盖同步范围。
- `tests/ocrflow-performance/baseline-ref.json` 当前是 `pending-controlled-baseline`。因此可以跑 benchmark 工具单测和 golden replay，但不得现场伪造正式 benchmark baseline；相关生产勾选保持未完成并注明阻塞证据。
- 本阶段不实现用户权限、题目版本、企业审核流、真实 MQ、超时扫描器和正式 SDK 发布包。

## Task 1：冻结现有 provider 解耦成果并建立可恢复检查点

**Files:**

- Inspect: `git status --short`
- Inspect: `git diff --stat`
- Inspect: `docs/superpowers/plans/2026-07-14-ocr-provider-postprocess-decoupling.md`
- Inspect: `docs/superpowers/plans/2026-07-14-ocr-flow-modularization-and-portability.md`
- Create outside Git: `.artifacts/recovery/20260715-pre-recovery.patch`

### Step 1：保存未提交改动的可恢复补丁

Run:

```bash
mkdir -p .artifacts/recovery
git status --short
git diff --binary > .artifacts/recovery/20260715-pre-recovery.patch
git diff --check
```

Expected: 补丁文件非空；`git diff --check` 无空白错误。若发现与 OCR/provider/接口/文档无关的用户改动，停止对该文件的暂存并在执行记录中列出。

### Step 2：运行现有成果基线

Run:

```bash
./scripts/test_python_worker.sh
JAVA_HOME="$(/usr/libexec/java_home -v 17)" PATH="$JAVA_HOME/bin:$PATH" mvn -f backend/pom.xml test
npm --prefix local-platform test -- --run
python3 scripts/test_ocrflow_golden.py
python3 scripts/test_benchmark_ocrflow.py
python3 scripts/test_check_project_portability.py
python3 scripts/test_check_ocrflow_boundaries.py
python3 scripts/check_question_engine_contract.py
```

Expected: Python 不少于 170 项、Java 不少于 81 项、前端不少于 22 项，其余工具测试全部通过。正式 benchmark compare 不在此处执行，因为受控 baseline 尚未发布。

### Step 3：提交经过验证的现有 provider 解耦改动

先逐文件审阅：

```bash
git diff --name-status
git diff -- backend/python-worker/app/ocr_flow.py backend/python-worker/tests/test_ocr_flow.py
git diff -- question-engine/openapi/question-engine.v1.yaml docs/delivery/QUESTION_ENGINE_INTERFACE_GUIDE.md
git status --short
```

只暂存已审阅且属于既有解耦交付的文件；禁止使用 `git add -A`。随后运行：

```bash
git diff --cached --check
git commit -m "refactor: complete provider-neutral OCR handoff"
```

Expected: provider 解耦改动形成独立检查点；设计和本实施计划已有各自文档提交；工作区只保留后续恢复任务产生的变更。

## Task 2：用失败测试复现“命令存在但 MinerU runtime 已损坏”

**Files:**

- Modify: `backend/python-worker/tests/test_ocr_flow.py`
- Modify: `backend/python-worker/app/ocr_flow.py`

### Step 1：添加 MarkupSafe/Jinja/MinerU 深度导入失败的 RED 测试

在 `MineruOcrProviderTest` 增加测试，构造一个 `--version` 成功但 `python -c` 深度导入失败的 venv：

```python
def test_status_rejects_command_when_runtime_import_probe_fails(self):
    with tempfile.TemporaryDirectory() as tmp:
        app_root = Path(tmp)
        command_path = self._write_local_mineru(app_root, "#!/bin/sh\nexit 0\n")
        provider = MineruOcrProvider(app_root, 5)
        command = ProviderCommand(
            args=[str(command_path)],
            display=str(command_path),
            source="local-venv-script",
        )
        with patch.object(provider, "_command_candidates", return_value=[command]), patch.object(
            provider,
            "_probe_command",
            return_value={"valid": True, "versionProbeOk": True, "version": "3.4.2", "error": None},
        ), patch.object(
            provider,
            "_probe_runtime",
            return_value={
                "runtimeProbeOk": False,
                "runtimePython": str(command_path.parent / "python"),
                "runtimeError": "cannot import name 'Markup' from 'markupsafe'",
            },
        ):
            status = provider.status()

    self.assertFalse(status["installed"])
    self.assertFalse(status["runtimeProbeOk"])
    self.assertIn("Markup", status["error"])
```

同时把测试文件的 import 扩为 `from app.ocr_flow import MineruOcrProvider, ProviderCommand, ...`。

如果现有类型名与上例不同，保留现有 command 数据结构并只调整构造方式，不改变断言语义。

Run:

```bash
PYTHONPATH=backend/python-worker backend/python-worker/.venv/bin/python \
  -m unittest discover -s backend/python-worker/tests -p test_ocr_flow.py
```

Expected: FAIL，原因是 provider 还没有 `_probe_runtime`，或 `installed` 仍仅由命令存在决定。

### Step 2：实现同解释器深度 runtime probe

在 `MineruOcrProvider` 中加入固定探针代码。探针解释器选择顺序为：配置命令同目录的 `python`、Python entrypoint 自身解释器、最后才是当前 worker 解释器。禁止用系统 Python 检查另一个 venv。

```python
RUNTIME_IMPORT_PROBE = """
from markupsafe import Markup
from jinja2 import Environment
import transformers
from mineru.cli.common import read_fn
assert Markup and Environment and transformers and read_fn
""".strip()

def _runtime_python(self, command: ResolvedMineruCommand) -> Path | None:
    executable = Path(command.args[0]).expanduser()
    sibling = executable.parent / "python"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling.resolve()
    if executable.resolve() == Path(sys.executable).resolve():
        return Path(sys.executable)
    return None

def _probe_runtime(self, command: ResolvedMineruCommand) -> dict[str, object]:
    python = self._runtime_python(command)
    if python is None:
        return {
            "runtimeProbeOk": False,
            "runtimePython": None,
            "runtimeError": "unable to resolve the Python interpreter for MinerU",
        }
    try:
        completed = subprocess.run(
            [str(python), "-c", RUNTIME_IMPORT_PROBE],
            capture_output=True,
            text=True,
            timeout=min(self.timeout_seconds, 15),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "runtimeProbeOk": False,
            "runtimePython": str(python),
            "runtimeError": str(exc),
        }
    error = (completed.stderr or completed.stdout).strip()
    return {
        "runtimeProbeOk": completed.returncode == 0,
        "runtimePython": str(python),
        "runtimeError": None if completed.returncode == 0 else error[-2000:],
    }
```

调整 `resolve_command()`：version probe 仍用于发现命令；只有 version 可执行且 runtime probe 成功的候选才可返回。调整 `status()` 输出至少包含：

```python
{
    "installed": bool,
    "command": list[str] | None,
    "source": str | None,
    "versionProbeOk": bool,
    "runtimeProbeOk": bool,
    "runtimePython": str | None,
    "error": str | None,
}
```

`run()` 必须复用同一解析结果；runtime 不健康时在创建 OCR 子进程前返回 provider unavailable，不能再排队后才失败。

深度导入会加载 Transformers，必须按“command 参数、解释器路径、解释器/命令 mtime”缓存 60 秒，避免每个 health 请求和每个 OCR 任务重复冷启动；cache 过期或 mtime 变化后重新探测。缓存只保存探针结果，不缓存 OCR 业务结果。

### Step 3：覆盖健康、损坏、超时和解释器缺失

补充/调整测试：

- 健康 venv：version 和 runtime 都成功，`installed=true`。
- MarkupSafe 导入失败：`installed=false` 且错误可定位。
- version probe 超时但命令可执行：保持现有兼容语义，但 runtime probe 必须成功。
- command 同目录没有 Python：拒绝跨 venv 误判。
- `run()` 在 runtime probe 失败时不调用 OCR 子进程。
- 60 秒内两次 `status()` 只执行一次深度导入；mtime 改变后必须重新执行。

Run:

```bash
PYTHONPATH=backend/python-worker backend/python-worker/.venv/bin/python \
  -m unittest backend.python-worker.tests.test_ocr_flow
./scripts/test_python_worker.sh
```

Expected: 全部通过，且 Python 总数高于 Task 1 基线。

### Step 4：提交

```bash
git add backend/python-worker/app/ocr_flow.py backend/python-worker/tests/test_ocr_flow.py
git diff --cached --check
git commit -m "fix: reject broken MinerU runtimes"
```

## Task 3：让检查脚本和容器启动复用深度 readiness

**Files:**

- Modify: `backend/python-worker/app/ocr_flow.py`
- Modify: `backend/python-worker/tests/test_ocr_flow.py`
- Modify: `scripts/check_mineru.py`
- Create: `scripts/test_check_mineru.py`
- Modify: `scripts/docker-entrypoint.sh`
- Modify: `scripts/start_server_docker.sh`
- Modify: `Dockerfile`
- Modify: `docker-compose.server.yml`
- Modify: `scripts/package_question_engine_delivery.py`

### Step 1：先写 `check_mineru.py` CLI 回归测试

测试使用 `unittest.mock`，不启动真实 MinerU：

```python
class CheckMineruCliTest(unittest.TestCase):
    def test_exit_one_when_runtime_probe_fails(self):
        status = {
            "installed": False,
            "runtimeProbeOk": False,
            "error": "cannot import Markup",
        }
        with mock.patch.object(check_mineru, "provider_status", return_value=status):
            self.assertEqual(1, check_mineru.main(["--json", "--skip-api"]))

    def test_check_api_requires_openapi_document(self):
        status = {"installed": True, "runtimeProbeOk": True, "error": None}
        with mock.patch.object(
            check_mineru,
            "provider_status",
            return_value={**status, "apiReady": False, "apiError": "connection refused"},
        ):
            self.assertEqual(1, check_mineru.main(["--json", "--check-api"]))
```

Run:

```bash
python3 scripts/test_check_mineru.py
```

Expected: FAIL，因为脚本还没有可测试的 `main(argv)`、`--skip-api` 和 `--check-api`。

### Step 2：实现机器可读检查模式和 API 探针

先在 `MineruOcrProvider.status(check_api: bool | None = None)` 增加 API readiness。`check_api=None` 时由 `MINERU_API_ENABLED` 决定；`False` 专供 API 启动前探针；`True` 强制检查 `${MINERU_API_URL}/openapi.json`。返回值增加 `apiEnabled`、`apiReady`、`apiUrl`、`apiError`。因此 worker 的 `/api/capabilities/ocr-flow/runtime` 会自动暴露真实 API 状态；`run()` 在配置了 API URL 时也要先验证 API readiness，再调用 MinerU CLI。

API 探针核心放在 `ocr_flow.py`，与 provider 状态和检查脚本共用：

```python
def _probe_api(self) -> dict[str, object]:
    url = self._api_url.rstrip("/") + "/openapi.json"
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            payload = json.load(response)
            status = response.status
        ready = status == 200 and isinstance(payload.get("paths"), dict)
        return {"apiReady": ready, "apiUrl": url, "apiError": None if ready else "invalid OpenAPI document"}
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"apiReady": False, "apiUrl": url, "apiError": str(exc)}
```

然后重构 `scripts/check_mineru.py`：

- `provider_status()` 返回 `MineruOcrProvider.status()`。
- `--skip-api` 只验证命令和同 venv 导入，供 API 启动前门禁使用。
- `--check-api` 调用 `provider.status(check_api=True)`，要求 HTTP 200 且 OpenAPI JSON 包含 `paths`；不猜测业务 OCR endpoint。
- `--json` 输出单行 JSON，不把 traceback 作为成功结果。
- 任一必需层失败返回退出码 1；参数错误返回 2。
- 自身切换到 worker venv 时必须原样转发 CLI 参数；测试直接调用 `main(argv)` 时不触发第二进程，避免丢失 mock 和退出码。

在 `backend/python-worker/tests/test_ocr_flow.py` 同时覆盖：API 返回合法 OpenAPI 时 `apiReady=true`；连接拒绝时 `apiReady=false` 且 `installed=false`；`status(check_api=False)` 在 API 启动前不发 HTTP 请求。`scripts/test_check_mineru.py` 覆盖三个 CLI 退出码和参数转发。

Run:

```bash
python3 scripts/test_check_mineru.py
MINERU_COMMAND="$PWD/backend/python-worker/.venv/bin/mineru" python3 scripts/check_mineru.py --json --skip-api
PYTHONPATH=backend/python-worker backend/python-worker/.venv/bin/python \
  -m unittest discover -s backend/python-worker/tests -p test_ocr_flow.py
```

Expected: 测试通过；本地 runtime 检查返回 0 和 `installed=true`、`runtimeProbeOk=true`。

### Step 3：给容器增加启动前后门禁

在 `scripts/docker-entrypoint.sh` 启动 `mineru-api` 前执行：

```bash
if [[ "${MINERU_API_ENABLED}" == "true" ]]; then
  /opt/question-engine/venv/bin/python /app/scripts/check_mineru.py --json --skip-api
  "${MINERU_API_COMMAND}" \
    --host "${MINERU_API_HOST}" \
    --port "${MINERU_API_PORT}" \
    --enable-vlm-preload "${MINERU_API_ENABLE_VLM_PRELOAD}" &
  pids+=("$!")
  for attempt in $(seq 1 90); do
    if /opt/question-engine/venv/bin/python /app/scripts/check_mineru.py --json --check-api; then
      break
    fi
    if [[ "$attempt" -eq 90 ]]; then
      echo "MinerU API readiness failed" >&2
      exit 1
    fi
    sleep 2
  done
fi
```

必须在 API readiness 成功后再启动 worker、Java 和 nginx。这样损坏 venv 不会生成“Java 健康但 OCR 永远失败”的容器。

`Dockerfile` 必须把探针同时复制进镜像：

```dockerfile
COPY scripts/docker-entrypoint.sh scripts/check_mineru.py /app/scripts/
```

在 `scripts/start_server_docker.sh` 的 Docker 构建前增加宿主机 venv 检查：

```bash
if [[ "${MINERU_API_ENABLED:-false}" == "true" ]]; then
  MINERU_COMMAND="${MINERU_HOST_COMMAND:-$ROOT_DIR/vendor/mineru-venv/bin/mineru}" \
    python3 scripts/check_mineru.py --json --skip-api
fi
```

Java health 成功后再验证：

```bash
curl -fsS "http://127.0.0.1:${HTTP_PORT}/api/capabilities/ocr-flow/runtime" \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); s=p["providerStatus"]; assert s["installed"] and s["runtimeProbeOk"] and s["apiReady"]'
```

把 `docker-compose.server.yml` 的容器 healthcheck 改为 Java health 加 OCR runtime 两层门禁，runtime JSON 必须同时满足 `installed`、`runtimeProbeOk` 和 `apiReady`。healthcheck 请求 worker 进程内的 provider 状态，以复用 60 秒缓存，不在每次 Docker healthcheck 中额外冷启动 Transformers。

```yaml
healthcheck:
  test:
    - CMD-SHELL
    - >-
      curl -fsS http://127.0.0.1:8080/api/java/health >/dev/null &&
      curl -fsS http://127.0.0.1:8018/api/capabilities/ocr-flow/runtime |
      /opt/question-engine/venv/bin/python -c
      'import json,sys; s=json.load(sys.stdin)["providerStatus"];
      assert s["installed"] and s["runtimeProbeOk"] and s["apiReady"]'
  interval: 30s
  timeout: 15s
  retries: 5
  start_period: 180s
```

### Step 4：更新 delivery 必需文件并验证 shell

把 `scripts/check_mineru.py`、`scripts/test_check_mineru.py` 和后续 Task 4 的 venv 重建脚本加入 `REQUIRED_IN_PACKAGE`。

Run:

```bash
bash -n scripts/docker-entrypoint.sh
bash -n scripts/start_server_docker.sh
python3 scripts/test_check_mineru.py
docker compose -f docker-compose.server.yml config >/dev/null
python3 scripts/package_question_engine_delivery.py --check-only --include-local-platform
```

Expected: 全部通过，delivery 边界显式包含 readiness 工具。

### Step 5：提交

```bash
git add backend/python-worker/app/ocr_flow.py backend/python-worker/tests/test_ocr_flow.py Dockerfile \
  docker-compose.server.yml \
  scripts/check_mineru.py scripts/test_check_mineru.py scripts/docker-entrypoint.sh \
  scripts/start_server_docker.sh scripts/package_question_engine_delivery.py
git diff --cached --check
git commit -m "fix: gate startup on MinerU readiness"
```

## Task 4：实现服务器 MinerU venv 的原子重建与回滚

**Files:**

- Create: `scripts/rebuild_mineru_venv.py`
- Create: `scripts/test_rebuild_mineru_venv.py`
- Modify: `scripts/install_mineru.sh`
- Modify: `scripts/package_question_engine_delivery.py`
- Modify: `docs/server/RUNBOOK.md`

### Step 1：先写路径、安装命令和原子切换测试

测试不得访问网络；通过临时目录和 mock subprocess 覆盖：

```python
class AtomicMineruVenvTest(unittest.TestCase):
    def test_staging_and_backup_are_siblings_of_active_venv(self):
        paths = rebuild_mineru_venv.build_paths(Path("/srv/vendor/mineru-venv"), "20260715T120000")
        self.assertEqual(Path("/srv/vendor/mineru-venv.new-20260715T120000"), paths.staging)
        self.assertEqual(Path("/srv/vendor/mineru-venv.bak-20260715T120000"), paths.backup)

    def test_activate_moves_active_to_backup_then_staging_to_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = rebuild_mineru_venv.build_paths(Path(tmp) / "mineru-venv", "20260715T120000")
            paths.active.mkdir()
            (paths.active / "old").write_text("old", encoding="utf-8")
            paths.staging.mkdir()
            (paths.staging / "new").write_text("new", encoding="utf-8")

            rebuild_mineru_venv.activate(paths)

            self.assertEqual("new", (paths.active / "new").read_text(encoding="utf-8"))
            self.assertEqual("old", (paths.backup / "old").read_text(encoding="utf-8"))

    def test_activate_rolls_back_when_staging_rename_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = rebuild_mineru_venv.build_paths(Path(tmp) / "mineru-venv", "20260715T120000")
            paths.active.mkdir()
            (paths.active / "old").write_text("old", encoding="utf-8")
            paths.staging.mkdir()
            calls = 0

            def flaky_rename(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated activation failure")
                source.rename(target)

            with self.assertRaisesRegex(OSError, "simulated"):
                rebuild_mineru_venv.activate(paths, rename=flaky_rename)

            self.assertEqual("old", (paths.active / "old").read_text(encoding="utf-8"))
            self.assertTrue(paths.staging.is_dir())

    def test_server_install_command_never_uses_local_wheelhouse(self):
        commands = rebuild_mineru_venv.build_install_commands(
            Path("/usr/bin/python3"), Path("/srv/vendor/mineru-venv.new-1"), "3.4.2"
        )
        self.assertNotIn("--find-links", " ".join(part for command in commands for part in command))

    def test_disk_guard_requires_active_size_plus_five_gib(self):
        required = rebuild_mineru_venv.required_free_bytes(active_size=10 * 1024**3)
        self.assertEqual(15 * 1024**3, required)
```

Run:

```bash
python3 scripts/test_rebuild_mineru_venv.py
```

Expected: FAIL，因为重建模块尚不存在。

### Step 2：实现“构建—验证—原子激活”CLI

CLI 固定接受：

```text
--target /absolute/path/to/mineru-venv
--python /usr/bin/python3
--mineru-version 3.4.2
--check-script /absolute/path/to/scripts/check_mineru.py
--keep-backups 2
```

安装流程必须是：

1. 要求 target 是绝对路径，staging/backup 与 target 同父目录，以保证 rename 在同一文件系统。
2. 创建 `target.new-{UTC时间戳}`，不修改 active venv。
3. 先读取 active 目录占用量；可用空间少于“active 占用量 + 5 GiB”时拒绝构建。
4. 执行参数 `--python` 指定的解释器加 `-m venv` 创建 staging。
5. 执行 staging 解释器加 `-m pip install --upgrade pip setuptools wheel`。
6. 执行 staging 解释器加 `-m pip install "mineru[all]==3.4.2" "MarkupSafe==3.0.3"`。
7. 令 `MINERU_COMMAND` 指向 staging 的 `bin/mineru`，用 staging 解释器执行 `--check-script ... --json --skip-api`。
8. 再直接执行同解释器导入探针和 staging 的 `bin/mineru --version`，记录版本与包清单 SHA-256。
9. 只有全部成功才把 active rename 到 backup，再把 staging rename 到 active。
10. 第二次 rename 失败时立即把 backup rename 回 active。
11. 保留最近两个备份；删除更老备份前，先确认 active readiness 成功。

原子激活核心：

```python
Rename = Callable[[Path, Path], None]

def _rename(source: Path, target: Path) -> None:
    source.rename(target)

def activate(paths: BuildPaths, rename: Rename = _rename) -> None:
    moved_active = False
    try:
        if paths.active.exists():
            rename(paths.active, paths.backup)
            moved_active = True
        rename(paths.staging, paths.active)
    except BaseException:
        if moved_active and not paths.active.exists() and paths.backup.exists():
            rename(paths.backup, paths.active)
        raise
```

所有 `subprocess.run` 使用参数数组、`check=True` 和明确环境变量；不得用 `shell=True`。失败时保留 staging 供诊断，但不切换 active。

### Step 3：让现有安装入口转调原子重建

`scripts/install_mineru.sh` 保留本地开发默认目标 `backend/python-worker/.venv`；新增 `MINERU_VENV_TARGET` 时调用：

```bash
python3 scripts/rebuild_mineru_venv.py \
  --target "$MINERU_VENV_TARGET" \
  --python "${MINERU_PYTHON:-python3}" \
  --mineru-version "${MINERU_VERSION:-3.4.2}" \
  --check-script "$ROOT_DIR/scripts/check_mineru.py" \
  --keep-backups "${MINERU_KEEP_BACKUPS:-2}"
```

本地 macOS 原有 wheelhouse 路径只用于本机 `.venv`，服务器目标禁止自动引用它。

### Step 4：记录 Runbook 的恢复与回滚命令

在 `docs/server/RUNBOOK.md` 增加：

```bash
python3 scripts/rebuild_mineru_venv.py \
  --target /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv \
  --python /usr/bin/python3 \
  --mineru-version 3.4.2 \
  --check-script /home/user/AI_GENERATION_DOCKER/scripts/check_mineru.py \
  --keep-backups 2
```

回滚固定为停止容器、把 active 改名为 `.failed-{UTC时间戳}`、把指定 `.bak-*` 改回 active、运行 `check_mineru.py --skip-api`、再启动容器；不得在容器运行中切换 venv。

### Step 5：验证并提交

```bash
python3 scripts/test_rebuild_mineru_venv.py
python3 scripts/test_check_mineru.py
bash -n scripts/install_mineru.sh
python3 scripts/package_question_engine_delivery.py --check-only --include-local-platform
git add scripts/rebuild_mineru_venv.py scripts/test_rebuild_mineru_venv.py \
  scripts/install_mineru.sh scripts/package_question_engine_delivery.py docs/server/RUNBOOK.md
git diff --cached --check
git commit -m "feat: rebuild MinerU venv atomically"
```

Expected: 单元测试覆盖成功切换和失败回滚，delivery 包含重建工具。

## Task 5：本地全量静态与自动化回归

**Files:**

- Modify only on failure: tests or implementation directly responsible for the failure
- Create runtime artifact outside Git: `.artifacts/recovery/local-test-results.txt`
- Create runtime artifacts outside Git: `.artifacts/recovery/local-golden-baseline.json`, `.artifacts/recovery/local-golden-candidate.json`

### Step 1：运行全量测试矩阵

```bash
set -o pipefail
{
  ./scripts/test_python_worker.sh
  JAVA_HOME="$(/usr/libexec/java_home -v 17)" PATH="$JAVA_HOME/bin:$PATH" mvn -f backend/pom.xml test
  npm --prefix local-platform test -- --run
  npm --prefix local-platform run build
  python3 scripts/test_ocrflow_golden.py
  python3 scripts/test_benchmark_ocrflow.py
  python3 scripts/test_check_project_portability.py
  python3 scripts/test_check_ocrflow_boundaries.py
  python3 scripts/check_project_portability.py
  python3 scripts/check_ocrflow_boundaries.py
  python3 scripts/check_question_engine_contract.py
  python3 scripts/package_question_engine_delivery.py --check-only --include-local-platform
} 2>&1 | tee .artifacts/recovery/local-test-results.txt
```

Expected: 全部退出 0。任何失败都按 `systematic-debugging` 找根因，并回到 RED→GREEN→回归；不得只改断言或跳过测试。

### Step 2：运行可用的 golden replay

```bash
python3 scripts/ocrflow_golden.py capture \
  --manifest tests/ocrflow-golden/manifest.json \
  --mode replay \
  --output .artifacts/recovery/local-golden-baseline.json
python3 scripts/ocrflow_golden.py capture \
  --manifest tests/ocrflow-golden/manifest.json \
  --mode replay \
  --output .artifacts/recovery/local-golden-candidate.json
python3 scripts/ocrflow_golden.py compare \
  --baseline .artifacts/recovery/local-golden-baseline.json \
  --candidate .artifacts/recovery/local-golden-candidate.json
```

Expected: 两次独立 capture 均退出 0，输出不同文件；compare 为 equal、differenceCount 为 0。这里只验证确定性 replay 工具和 corpus 可用性，不冒充正式受控 benchmark。旧 `.artifacts/recovery/local-golden.json` 如已存在则保留，不参与本次验收。

## Task 6：本地全量启动和运行态 smoke

**Files:**

- Inspect/Modify if stale: `.run/deploy.env`
- Inspect: `.env`
- Runtime only: `.run/*.pid`, `.run/*.log`, `.run/deploy.env`

### Step 1：清理陈旧 PID 并按仓库脚本启动

先确认没有占用目标端口的非本项目进程：

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN || true
lsof -nP -iTCP:8019 -sTCP:LISTEN || true
lsof -nP -iTCP:5174 -sTCP:LISTEN || true
./scripts/stop_local.sh || true
./scripts/deploy_local.sh --with-mineru
```

Expected: worker `8001`、Java `8019`、前端 `5174` 均监听；`.run/deploy.env` 与实际端口一致。若本机资源不允许真实 MinerU OCR，仍须完成 provider 深度 readiness，并在验收记录中明确该限制；服务器 OCR smoke 不能省略。

### Step 2：逐层检查健康和业务路径

```bash
curl -fsS http://127.0.0.1:8001/api/health
curl -fsS http://127.0.0.1:8019/api/java/health
curl -fsS http://127.0.0.1:8019/api/capabilities/ocr-flow/runtime
curl -fsS http://127.0.0.1:5174/
AI_GENERATION_BASE_URL=http://127.0.0.1:8019 python3 scripts/smoke_import_file_types.py
AI_GENERATION_BASE_URL=http://127.0.0.1:8019 \
  AI_GENERATION_FRONTEND_URL=http://127.0.0.1:5174 \
  PYTHON_WORKER_URL=http://127.0.0.1:8001 \
  python3 scripts/smoke_deploy_basic.py
AI_GENERATION_BASE_URL=http://127.0.0.1:8019 \
  AI_GENERATION_FRONTEND_URL=http://127.0.0.1:5174 \
  python3 scripts/smoke_local_platform_business.py
AI_GENERATION_BASE_URL=http://127.0.0.1:8019 python3 scripts/smoke_ocr.py
```

Expected: 基础、文件类型、本地平台业务和 OCR smoke 全部通过；runtime JSON 中 `installed=true`、`runtimeProbeOk=true`。AI smoke 只在 `.env` 有可用 provider 凭据时执行：

```bash
AI_GENERATION_BASE_URL=http://127.0.0.1:8019 python3 scripts/smoke_ai.py
```

### Step 3：检查日志和停止本地服务

```bash
rg -n "Traceback|ERROR|Exception|Address already in use|cannot import" .run/*.log || true
./scripts/stop_local.sh
for port in 8001 8019 5174; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN; then exit 1; fi
done
```

Expected: 无未解释的错误；停止后端口释放。发现错误必须先修复并重跑本 Task。

## Task 7：生成不可变交付包并在服务器做备份/预检

**Files:**

- Create outside Git: `dist/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY.tar.gz`
- Create outside Git: `dist/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY_MANIFEST.json`
- Server staging: `$HOME/releases/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY/`
- Server backup pattern: `$HOME/backups/AI_GENERATION_DOCKER_{UTC时间戳}/`

### Step 1：生成不含 macOS wheelhouse 的 release

```bash
python3 scripts/package_question_engine_delivery.py \
  --release-name AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY \
  --include-local-platform
shasum -a 256 \
  dist/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY.tar.gz \
  dist/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY_MANIFEST.json
tar -tzf dist/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY.tar.gz \
  | rg '^vendor/mineru-wheelhouse/' && exit 1 || true
```

Expected: package 校验通过，archive 不含本机 wheelhouse、`.env`、storage、模型或密钥。

### Step 2：上传到 staging，凭据只交互输入

```bash
ssh -p 3322 user@120.211.112.121 'mkdir -p "$HOME/releases/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY"'
scp -P 3322 \
  dist/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY.tar.gz \
  dist/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY_MANIFEST.json \
  user@120.211.112.121:releases/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY/
```

### Step 3：服务器只读预检和持久数据备份

进入交互 SSH 后执行：

```bash
set -euo pipefail
cd /home/user/AI_GENERATION_DOCKER
release="$HOME/releases/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$HOME/backups/AI_GENERATION_DOCKER_${stamp}"
mkdir -p "$backup"
cp -a .env "$backup/.env"
cp -a docker-compose.server.yml "$backup/docker-compose.server.yml"
rsync -a \
  --exclude '.env' \
  --exclude 'server-data/' \
  --exclude 'vendor/' \
  --exclude 'backend/target/' \
  --exclude 'local-platform/node_modules/' \
  ./ "$backup/app/"
printf '%s\n' "$backup" > "$release/BACKUP_PATH"
sudo docker inspect ai_generation_docker-question-engine-1 > "$backup/container-inspect.json"
sudo docker image inspect ai_generation_docker-question-engine > "$backup/image-inspect.json" 2>/dev/null || true
find "$backup" -maxdepth 2 -type f -print0 | sort -z | xargs -0 sha256sum > "$backup/SHA256SUMS"
df -h "$HOME"
du -sh server-data vendor/mineru-venv
sudo docker compose -f docker-compose.server.yml ps
curl -fsS http://127.0.0.1:8018/api/java/health
curl -fsS http://127.0.0.1:8018/api/import-tasks/import_task_20260715_065444_e0d1c55f
command -v mvn
command -v npm
command -v rsync
```

Expected: 环境、应用代码、容器/镜像元数据备份完成，任务仍为可重试失败状态；`BACKUP_PATH` 精确记录本轮备份目录。此时不复制运行中的 H2/任务状态；一致性 server-data 归档在停服后的 Task 8 Step 2 完成。若剩余空间不足以容纳一份 server-data 压缩归档和一份新 venv，不删除 active、模型或 server-data，先停止执行并调整备份介质。

## Task 8：在服务器原子修复 MinerU、部署应用并完成全量验收

**Files:**

- Server active app: `/home/user/AI_GENERATION_DOCKER`
- Server active venv: `/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv`
- Server model cache: existing host model cache, preserved
- Server data: `/home/user/AI_GENERATION_DOCKER/server-data`, preserved

### Step 1：解压 staging 并校验交付物

```bash
set -euo pipefail
release="$HOME/releases/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY"
rm -rf "$release/extracted"
mkdir -p "$release/extracted"
tar -xzf "$release/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY.tar.gz" -C "$release/extracted"
python3 "$release/extracted/scripts/package_question_engine_delivery.py" --check-only --include-local-platform
```

`rm -rf` 仅允许作用于本次 release 下已知的 `extracted` 临时目录，禁止指向 active app、vendor 或 server-data。

### Step 2：停止应用并在 active 路径旁构建新 venv

```bash
cd /home/user/AI_GENERATION_DOCKER
sudo docker compose -f docker-compose.server.yml stop question-engine
release="$HOME/releases/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY"
backup="$(cat "$release/BACKUP_PATH")"
test -d "$backup/app"
tar -czf "$backup/server-data.tar.gz" server-data
sha256sum "$backup/server-data.tar.gz" >> "$backup/SHA256SUMS"
python3 "$release/extracted/scripts/rebuild_mineru_venv.py" \
  --target /home/user/AI_GENERATION_DOCKER/vendor/mineru-venv \
  --python /usr/bin/python3 \
  --mineru-version 3.4.2 \
  --check-script "$release/extracted/scripts/check_mineru.py" \
  --keep-backups 2
MINERU_COMMAND=/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/mineru \
  python3 "$release/extracted/scripts/check_mineru.py" --json --skip-api
```

Expected: 新 venv 深度探针通过；`markupsafe.Markup`、Jinja2、Transformers 和 MinerU import 均成功；旧 venv 保留为 `.bak-*`。如果安装或验证失败，容器保持停止，active venv 不变或已自动回滚。

### Step 3：同步应用代码，显式排除状态和环境

```bash
rsync -a --delete \
  --exclude '.env' \
  --exclude 'server-data/' \
  --exclude 'vendor/' \
  --exclude 'backend/target/' \
  --exclude 'local-platform/node_modules/' \
  "$release/extracted/" /home/user/AI_GENERATION_DOCKER/
cd /home/user/AI_GENERATION_DOCKER
test -f .env
test -x vendor/mineru-venv/bin/mineru
test -d server-data
```

Expected: 代码更新但 `.env`、server-data 和新 venv 保持不变。

### Step 4：构建并启动容器

```bash
cd /home/user/AI_GENERATION_DOCKER
JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}" mvn -f backend/pom.xml clean -DskipTests package
npm --prefix local-platform ci
npm --prefix local-platform run build
sudo docker compose -f docker-compose.server.yml up -d --build question-engine
sudo docker compose -f docker-compose.server.yml ps
sudo docker compose -f docker-compose.server.yml logs --tail=200 question-engine
```

Expected: 容器只能在 MinerU preflight 和 API readiness 成功后进入运行态；日志中不再出现 `cannot import name 'Markup'`。

### Step 5：基础和 OCR 小样 smoke

```bash
cd /home/user/AI_GENERATION_DOCKER
curl -fsS http://127.0.0.1:8018/api/capabilities/ocr-flow/runtime \
  | python3 -m json.tool
curl -fsS http://127.0.0.1/
sudo docker exec ai_generation_docker-question-engine-1 \
  curl -fsS http://127.0.0.1:8000/api/health
AI_GENERATION_BASE_URL=http://127.0.0.1:8018 \
  vendor/mineru-venv/bin/python scripts/smoke_ocr.py
```

Expected: runtime 显示 `installed=true`、`runtimeProbeOk=true`，API readiness 成功；生成的小图片 OCR 任务成功。

### Step 6：重试原任务 123，并等待同一任务完成

```bash
curl -fsS -X POST \
  http://127.0.0.1:8018/api/import-tasks/import_task_20260715_065444_e0d1c55f/retry \
  | python3 -m json.tool
```

然后每 15 秒读取：

```bash
curl -fsS http://127.0.0.1:8018/api/import-tasks/import_task_20260715_065444_e0d1c55f \
  | python3 -m json.tool
```

最多等待 30 分钟。成功标准：

- import task 状态为成功；
- 原 OCR job `ocr_20260715_065444_6f78252a` 被复用，`retryCount` 增加；
- `error`/`failureReason` 清空；
- `questions` 数量大于 0；
- 源文件 preview 和至少一条题目读取接口返回 200。

若失败，先保存任务 JSON、OCR job JSON、容器日志和 `nvidia-smi`；只在查明新根因并补测试后再次 retry。

### Step 7：服务器全量运行态测试

```bash
cd /home/user/AI_GENERATION_DOCKER
AI_GENERATION_BASE_URL=http://127.0.0.1:8018 \
  vendor/mineru-venv/bin/python scripts/smoke_import_file_types.py
AI_GENERATION_BASE_URL=http://127.0.0.1:8018 \
  AI_GENERATION_FRONTEND_URL=http://127.0.0.1 \
  vendor/mineru-venv/bin/python scripts/smoke_local_platform_business.py
AI_GENERATION_BASE_URL=http://127.0.0.1:8018 \
  vendor/mineru-venv/bin/python scripts/smoke_ai.py
sudo docker compose -f docker-compose.server.yml logs --since=30m question-engine \
  | rg -n "Traceback|ERROR|Exception|cannot import|CUDA out of memory" || true
nvidia-smi
nvidia-smi pmon -c 1
curl -fsS http://127.0.0.1:8018/api/java/health
curl -fsS http://127.0.0.1:8018/api/java/worker
curl -fsS http://127.0.0.1:8018/api/capabilities/ocr-flow/runtime
```

Expected: 全部 smoke 通过；MinerU 使用约定的 GPU 0，现有 vLLM 保持在 GPU 1；没有新的依赖导入、OOM 或任务编排错误。AI smoke 若受外部 provider 凭据/额度影响，必须保存明确响应并单列为外部依赖，不能伪报通过。

### Step 8：失败回滚路径

只有 Task 8 任一生产门禁失败时执行：

```bash
set -euo pipefail
cd /home/user/AI_GENERATION_DOCKER
sudo docker compose -f docker-compose.server.yml stop question-engine
release="$HOME/releases/AI_GENERATION_TOGO_20260715_PRODUCTION_RECOVERY"
backup="$(cat "$release/BACKUP_PATH")"
test -d "$backup/app"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
old_venv="$(find "$PWD/vendor" -maxdepth 1 -type d -name 'mineru-venv.bak-*' -print | sort | tail -n 1)"
test -n "$old_venv"
test -x "$old_venv/bin/mineru"
mv vendor/mineru-venv "vendor/mineru-venv.failed-${stamp}"
mv "$old_venv" vendor/mineru-venv
cp -a "$backup/.env" .env
rsync -a --delete \
  --exclude '.env' --exclude 'server-data/' --exclude 'vendor/' \
  "$backup/app/" /home/user/AI_GENERATION_DOCKER/
JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}" mvn -f backend/pom.xml clean -DskipTests package
npm --prefix local-platform ci
npm --prefix local-platform run build
MINERU_COMMAND=/home/user/AI_GENERATION_DOCKER/vendor/mineru-venv/bin/mineru \
  python3 scripts/check_mineru.py --json --skip-api
sudo docker compose -f docker-compose.server.yml up -d --build question-engine
```

若自动选择的最新 backup venv 不是本轮重建产生的备份，停止并依据验收记录选择精确目录，不能猜测。默认不自动恢复 `server-data.tar.gz`，以免覆盖部署后新写入；它只用于经批准的数据恢复。若旧 venv 本身就是已知损坏状态，则应用代码可回滚，但 OCR 仍保持停用并在报告中明确，不能把损坏 venv 说成健康回滚。

## Task 9：按证据同步计划状态和运维/验收文档

**Files:**

- Modify: `docs/superpowers/plans/2026-07-14-ocr-provider-postprocess-decoupling.md`
- Modify: `docs/superpowers/plans/2026-07-14-ocr-flow-modularization-and-portability.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/server/CHANGELOG.md`
- Modify: `docs/server/RUNBOOK.md`
- Modify: `docs/delivery/ACCEPTANCE.md`
- Create: `docs/delivery/PRODUCTION_RECOVERY_ACCEPTANCE_20260715.md`

### Step 1：建立“勾选项—证据”审计表

逐个读取两个计划中的 checkbox；每项只允许以下状态：

- `[x]`：有提交、文件和本轮测试/运行证据三者之一或组合足以直接证明。
- `[ ]`：尚未完成、只完成部分，或正式门禁因受控 baseline/真实样卷/预发观察周期缺失而不能证明。
- `[ ]` 后追加 `Blocked:` 或 `Partial:`：说明缺失证据，不改变原任务含义。

审计命令：

```bash
rg -n '^\s*- \[[ xX]\]' docs/superpowers/plans/2026-07-14-ocr-provider-postprocess-decoupling.md
rg -n '^\s*- \[[ xX]\]' docs/superpowers/plans/2026-07-14-ocr-flow-modularization-and-portability.md
git log --oneline --decorate --all --since=2026-07-01
```

禁止把 provider 计划从 0/18 机械改成 18/18，也禁止把模块化计划从 0/215 机械改成 215/215。特别是需要以下证据的项保持未完成：20 份受控真实样卷、正式 benchmark baseline、预发观察周期、真实 MQ、超时扫描器、权限/版本/审核、正式 SDK 发布包。

### Step 2：写生产恢复验收报告

`PRODUCTION_RECOVERY_ACCEPTANCE_20260715.md` 必须包含实际值，而非模板占位：

- Git 分支和最终 commit SHA；
- 本地 Python/Java/前端测试计数；
- 本地端口、health、runtime 和 smoke 结果；
- delivery 文件名、manifest、SHA-256；
- 服务器旧/新 MinerU、MarkupSafe、Jinja2、Transformers 版本；
- venv backup 路径和回滚命令；
- 小样 OCR task/job ID 与结果；
- 原任务 123 的 task/job ID、retryCount、questionCount 和最终状态；
- 日志扫描结果和 GPU 分配；
- 未完成项及原因，尤其是受控 benchmark baseline 和六个后续子项目。

### Step 3：更新运维和交付文档

- `docs/CHANGELOG.md`：记录深度 readiness、原子 venv rebuild、本地/服务器验收。
- `docs/server/CHANGELOG.md`：记录服务器根因、恢复版本和备份路径。
- `docs/server/RUNBOOK.md`：保留 Task 4 的构建/回滚/检查命令。
- `docs/delivery/ACCEPTANCE.md`：把 `runtimeProbeOk`、小样 OCR 和既有失败任务 retry 加入 OCR 交付门禁。

### Step 4：验证文档事实并提交

```bash
rg -n "0/18|0/215|pending-controlled-baseline|runtimeProbeOk|import_task_20260715_065444_e0d1c55f" docs
git diff --check
git diff -- docs/superpowers/plans docs/CHANGELOG.md docs/server docs/delivery
git add docs/superpowers/plans/2026-07-14-ocr-provider-postprocess-decoupling.md \
  docs/superpowers/plans/2026-07-14-ocr-flow-modularization-and-portability.md \
  docs/CHANGELOG.md docs/server/CHANGELOG.md docs/server/RUNBOOK.md \
  docs/delivery/ACCEPTANCE.md docs/delivery/PRODUCTION_RECOVERY_ACCEPTANCE_20260715.md
git diff --cached --check
git commit -m "docs: record production recovery evidence"
```

Expected: 计划状态与证据一致，未完成生产范围仍明确可见。

## Task 10：最终新鲜验证与交付判定

**Files:**

- Verify: all modified files
- Verify: `docs/delivery/PRODUCTION_RECOVERY_ACCEPTANCE_20260715.md`

### Step 1：执行最终自动化验证

```bash
./scripts/test_python_worker.sh
JAVA_HOME="$(/usr/libexec/java_home -v 17)" PATH="$JAVA_HOME/bin:$PATH" mvn -f backend/pom.xml test
npm --prefix local-platform test -- --run
npm --prefix local-platform run build
python3 scripts/test_ocrflow_golden.py
python3 scripts/test_benchmark_ocrflow.py
python3 scripts/test_check_project_portability.py
python3 scripts/test_check_ocrflow_boundaries.py
python3 scripts/test_check_mineru.py
python3 scripts/test_rebuild_mineru_venv.py
python3 scripts/check_question_engine_contract.py
python3 scripts/package_question_engine_delivery.py --check-only --include-local-platform
bash -n scripts/docker-entrypoint.sh scripts/start_server_docker.sh scripts/install_mineru.sh
git diff --check
git status --short
```

Expected: 所有自动化验证退出 0；`git status` 仅显示明确解释的运行产物或为空。

### Step 2：再次检查服务器最终状态

```bash
ssh -p 3322 user@120.211.112.121
```

进入后执行：

```bash
cd /home/user/AI_GENERATION_DOCKER
sudo docker compose -f docker-compose.server.yml ps
curl -fsS http://127.0.0.1:8018/api/java/health
curl -fsS http://127.0.0.1:8018/api/capabilities/ocr-flow/runtime | python3 -m json.tool
curl -fsS http://127.0.0.1:8018/api/import-tasks/import_task_20260715_065444_e0d1c55f | python3 -m json.tool
sudo docker compose -f docker-compose.server.yml logs --since=10m question-engine \
  | rg -n "Traceback|ERROR|Exception|cannot import|CUDA out of memory" || true
```

Expected: 容器稳定、health 和 runtime 正常、任务 123 成功且问题数大于 0、最近日志无未解释错误。

### Step 3：最终交付结论

只有以下全部满足，才可表述为“生产恢复完成”：

- 本地自动化、构建和运行态 smoke 通过；
- 服务器 MinerU runtime/API readiness 通过；
- 小样 OCR 通过；
- 原任务 123 retry 成功且 questionCount > 0；
- 服务器全量 smoke、日志和 GPU 检查通过；
- 回滚资产存在并已记录；
- 计划状态按证据同步。

最终措辞仍必须区分：本阶段是“生产运行态恢复并验收完成”；权限、版本、审核、MQ、扫描器、正式 SDK，以及依赖受控 baseline/真实样卷/观察周期的正式生产门禁，继续作为独立后续项目，不能宣称整个 215 项模块化计划已经完成。
