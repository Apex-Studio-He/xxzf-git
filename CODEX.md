# 让 Codex 帮你配置和构建 XXZF

> 这是给第一次碰源码的朋友准备的。你不需要先学会 Java、Python 或 C#，只要知道自己准备把 XXZF 放在哪个域名下。

![Codex 辅助构建流程](docs/images/codex-build.svg)

## 你要准备什么

只有 4 类公开信息：

1. **服务地址**：例如 `https://notify.example.com/xxzf`。必须是你控制的 HTTPS 域名，路径保持 `/xxzf`。
2. **更新地址**：例如 `https://updates.example.com/downloads/forwarder/test`。刚开始可以与服务地址使用同一个域名。
3. **想构建哪些部分**：`server`、`android`、`macos`、`windows`。
4. **测试版还是发布版**：第一次选 `debug`。给别人安装时再选 `release`。

不要把服务器密码、SSH 私钥、Bark Key、证书私钥或签名密码填进任何 JSON，也不要发到聊天里。

## 最简单的操作

### 1. 下载项目

会用 Git：

```bash
git clone https://github.com/Apex-Studio-He/xxzf-git.git
cd xxzf-git
```

不会 Git：在 GitHub 页面点 **Code → Download ZIP**，解压后用 Codex 打开这个文件夹。

### 2. 复制一份填写卡

```bash
cp codex/request.example.json codex/request.local.json
```

打开 `codex/request.local.json`，只替换两个示例网址，再选择目标平台。这个本地文件已被 Git 忽略，不会跟着正常提交上传。

### 3. 对 Codex 发这句话

```text
请按 CODEX.md 读取 codex/request.local.json，先检查环境，再在隔离副本中配置、测试并构建 XXZF。缺少环境时先告诉我下载大小和用途，得到我确认后再安装。不要部署服务器，不要要求我发送密码或私钥。
```

Codex 会先运行：

```bash
python3 scripts/codex_preflight.py --request codex/request.local.json
```

环境齐全后，它会运行：

```bash
python3 scripts/codex_build.py --request codex/request.local.json
```

构建在临时副本里进行，所以你的域名不会被写回公开源码。成品会放进 `dist/codex/`，Codex 应当同时告诉你文件路径和 SHA-256。macOS 目标会同时生成“转发”桌面接收端和服务器本机通知使用的 `XXZFNotifier` 辅助 App。

## 电脑要装哪些环境

| 你要做的东西 | 在哪种电脑上做 | 必需环境 |
|---|---|---|
| 服务端 | macOS 或 Linux | Python 3.9+；正式上线再准备 Nginx、域名和 HTTPS 证书 |
| Android APK | macOS | JDK 17、Android SDK Platform 35、Build Tools 35.0.0 |
| macOS App | macOS | Xcode Command Line Tools；正式发布需 Apple Developer ID |
| Windows EXE | Windows 10/11 | PowerShell 5.1+、.NET Framework 4.8 Developer Pack |

Windows 成品必须在 Windows 电脑构建；Mac 上不会“假装已经构建”。同理，macOS App 只能在 Mac 上构建。

## debug 和 release 怎么选

- `debug`：适合你自己真机测试。Android 会在仓库外自动生成一份测试签名。
- `release`：适合发给用户。必须使用你自己的 Android 签名、Apple Developer ID 或 Windows 代码签名。

发布签名的环境变量和私钥放置规则见[配置参考](docs/配置参考.md)。私密文件只保存在你的电脑里，脚本会拒绝权限过宽的文件。

## Codex 会做什么，不会做什么

Codex 会：

- 验证两个 URL 是否为安全的 HTTPS 地址。
- 检查当前电脑能构建哪些目标，把缺失项说清楚。
- 在临时副本里写入公开域名，运行测试，然后构建。
- 列出成功、失败和跳过的部分，不把“没测试”说成“没问题”。

Codex 不会在你只要求“构建”时直接登录服务器、修改 DNS、申请证书、撤销签名证书或发布更新。这些操作会先单独告知影响，再等你确认。

## 常见卡点

- **显示 `example.com`**：说明还在使用示例填写卡，把 `request.local.json` 中的两个地址换成你的域名。
- **Android SDK 缺失**：它的下载较大，Codex 应先征求你同意，再运行 `scripts/install_android_tools.sh`。
- **release 要签名**：这是系统对用户的保护，不能用公共证书或把私钥打包进开源项目。
- **Mac 上选了 Windows**：需把同一份源码放到 Windows 电脑，然后在那台电脑让 Codex 继续。

服务器真正上线时，继续看[小白部署指南](docs/部署指南.md)。
