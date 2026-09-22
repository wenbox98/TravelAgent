# XHS upstream provenance｜T02

## 固定参考

- Repository：`https://github.com/xpzouying/xiaohongshu-mcp`
- Commit：[`8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff`](https://github.com/xpzouying/xiaohongshu-mcp/commit/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff)
- 提交时间：2026-09-22T14:31:32+08:00；设计审查时远端HEAD/main与本地checkout一致，本轮继续使用明确批准的固定SHA，不自动升级。
- upstream LICENSE文件为Apache-2.0；本项目尚未选择许可证。本次没有vendored upstream源码，不宣称已经完成发行许可证审查。

## 实际复用和修改

**复制的upstream实现文件：0；修改的upstream文件：0；运行的upstream二进制：0。** T02采用独立Python实现；不导入Go MCP、headless_browser、CloakBrowser、humanize或其浏览器下载器。不存在需发布的upstream patchset，所以patchset_sha256保持null；这不是遗漏补丁hash。

| upstream参考 | 本项目实现 | 复用/差异及原因 |
|---|---|---|
| xiaohongshu/search.go:FilterOption | integrations/xhs-sidecar/xhs_sidecar/models.py:SearchFilters | 参照固定枚举；新增requested/applied/status，避免筛选未知冒充已生效 |
| types.go / xiaohongshu/types.go | models.py:SourceIdentity、AccessLocator、Candidate、RawDetail | 参照note ID/token关系；独立定义严格类型，凭证不进入公共响应 |
| feed_detail.go | completeness.py:classify_completeness | 没有复用页面抓取代码；HTTP200不证明全文，按文本范围证据保守分类 |
| browser/browser.go、service.go | browser.py:BrowserManager、service.py:SidecarService | 新建普通浏览器生命周期抽象与Fake；无指纹、无真实启动，复用同一会话 |
| routes.go、middleware.go | app.py:create_app、redaction.py | 独立只读路由注册、强制本机鉴权、日志字段白名单；没有隐藏/配置关闭的写工具 |
| 原上游无研究网络计量契约 | observability.py | 导航与HTTP类别分离；NOT_MEASURED/null和SIMULATED，不伪造真实请求数 |

上述为行为/接口参考，不是兼容整个upstream REST响应或二进制。当前也没有把本服务接入TravelResearchService；该业务循环仍未实现。

## 后续同步流程

1. 操作者显式选择新候选SHA，先与当前锁比较README及登录、browser/session、search/detail相关文件，不自动跟随main/latest。
2. 记录接口/页面结构差异；只把必要变更映射到本项目类型与未来受控页面读取，不merge完整Go服务。
3. 同步内部OpenAPI、来源/筛选/完整度语义、脱敏合成夹具、测试和本记录；核实没有引入写路由或反检测依赖。
4. 先跑全部离线门禁。真实连接另行明确授权；通过Fake测试不改变G0状态。
5. 若未来复制实现代码，新增逐文件来源、许可/NOTICE及实际改动记录；若发布构建，再记录真实平台、产物hash和签名状态。当前没有浏览器/sidecar发行产物，artifact_sha256为null、approved_for_release=false。

历史发现保留于 [PoC上游分析](xhs-poc-analysis.md)；机器记录见 [upstream-lock](../../contracts/upstream-lock.json)。
