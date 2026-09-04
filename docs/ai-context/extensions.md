# 二开与扩展边界

扩展的唯一完整规范是 [`../secondary-development.md`](../secondary-development.md)。本页只提供任务入口，避免重复维护细节。

- 数据源：从 `backend/app/data_providers/` 与 `backend/app/plugins/` 开始，先确认数据集契约、能力声明与隔离测试。
- 后端扩展：`backend/app/extensions/` 与 `backend/app/custom/`。已实现的稳定继承点为 `NotificationFormatter`；不要根据设计示例假设其他策略接口存在。
- 前端扩展：`frontend/src/extensions/` 与 `frontend/src/custom/`。现有开放插槽为 `layout.navigation.extra`、`stock-preview.footer`、`watchlist.toolbar`；完整页面使用已实现的路由/导航注册。

每次二开先用 Serena 查声明、实现、注册点和测试，判断 L1（配置/策略/扩展数据）、L2（既有注册/插槽/接口）或 L3（核心源码）。新扩展点只为已确认的真实需求新增，保持失败隔离和默认行为不变。
