# 14｜来源与事实核实状态

核查日：2026-09-22。所有外部事实按此观察时点记录。链接用于开发者复核；不将未来变化写成静态保证。

## S01｜xiaohongshu-mcp README

来源：<https://github.com/xpzouying/xiaohongshu-mcp>

状态：**已读取项目说明**。能力自述不等于平台认可；未复述其免封/稳定性宣传。

## S02｜候选基线 commit

来源：<https://github.com/xpzouying/xiaohongshu-mcp/commit/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff>

状态：**设计审查以git ls-remote与本地源码核对**。提交2026-09-22；T02固定为reference，不代表已验收构建。详见[provenance](architecture/xhs-upstream-provenance.md)。

## S03｜routes.go

来源：<https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/routes.go>

状态：**已读源码**。用于只读路径白名单。

## S04｜service.go

来源：<https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/service.go>

状态：**已读登录/search/detail相关源码**。每次读取新建浏览器，二维码后台保存不等于完整生命周期管理。

## S05｜login_session.go

来源：<https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/login_session.go>

状态：**已读源码**。取消旧waiter的登记管理，不保证创建前幂等或阻止旧Cookie提交。

## S06｜feed_detail.go

来源：<https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/xiaohongshu/feed_detail.go>

状态：**已读只读执行路径**。含token日志、评论开关、默认值和重试问题见架构审查；T02没有复制该读取实现。

## S07｜handlers_api.go

来源：<https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/handlers_api.go>

状态：**已读登录/搜索/详情处理源码**。请求封装与错误处理。

## S08｜LangGraph interrupts

来源：<https://docs.langchain.com/oss/python/langgraph/interrupts>

状态：**已读官方文档**。中断恢复与节点重执行。

## S09｜LangGraph persistence

来源：<https://docs.langchain.com/oss/python/langgraph/persistence>

状态：**已读官方文档**。检查点能力，不等于网络操作 exactly-once。

## S10｜SQLite FTS5

来源：<https://www.sqlite.org/fts5.html>

状态：**已读官方文档**。全文索引；中文预分词是本项目设计。

## S11｜search.go

来源：<https://github.com/xpzouying/xiaohongshu-mcp/blob/8eae4eb22ca1135e53f3e2da6c449fdfe5b492ff/xiaohongshu/search.go>

状态：**已读搜索源码**。筛选枚举、候选字段及超时可能返回旧结果；T02仅参考枚举/字段。

## S12｜历史 issue #599

来源：<https://github.com/xpzouying/xiaohongshu-mcp/issues/599>

状态：**已读用户缺陷报告**。历史案例，不判定当前版本必现。

## S13｜历史 issue #681

来源：<https://github.com/xpzouying/xiaohongshu-mcp/issues/681>

状态：**已读用户缺陷报告**。额外登录验证案例，不作为绕过建议。

## S14｜小红书账号平台 quick start

来源：<https://openaccount.xiaohongshu.com/docs/quick-start>

状态：**本次获取超时，未核实**。不能断言官方 scope、OAuth 开放范围或全站搜索可用。

## S15｜高德开放平台服务协议

来源：<https://lbs.amap.com/pages/terms/>

状态：**已读官方页面**。实际存储、派生和模型用途按适用许可确认。

## S16｜OSI Open Source Definition

来源：<https://opensource.org/osd>

状态：**已读定义**。用途限制与开放源代码定义的区别。

## S17｜高德路径规划2.0

来源：<https://lbs.amap.com/api/webservice/guide/api/newroute>

状态：**已读官方API文档**。无本项目key，未调用实测。

## S18｜艺龙 hotel.detail

来源：<https://open.elong.com/doc/info/cn-api-search-hotel_detail>

状态：**已读官方API文档**。仅候选酒店能力，无凭证未实测。

## S19｜PyInstaller operating mode

来源：<https://pyinstaller.org/en/stable/operating-mode.html>

状态：**已读官方文档**。发行包装方向，不代表Windows构建已通过。

## 本次未完成的事项

未使用真实小红书账号；未跑真实搜索/详情/图像读取；未验证反爬触发概率；未取得或调用旅行供应商凭证；未在 Windows 构建/运行发行包。没有完整审计整个上游仓库及所有依赖。本包只审查列明的源码入口，不能称“上游全部安全”。

本包的预算、权重、性能容量、精确率目标、文件目录和 API 是设计决定。它们不是从平台规则推导出的保证值。Codex 应在实现报告中新增实际依赖版本、真实响应契约和实测结果，不能修改历史报告把未运行改成通过。
