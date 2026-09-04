# 架构与入口

## 分层

```text
数据源 / Provider 插件
  -> 同步、校验、标准化服务
  -> DataStore / KlineRepository / Parquet
  -> enriched 指标流水线
  -> 策略、监控、回测、分析服务
  -> FastAPI API / SSE
  -> 前端 API 类型 + TanStack Query
  -> 页面与共享组件
```

- `backend/app/main.py` 创建 FastAPI 应用，管理生命周期、路由与后端扩展装载。
- `backend/app/api/` 负责 HTTP/SSE、参数校验和响应映射；重计算与数据源专属逻辑应留在服务/领域层。
- `backend/app/services/` 负责编排同步、实时行情、通知等跨领域用例。
- `backend/app/tickflow/` 与 `backend/app/data_providers/` 构成数据访问边界；上层依赖统一能力和标准字段。
- `frontend/src/router.tsx` 汇集页面路由；`lib/api.ts` 与 `lib/queryKeys.ts` 是前端数据契约和缓存键的入口。

## 静态检索起点

| 问题 | 先定位 |
| --- | --- |
| 应用启动、依赖实例、路由装载 | `main.py` 的 `lifespan`、应用对象与路由引用 |
| API 到业务层 | API endpoint 的引用和其调用服务 |
| Provider 能力/数据路由 | `data_providers/registry.py`、`capabilities.py`、`base.py` 的符号与实现 |
| 前端页面数据链 | 路由页面、`lib/api.ts` 对应请求、`queryKeys.ts` 与共享 Query hook |

高冲突接线点：`backend/app/main.py`、`backend/app/strategy/engine.py`、`backend/app/backtest/engine.py`、`frontend/src/router.tsx`、`frontend/src/components/Layout.tsx`、`frontend/src/lib/api.ts`、`frontend/src/lib/queryKeys.ts`。它们不是默认修改位置；先查已有扩展点和调用链。
