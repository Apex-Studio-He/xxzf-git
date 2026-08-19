# Security policy / 安全策略

## 支持范围

安全修复只面向默认分支的最新源码。仓库不分发官方安装包，也不运营公共 XXZF 服务；每个部署者负责自己的域名、TLS、服务器、证书、密钥、备份和客户端发布。

## 报告漏洞

请使用 GitHub 仓库的 **Private vulnerability reporting**，不要在公开 issue 中发布可利用细节、真实服务器地址、通知内容、设备 ID、Bark Key、token、证书或私钥。如果私密报告功能不可用，请先开一个不含细节的 issue，请维护者提供安全联系方式。

报告应包含受影响版本/commit、影响、最小复现、是否需要已配对设备，以及你已经采取的临时缓解。不要对不属于你的公网服务进行扫描、压测或利用。

## 设计边界

- Python 服务强制监听数字回环地址，公网只能经 Nginx 精确 allowlist 路由进入。
- 配对码短时有效且一次性；长期凭据按设备隔离，数据库只保存哈希。
- Bark Key 保存于 `0600` 文件，不进入 Android、URL、普通日志或设备数据库。
- Bark payload 只含来源 App 与通知标题，不读取通知正文作为 Bark body。
- 管理与审计界面不应暴露公网。
- 自动更新同时固定 HTTPS host/path、公钥、Key ID、文件名、大小、SHA-256 和签名，并拒绝重定向。
- 仓库示例更新公钥没有对应私钥，不能签署任何有效默认更新。

## 部署者责任

- 使用受信任 TLS、独立服务账号、最小权限、防火墙、磁盘加密和定期恢复测试。
- 生成自己的客户端/更新签名密钥，绝不把私钥提交 Git。
- 在处理通知前取得设备所有者同意，并设置合理的保留期限。
- 上线前运行全套测试、`scripts/privacy_scan.sh` 和独立秘密扫描器。

---

Security fixes target the latest source on the default branch. This repository does not operate a public XXZF service or distribute an official binary. Report vulnerabilities through GitHub Private Vulnerability Reporting and never place real endpoints, notification content, device identifiers, Bark keys, tokens, certificates, or private keys in a public issue. Test only systems you own or are explicitly authorized to assess.
