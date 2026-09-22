# 11｜开发、部署、运行与排错

## 两种用户不能混淆
开发者：需要 Python、Node 和构建 sidecar 所需的 Go；具体兼容版本由 T00 根据真实依赖选择并锁定。
普通使用者：下载对应 Windows x64 发布包、启动 TravelAgent、用表单完成首次设置。不要求安装 Python/Node/Go/Docker。不能用“开发环境能跑”替代发行包验收。

## 当前包能运行的命令
```text
python -m pip install -r tools/requirements-docs.txt
python tools/validate_pack.py
```
此命令校验文档引用、契约、合成夹具和数据库草案，不运行应用。

## 待 T00/T01 创建的命令契约
```text
python scripts/dev.py --mode mock
python scripts/doctor.py
python scripts/check.py --suite unit
python scripts/check.py --suite contract
python scripts/check.py --suite integration
python scripts/check.py --suite security
python scripts/check.py --suite e2e
```

T00/T01 已提供以上开发脚本，结果见对应实现报告。先 `uv sync --locked`，在 apps/web 执行 `pnpm install --frozen-lockfile`、`pnpm build`。当前锁定 Python 3.14；其他 Python 小版本尚未验证。e2e 尚无测试时返回退出码 5 并标 SKIPPED。sidecar go.sum 留待 T02，不伪造上游构建结果。

## 默认配置
`config/defaults.json` 是配置契约。运行配置从受控用户目录加载；任何 key 不放 defaults。能力状态区分 UNCONFIGURED、CONFIGURED_UNVERIFIED、VERIFIED、FAILED、UNSUPPORTED。

模型可配置支持结构化输出/工具调用的国内可用服务或本地服务。先实现统一适配与 mock；通过一组能力探测后才能标 VERIFIED，不由模型名称推断一定兼容。官方资料搜索同样走适配器，不硬编码一个尚未取得 key 的服务为可用。

高德需要本人的合适 key 和适用许可。地图 key 和服务端 secret 区分；客户端需要的 key按厂商规则限制来源，服务端 key 不进入网页。坐标系以供应商返回和入口协议为准，不把 WGS84 与 GCJ02 混用。路线字段按官方文档实测。[S17]

报价接口先提供 Protocol 与 UNSUPPORTED 退路，至少接通一个有凭证的供应商再显示真实报价。艺龙 hotel.detail 只是候选官方能力，不代表当前项目已经拥有调用资格；机票、火车票另行验收，禁止从酒店 API 臆造同格式出票接口。[S18]

## 本地启动与监督
launcher 检查端口、数据库版本、资源目录和 OS secret store；启动 API、worker、裁剪 sidecar；打开本地浏览器。启动清单与实际进程 PID 记录在受限运行目录，退出时只关闭拥有的子进程。

健康检查不触达小红书。启动时不自动搜索热门内容，不轮询维持登录。休眠、断网、关机恢复按任务 lease 和 generation 决定，不假设进程始终在线。

## Windows 发行包
建议 PyInstaller one-folder 作为首个包装验证方向，打包 Python backend/launcher 和已构建前端，sidecar 作为锁定版本二进制。[S19] 这是构建方案，未测试成功；按目标 OS 构建与验证，不把 Linux 打包结果称为 Windows 可执行发布包。

普通用户浏览器选项：受支持的本机浏览器路径由程序检测并让用户确认，或在许可允许时附带/安装经过校验的浏览器资源。未下载资源时显示进度和大小；网络失败提供明确错误，不隐藏自动下载的环境要求。

上游二进制、浏览器资源、运行时和依赖均须来源/校验/许可检查。先做未签名内部预览包可以，但发布页必须如实说明签名状态；不能让用户关闭杀毒软件才能运行。

## 数据迁移
数据库有 schema_version；迁移前备份允许保存的数据，迁移失败不继续启动 worker。只增量修改，不对已有数据库执行整份初始 SQL 重建。备份不含 profile、token、原始受限内容；通过 source policy 控制其他数据。

## 故障表
| 现象 | 检查与处理 |
|---|---|
| 页面打不开 | 本地端口/子进程/同源校验，不改为公网监听 |
| 二维码空白或过期 | 当前 session/generation、timeout、图片权限；人工刷新一次 |
| 手机上确认了但未连接 | cookie 保存事件、一次核实结果、写入权限；不无限刷 status |
| “搜索失败”但不知原因 | 查看结构化错误码，区分验证/网络/解析/无结果 |
| 第二轮访问次数突然变多 | 会话预算、去重键、checkpoint 重放、上游隐式重试 |
| RAG 查不到刚研究内容 | 检查是否允许保存、入库状态、embedding 模型/维度，不能自动放宽权限 |
| 地图/票价空白 | 配置和授权状态、时间条件，明确未知而非编默认值 |
| 重启后旧结果覆盖新结果 | revision/generation 过滤与幂等结果应用检查 |

## 诊断导出
仅导出版本、OS 类别、匿名错误码、计数、门禁状态和脱敏配置。默认不包含具体地址、搜索词、笔记正文、账号ID、密钥、URL查询参数。导出前给预览。
