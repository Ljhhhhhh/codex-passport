<p align="right">
  <strong>简体中文</strong> · <a href="README.md">English</a>
</p>

# Codex 伴侣护照 (`codex-passport`)

运行在 ESP32-C3 FoloToy AI Passport（240 × 320）上的个人证件与 Codex 用量伴侣。

## 消息列表与状态

设备开机进入 **MESSAGES**（消息列表页）。UP/DOWN 在首页、额度和消息列表页之间切换；消息列表页按 OK 请求下一组，每组显示三条消息。其他页面按 OK 打开二维码。消息列表内容发生变化时会唤醒已熄灭的屏幕，亮屏 30 秒。

更新固件后重启 Mac 服务：`projects/codex-passport/tools/passport-sync restart`。只有设备确认收到消息页后，`passport-sync logs` 才会显示 **Projects ACK**。旧固件会产生明确的升级提示。

消息列表展示未读的已完成、待回复以及失败任务，每条显示任务真实标题、当前状态及所属项目。同一项目的不同任务分别展示，存在未处理问题时优先显示待回复。待回复和失败不受仅当天记录限制，已完成任务按桌面真实未读 ID 补读历史记录；未读源异常时提示同步异常。运行中、主动中断的任务不在消息列表中展示；若任务重新运行，将移除旧消息状态。列表按状态最新更新时间倒序排列，空列表显示“暂无消息”。

本项目状态页尚未启用设备端标记已读操作。缺失标题时显示短 ID。用量统计仍由原有统计采集器提供。

## 界面

- **首页**：姓名、上次 BLE 同步时间、今日 Token，底部为终身 / 近 7 天 / 连续天数。
- **额度**：三个 Codex 登录账号各自的五小时与周限额占用。
- **消息**：消息列表，展示未读已完成、待回复、失败任务，每页三条。
- **二维码**（其他页按 OK）：GitHub 主页。

状态栏：蓝牙、Codex 状态（`IDLE` / `RUN` / `WAIT` / `DONE` / `ERR`）、电量。会话进行中会抽出一行当前活跃任务所属项目名和时长。

## 按键

| 按键 | 作用 |
| :--- | :--- |
| `UP` | 上一页 |
| `DOWN` | 下一页 |
| `OK` | 消息列表页查看下一组；其他页打开或关闭二维码 |

Codex 应用跨主机、跨项目有未读任务时，屏幕持续常亮。在 Codex 中打开对应任务后清除未读，设备按键不会标记已读。未读数归零后，无操作 30 秒才熄灭背光。确认键亮屏且不切换二维码。`UP` / `DOWN` 不唤醒。尚未取得未读数、蓝牙断连或无法读取应用状态时，屏幕保持亮屏。

Mac 从 `$CODEX_HOME/.codex-global-state.json`（默认 `~/.codex`）读取 `electron-thread-read-state-v1`（兼容回退至旧版 `unread-thread-ids-by-host-v1`），每两秒同步变化。

## 烧录

合并固件（地址 `0x0`）：

`build/codex-passport-full.bin`

网页烧录：连接 ESP32-C3 USB JTAG，起始地址 `0x0`，波特率 `460800`。

或在 ESP-IDF 5.5.3 环境中：

```bash
idf.py -C projects/codex-passport flash
```

从 `0x0` 烧录合并镜像会写入出厂默认资料。

## 从电脑同步

设备广播名为 `Codex-Passport`。安装一次登录项：

```bash
projects/codex-passport/tools/passport-sync install
```

安装后立即开始 BLE 同步，登录时自动拉起，进程退出也会拉起。日常用 `start` / `stop` / `restart` / `status` / `logs`。或在 Raycast：Settings → Extensions → Script Commands → Add Directories → `projects/codex-passport/tools/raycast`，搜索 `Codex Passport`。

前台运行（不装登录项）：先 `pip install bleak`，再 `python3 projects/codex-passport/tools/assistant.py --sync --interval 60`。可选 `--device <地址>`、`--config 配置.json`、`--interval 120`。

设备只走 BLE，不上 Wi-Fi：ESP32-C3 无 PSRAM，已经同时跑 LVGL 和 NimBLE；用量账本也在电脑本机。

助手优先读取本机 `~/.opencodex/usage.jsonl`（与 OpenCodex 仪表盘 `/#usage` 同一份账本），按 `requestId` 去重，把最近 30 天 Token 最多的模型映射到方向页。若该文件不存在，则回退到 `~/.codex/sessions` 与 `response_id`。

无隐私示例：`projects/codex-passport/config.example.json`。真实个人配置不要提交 Git。

## 验收

```bash
./tools/validate.sh --static
./tools/validate.sh --firmware codex-passport
```

## 设计说明

[docs/software-design/codex-passport-design.zh_CN.md](docs/codex-passport-design.zh_CN.md)
