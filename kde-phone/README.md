# kde-phone — KDE 手机连接

KDE Connect Android 客户端 APK 的部署包，用于在 Android 手机与桌面端（KDE Connect / GSConnect）之间配对连接。

> ⚠️ `kde.apk`（6.7MB）已被 `.gitignore`（`*.apk`）排除，不随仓库分发；
> 需从系统源位置 `/usr/chindows/phone/kde.apk` 获取。

## 内容

| 文件 | 说明 |
|---|---|
| `kde.apk` | KDE Connect TP（Tech Preview）Android 包（不含在仓库内） |
| `install.sh` | 部署脚本：拷贝 APK 到桌面 + 清理旧的 .desktop 启动项 |

## 能力（APK 内置）

- **网络**：LAN（Apache MINA，TCP/UDP 双通道）+ 蓝牙双链路
- **插件**：电量、查找手机、媒体控制（MPRIS）、SFTP 远程文件（内置 SSHD）、分享、系统音量、通知/SMS/通话同步
- **UI**：Jetpack Compose Material3，多 ABI（arm64-v8a / armeabi-v7a / x86 / x86_64）

## 部署

```bash
bash install.sh          # 拷贝 APK 到 ~/桌面 + 清理旧启动项
# 之后在 Android 设备安装 kde.apk，与桌面端 KDE Connect / GSConnect 配对
```
