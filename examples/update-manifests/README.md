# 更新清单是怎么生成的？

`android.json`、`macos.json` 和 `windows.json` 不是需要手写的源码。它们必须根据每次发布的真实安装包大小、SHA-256 和版本号生成，再由部署者的 RSA 私钥签名。

生成 Android 清单的例子：

```bash
export XXZF_UPDATE_PRIVATE_KEY=/仓库外/安全目录/update-private.pem
python3 scripts/publish_test_update.py \
  --platform android \
  --version-code 27 \
  --version 0.9.17 \
  --notes '安全与稳定性更新' \
  --package dist/NotifyBridge-release.apk \
  --output-root /tmp/xxzf-update
```

会得到：

```text
/tmp/xxzf-update/
├── android.json
└── forwarder-android-0.9.17-test.apk
```

验证：

```bash
python3 scripts/verify_published_update.py \
  /tmp/xxzf-update/android.json \
  --package-root /tmp/xxzf-update
```

不提供一份“看起来很像真的”假签名 JSON，因为客户端必须拒绝这种文件。清单字段、签名载荷和平台大小上限的权威实现在 `scripts/publish_test_update.py`，回归测试在 `server/test_update_manifest.py`。
