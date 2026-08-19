# Contributing / 参与贡献

提交前请：

1. 从不含生产数据的干净分支开始。
2. 不提交 `.env`、账号、邮箱、真实服务器/IP、设备序列号、通知截图、数据库、日志、Bark Key、token、证书、私钥或安装包。
3. 对行为修改补充测试；安全边界默认 fail closed。
4. 运行：

   ```bash
   ./android/test_receiver.sh
   ./android/test_security.sh
   python3 scripts/test_codex_workflow.py
   PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s server -p 'test_*.py'
   ./server/mac_notifier/build.sh
   ./server/mac_receiver/test_update_manager.sh
   ./server/mac_receiver/build.sh
   ./server/mac_receiver/test_update_install.sh
   ./scripts/privacy_scan.sh
   ```

5. 在 PR 中描述动机、测试证据和隐私/兼容性影响，不粘贴真实通知或凭据。

接口或协议修改需同时更新中英文文档。新增外部网络请求必须说明目的、数据字段、是否可关闭，并添加明确 allowlist 与测试；不接受遥测、暗门账户或绕过用户授权的功能。

新增或替换 PNG/JPG/ICO/JAR 前必须人工查看画面和元数据；不接受包含桌面、设备名、账号、时间、通知、凭据或其他现实数据的截图。经审阅的二进制资源需同时更新 `scripts/privacy_scan.py` 中的完整性摘要。
