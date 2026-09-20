# 文档归档索引

## 理论与口径

- `theory/sector-rs/`：Sector Strength、Relative Strength 的冻结定义与 DTO。
- `theory/volume-profile/`：Volume Profile 参考实现学习和算法设计。
- `strategy/`：既有 Wyckoff、CZSC、ICT 及跨策略理论文档。该目录保留为稳定入口，供项目开发规范和既有链接使用。

## 实现

- `implementation/volume-profile/`：分钟 VP V1、Batch/Cache 性能与工程约束。
- `ai-context/`：架构、数据契约、扩展点和 AI 开发导航。

## 回测与研究

- `research/sector-rs/`：Sector/RS 的独立验证、描述正确性、NARROWING 与 Sector/RS+VP 研究。
- `research/volume-profile/`：VP-first 五日分析、Extension 修复后的历史回填研究。
- `research/wyckoff/`：Wyckoff 候选池内的 Sector/RS 对照回测。

## 审计

- `audits/`：数据/实现审计、候选池链路复核和历史正确性审阅。

## 运行与部署

根目录保留 `configuration.md`、`deployment.md`、`deploy-password.md`、`custom-data-source.md`、
`plugin-development.md` 等操作文档；`examples/` 与 `czscEvent/` 保留示例和第三方使用材料。
