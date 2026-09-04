# 插件接入 Agent 工具指南

插件可以通过 manifest 声明「Agent 工具」，让 AI 助手在对话中直接调用插件能力（查询、写操作等），与内置工具共用同一套 **分级 / 权限 / Web 确认**机制。

## 1. 快速开始

1. 在插件 `manifest.json` 的 `backend` 节点声明 `tools`；
2. 在插件后端类中实现 `agent_tool(name, arguments)` 方法；
3. 安装并**启用**插件后，新开一次 Agent 对话即可让助手使用这些工具。

> 工具清单在每次会话构建时从「已启用插件」动态读取，启用/禁用无需重启服务；内置工具与插件工具同名时以内置为准。

## 2. manifest 声明

示例（在现有插件上新增两个工具）：

```json
{
  "manifest_version": "1.0",
  "id": "demo_plugin",
  "name": "示例插件",
  "version": "1.0.0",
  "backend": {
    "entry": "demo_backend:DemoPlugin",
    "tools": [
      {
        "name": "demo_echo",
        "description": "回显给定文本，用于演示只读插件工具",
        "parameters": {
          "type": "object",
          "properties": {
            "text": { "type": "string", "description": "要回显的文本" }
          },
          "required": ["text"]
        },
        "level": "read",
        "permission": ""
      },
      {
        "name": "demo_cleanup",
        "description": "清理临时数据（危险操作示例）",
        "parameters": {
          "type": "object",
          "properties": {
            "target": { "type": "string" }
          },
          "required": ["target"]
        },
        "level": "dangerous",
        "permission": "demo:manage"
      }
    ]
  }
}
```

### tools 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 工具名，助手据此调用；需唯一（内置优先，建议加插件前缀避免冲突） |
| `description` | 是 | 一句话说明工具作用/何时使用，模型据此选择工具 |
| `parameters` | 是 | JSON Schema 对象：`type/object + properties/required`，参数均需显式声明 |
| `level` | 否 | `read`（默认）/ `write` / `dangerous` |
| `permission` | 否 | 所需 RBAC 权限码（如 `demo:manage`）；为空表示不校验权限 |

## 3. 后端实现

在 `backend.entry` 指向的类中实现 `agent_tool`：

```python
class DemoPlugin:
    # 构造参数由插件沙箱注入（media_service / downloader_core / agent_service 等）
    def __init__(self, media_service=None, agent_service=None):
        self._media_service = media_service
        self._agent_service = agent_service

    def agent_tool(self, name: str, arguments: dict):
        """Agent 工具统一入口：name=工具名，arguments=已校验参数"""
        if name == "demo_echo":
            return {"success": True, "data": {"echo": arguments.get("text")}}
        if name == "demo_cleanup":
            # 执行写操作...
            return {"success": True, "data": {"cleaned": arguments.get("target")}}
        return {"success": False, "error": f"未知插件工具: {name}"}
```

### 返回值约定

| 返回 | 含义 |
|---|---|
| `{"success": True, "data": {...}}` | 成功，`data` 给助手参考 |
| `{"success": False, "error": "原因"}` | 失败，错误信息返回给助手 |
| 纯 dict（不含 success/error 键） | 视为成功，整个 dict 作为 data |
| `None` | 视为成功、无 data |

工具异常会在执行器层被捕获并转换为失败结果，无需自行 try/except。

## 4. 分级、权限与确认

插件工具复用内置工具的安全模型，无需额外编码：

- **read**：直接执行；
- **write**：直接执行（Web 端同样需要 `agent:manage` 会话才可调用写工具会话内的确认流视工具而定）；
- **dangerous**：Web 端会先弹**确认卡片**，确认后才真正执行；IM/消息渠道不支持确认，会收到“需要二次确认”提示，请到 Web 端确认；
- **permission**：非空时，调用方（Web 用户权限 / IM 渠道全权）必须包含该权限码，否则拒绝执行。

> 建议：会改动数据的工具一律 `write/dangerous`，并按需声明 permission；不要把敏感信息放进 description/参数默认值。

## 5. 在会话中让助手使用

1. 确保插件已启用（插件管理页）；
2. 新开会话（或说“清空对话”）让工具清单刷新；
3. 直接提问，例如“用 demo_echo 回显 ‘hello’”或描述业务诉求，模型会根据 description 自主选择。

## 6. 常见问题

- **助手说“未知工具”**：插件未启用，或 manifest 里 `tools` 未解析（检查 JSON/name 冲突）；
- **返回“插件未加载”**：backend 类未成功加载，查看插件日志/后台日志；
- **工具改了不生效**：每次会话会重建工具清单，重开会话即可；
- **参数校验不严**：`parameters` 必须声明合法 JSON Schema，未知参数/缺必填参数会先被拦截。

## 7. 参考实现位置

- manifest 解析：`src/app/schemas/plugin.py`（`PluginToolConfig` / `PluginBackendConfig.tools`）
- 工具清单与执行：`src/app/services/plugin_framework_service.py`（`list_enabled_agent_tools` / `call_agent_tool`）
- 动态合并与派发：`src/app/agent/tool_executor.py`（`plugin_tools_provider` / `plugin_executor`）
- DI 装配：`src/app/di/builders/coordinators_builder.py`、`src/app/di/builders/agent_reload.py`
