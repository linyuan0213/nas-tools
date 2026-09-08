# 浏览器系统通知（PWA / Web Push）

Nexus Media 支持把消息以**系统通知**的形式推到桌面通知栏与手机通知栏，即使关闭页面也能收到（Web Push），或安装为 PWA 后以类 App 方式使用。

- **页面内系统通知**：页面打开（含后台标签页）时，用浏览器 `Notification` 直接弹出，不依赖外部推送服务
- **Web Push（Service Worker）**：后台/关闭页面也能收到，由服务端推送（VAPID 签名）经浏览器厂商推送服务投递

两者由右上角铃铛的「系统通知」开关统一控制：开启 = 请求浏览器权限 + 订阅 Web Push；关闭 = 退订。

## 前提

| 条件 | 说明 |
|------|------|
| HTTPS | Web Push 与 Notification API 都要求安全上下文（`https://` 或 localhost） |
| 支持的浏览器 | Chrome / Edge / Firefox / Safari（iOS 16.4+，macOS 13+） |
| PWA 安装 | 手机端如需主屏幕图标/独立窗口，iOS Safari 用「分享 → 添加到主屏幕」，Android Chrome 用「安装应用」 |

## 使用步骤

1. 以 **HTTPS** 打开站点（如 `https://nexus.vivy.cc`）
2. 右上角铃铛 → 点击「系统通知」开关（🔔）→ 浏览器弹出授权时选**允许**
3. 完成后**每个浏览器/设备各自开启一次**（授权与订阅是按浏览器隔离的）

开启后仅推送**新产生**的消息（开启前的存量未读不会重推）。

## 各端可用性（含中国大陆网络说明）

| 端 | 页面打开时 | 关闭/后台（Web Push） | 说明 |
|----|-----------|----------------------|------|
| 桌面 Chrome | ✅ | ❌（大陆） | Web Push 走 `fcm.googleapis.com`，大陆不可达 |
| 桌面 Edge（Windows） | ✅ | ✅ | 走微软 WNS（`*.notify.windows.com`），大陆可达 |
| iPhone Safari / PWA | ✅ | ✅ | 走 Apple（`web.push.apple.com`），大陆可达 |
| Android Chrome | ✅ | ❌（大陆） | 同 Chrome，走 FCM |
| Firefox / 其他 | ✅ | ✅ | 走 Mozilla Push 或对应厂商服务 |

> 大陆网络下"关页也要收"：桌面建议用 **Edge**，手机 iOS 用 **Safari 添加到主屏幕**。Chrome 系关闭页面后收不到属 Google 通道限制，与应用无关。

## 配置

Web Push 的 VAPID 联系邮箱（`sub`）默认取**外网访问地址 `app.domain`** 的主机名推导（如 `mailto:noreply@你的域名`），一般无需配置。

| 配置 | 说明 |
|------|------|
| `app.domain` | 外网访问地址（`app` 段）；用于推导 VAPID 联系邮箱 |
| `app.push_contact`（可选） | 自定义联系邮箱，优先于 `app.domain` 推导 |
| 环境变量 `PUSH_VAPID_CONTACT` | 最高优先级覆盖 |

> ⚠️ Apple 校验 VAPID `sub`：使用 `@localhost` / `.local` 等本地域名会返回 `BadJwtToken`，必须用可公开解析的真实域名。

## 故障排查

| 现象 | 处理 |
|------|------|
| 开启开关后无授权弹窗 | 确认页面是 HTTPS；查看地址栏左侧站点设置里「通知」权限 |
| 手机收到、桌面收不到 | 桌面浏览器未开启/授权或订阅已失效：点开关关再开一次；DevTools → Application → Service Workers → Unregister 后刷新重新订阅 |
| 服务端日志 `410 Gone` | 订阅已被浏览器注销（如 Unregister），自动清理后重新订阅即可 |
| 服务端日志 `403 BadJwtToken`（Apple） | 联系邮箱用了 `.local`/本地域名，按上文配置真实域名后**重新订阅** |
| 只有打开页面才弹 | 该端 Web Push 通道不可达（如大陆 Chrome）；保留页面标签或改用 Edge/iOS Safari |

## 相关

- 通知设置与渠道：见 [通知渠道配置](notifications.md)
- 消息中心交互页可查看历史消息；点击系统通知会跳转消息中心
