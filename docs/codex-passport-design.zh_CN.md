<p align="right">
  <strong>简体中文</strong> · <a href="codex-passport-design.md">English</a>
</p>

# Codex 伴侣护照软件设计

本文档规范了将 FoloToy AI Passport（ESP32-C3）打造为专属 **Codex 伴侣护照**（Codex Passport）的系统架构、BLE 通信协议、状态机、数据持久化及用户界面设计。

## 1. 系统概述

Codex 伴侣护照基于 ESP32-C3 硬件平台（240 × 320 ST7789P3 屏幕、3 按键 ADC 分压梯、CW2017 电量计、NimBLE 蓝牙栈与 NVS 存储），为开发者的 Codex 编程活动提供专属身份凭证与实体数据看板。

核心目标：
1. **数字护照个人凭证**：展示机主姓名、签名、签发日期、今日 Token 与 GitHub 主页二维码。
2. **完全本地的用量采集与分析**：直接解析本机 `~/.codex/sessions/**/*.jsonl` 及归档会话，不依赖云端账号或远程模型。通过 `token_usage_record` 统计真实增量，按 `response_id` 精确去重，生成总 Token、今日、本周、连续活跃天数及 13 周热力图。
3. **足迹主题与活跃方向**：基于会话工作目录与项目名称，离线提炼开发主题足迹（首次活动时间与累计 Token）以及最近 30 天最活跃的方向。
4. **实时状态桌面提示**：监听活跃会话事件，映射为空闲、运行中、等待操作、完成、异常等状态，实时显示当前项目、耗时、当次与今日用量，并在超时后自动回退空闲。
5. **BLE 分片传输与掉电持久化**：采用 ESP-IDF 原生 NimBLE，设计分片传输协议（含版本、序号、长度与 CRC16 校验），数据写入 NVS，断线自动重连，重启即刻展示。

```text
+-------------------------------------------------------------+
|                          宿主计算机                          |
|                                                             |
|   ~/.codex/sessions/**/*.jsonl ──> [ 会话解析引擎 ]         |
|                                            │                |
|   本地个人配置 (config.json)   ──> [ 统计聚合分析 ]         |
|                                            │                |
|   当前会话变动监听             ──> [ 实时状态机 ]           |
|                                            │                |
|                                     [ BLE 同步管理 ]        |
+--------------------------------------------┬----------------+
                                             │ BLE (NimBLE GATT)
                                             │ 分片协议 + CRC16
+--------------------------------------------┴----------------+
|                 FoloToy AI Passport (ESP32-C3)              |
|                                                             |
|   [ NimBLE 外设服务 ] ──> [ 分片重组与校验 ]                |
|                                   │                         |
|                            [ NVS 数据持久化 ]               |
|                                   │                         |
|                 [ 顶部状态栏与 LVGL 界面 ]                    |
|           (首页 / 额度 / 热力 / 方向 / 二维码)                 |
+-------------------------------------------------------------+
```

---

## 2. 个人资料配置规范

默认初始数据：
- 姓名：`GuanMo`
- 兴趣：`读书 / 开发 / 运动`（同步保存，首页不展示）
- 签名：`In me the tiger sniffs the rose.`
- 主页：`https://github.com/Ljhhhhhh`

配置与隐私管理：
- 个人配置保存在宿主机 `~/.codex-passport/config.json` 或本地非 Git 跟踪路径，禁止提交进代码仓库。
- 仓库内提供不含敏感信息的示例文件 `config.example.json`。
- 资料字段通过 BLE 写入设备 NVS 命名空间 `codex_passport`。

---

## 3. Codex 用量采集引擎

### 3.1 Token 统计与去重
- 首选数据源：若存在 `~/.opencodex/usage.jsonl`（与 OpenCodex `/#usage` 仪表盘同一份本地账本），按 `requestId` 去重。方向页展示最近 30 天 Token 最多的 5 个模型；足迹按供应商归类（`OpenAI / Codex`、`xAI Grok`、`Gemini`）。
- 回退数据源：`~/.codex/sessions/**/*.jsonl` 及 `~/.codex/archived_sessions/`。
- 记录提取（回退）：匹配 `token_usage_record` 记录。
- 去重策略（回退）：以 `response_id` 为唯一键（空值时回退至 `(session_id, turn_id, ordinal)`），避免各轮次累计字段被重复相加。
- 聚合指标：
  - `total_tokens`：全量会话总消耗 Token。
  - `today_tokens`：本地自然日（00:00 - 23:59）内新增 Token。
  - `week_tokens`：本周自然周（周一至周日）内新增 Token。
  - `streak_days`：连续有编码记录的活跃天数。
  - `heatmap_91d`：最近 13 周（91 天）每天的活跃度阶梯（0 至 4 档）。

### 3.2 足迹主题与活跃方向
- 路径归类：基于 `turn_context.payload.cwd` 工作目录名称及路径模式。
- 离线分类规则：
  - 嵌入式与硬件：`ai-passport`、`esp32`、`bsp`、`hardware`、`iot`
  - Web 与前端：`open-webui`、`frontend`、`ui`、`react`、`vue`、`web`
  - AI 系统与智能体：`agent`、`codex`、`llm`、`deepseek`、`draft`
  - 基础服务与后端：`server`、`service`、`api`、`db`、`backend`
- 结果输出：
  - 主题足迹：各主题名称、首次活动日期（`YYYY-MM-DD`）与历史累计 Token。
  - 活跃方向：最近 30 天 Token 最多的前 5 个项目（OpenCodex 源下为模型）及其百分比占比。
- 隐私保障：不上传会话对话文本、代码或提示词至任何公网服务器或大模型。

---

## 4. 实时状态机

Codex 实时生命周期分为 5 种状态：
1. `IDLE` (0)：空闲，无正在执行的任务。
2. `RUNNING` (1)：运行中，智能体正在生成推理或调用执行工具。
3. `WAITING_INPUT` (2)：等待操作，需用户输入信息或进行确认。
4. `COMPLETED` (3)：完成，当前任务回合顺利结束。
5. `ERROR` (4)：异常，工具报错或执行失败。

超时回退机制：
- 超过设定时长（默认 90 秒）无新事件更新时，状态机自动回到 `IDLE`，防止外部终端直接退出后设备长时间滞留“运行中”。

实时遥测数据：
- `state`：状态枚举值 0..4。
- `duration_sec`：当前任务已耗时秒数。
- `turn_tokens`：当前轮次消耗 Token。
- `today_tokens`：今日累计 Token。
- `project_name`：当前所在项目名称。

---

## 5. 设备界面与交互设计

屏幕分辨率：240 × 320 像素。

### 5.1 顶部状态栏
- BLE 连接指示。
- 电池：有 CW2017 时显示采样电量。
- 状态戳：`IDLE`、`RUN`、`WAIT`、`DONE`、`ERR`。
- 非空闲时抽出一行：当前项目、时长、当次 Token。

### 5.2 页面
1. **首页**：姓名、上次 BLE 同步时间、签发日、今日 Token，底部为终身 / 近 7 天 / 连续天数。
2. **额度**：三个 Codex 登录账号各自的五小时与周限额占用及重置倒计时，数据来自本机 OpenCodex `/api/codex-auth/accounts`。
3. **热力图**：13 × 7（91 天），五档金箔浓度，活跃天数与峰值。
4. **方向**：最近 30 天 Top 5 项目及占比条。
5. **二维码**（叠加层）：GitHub 主页；任意页按 `OK` 开关。

足迹主题仍走 BLE/NVS，便于主机兼容，设备上不再展示。

### 5.3 硬件按键
- `UP`：上一页（若在二维码则先关闭）。
- `DOWN`：下一页（若在二维码则先关闭）。
- `OK`：打开或关闭二维码。
- Codex 应用有未读任务时保持亮屏，在 Codex 中打开对应任务后清除未读，设备按键不标记已读。未读数归零后，无操作 30 秒熄灭背光。未读状态未知或蓝牙断连时保持亮屏。确认键亮屏且不切换二维码，`UP` / `DOWN` 不唤醒。


---

## 6. BLE 通信与数据持久化

### 6.1 GATT 协议规范
- 服务 UUID：`0xCD00`
- 数据同步接收（`0xCD01`）：Write / Write Without Response（主机 -> 设备，分片传输）。
- 状态与 ACK（`0xCD02`）：Read / Notify（设备 -> 主机，回复应答与状态）。
- 实时事件通道（`0xCD03`）：Write Without Response（主机 -> 设备，高频实时推送）。

### 6.2 分片帧格式
```text
+--------------+---------+----------+---------+-----------+-------------+---------+---------+
| 魔数 (2B)    | 版本(1B)| 类型(1B) | 序号(1B)| 总包数(1B)| 长度(2B BE) | 数据负载| 校验(2B)|
| 0x50 0x54    | 0x01    | 0x01..07 | 0..N    | N+1       | <= 240      | ...     | CRC-16  |
+--------------+---------+----------+---------+-----------+-------------+---------+---------+
```
数据包类型：
- `0x01`：个人资料（姓名、兴趣、签名、主页、日期）
- `0x02`：里程统计（总量、今日、本周、连续天数）
- `0x03`：活跃热力图（91 字节等级数组 0..4）
- `0x04`：足迹主题数组
- `0x05`：近 30 天项目方向
- `0x06`：实时状态（状态、持续时间、当次 Token、今日 Token、项目名）
- `0x07`：ACK 确认帧
- `0x08`：额度（最多三个 Codex 账号：五小时占用、周占用、剩余秒数）

CRC16 使用 CRC-16-CCITT（多项式 `0x1021`）。

`0x0A` 传输应用的全局未读任务数，使用四字节小端无符号整数；`0xFFFFFFFF` 表示未知。TX 状态字节 4 为 `1` 表示支持此能力。主机读取 `.codex-global-state.json` 的 `electron-persisted-atom-state.unread-thread-ids-by-host-v1`，收到设备 ACK 后才将变更计为已同步。

### 6.3 NVS 持久化存储
命名空间：`codex_passport`。
- 键名：`profile`、`stats`、`heatmap`、`footprints`、`directions`。
- 设备冷启动时自动自检并读取 NVS 内容装载至界面。
- 若 NVS 尚无记录，自动加载 `GuanMo` 初始预置资料。

### 6.4 主机同步服务

macOS 上主机助手作为用户级 launchd 代理 `local.codex-passport-sync` 运行。`projects/codex-passport/tools/passport-sync` 负责安装与启停。Raycast 脚本在 `projects/codex-passport/tools/raycast/`，调用同一条命令。
