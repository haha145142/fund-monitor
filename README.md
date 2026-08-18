# 我的板块资金监控 V2

这是手机 PWA + Python 后端。手机每30秒请求 `/api/market`；后端缓存约20秒，并从东方财富公开行情接口获取指数和行业板块数据。

## 最简单部署
服务器安装 Docker 后：
`docker build -t fund-monitor .`
`docker run -d --restart unless-stopped -p 8080:8080 --name fund-monitor fund-monitor`

然后手机打开 `http://服务器IP:8080`，浏览器菜单选择“添加到主屏幕”。

## 注意
公开行情接口不是官方商业授权 API，可能限流、变更或短时不可用。程序有3次重试和旧数据兜底。正式长期使用建议配置 HTTPS 和域名。
