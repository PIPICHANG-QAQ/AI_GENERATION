# Local Platform

本目录是本地演示小平台前端，用于验证题目加工能力闭环。

公司教育生态平台对接时，不应直接依赖本目录页面代码；推荐对接 `backend` 暴露的 `/api/capabilities`、`/api/engine`、`question-package.v1` 和 `question-engine/sdk`。

如果要理解本地页面如何作为 question-engine 的 example 使用，请阅读 `../docs/LOCAL_PLATFORM_AS_EXAMPLE.md`。正式 SDK 使用方式见 `../question-engine/sdk/USAGE.md`。

## 本地启动

```bash
npm install
VITE_API_BASE=http://localhost:8018 npm run dev -- --host 0.0.0.0
```
