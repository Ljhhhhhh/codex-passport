<p align="right">
  <strong>简体中文</strong> · <a href="README.md">English</a>
</p>

# Codex 伴侣护照 (`codex-passport`)

专为 OpenAI Codex 与 OpenCodex 开发者打造的桌面智能随身 AI 硬件伴侣，运行于 FoloToy AI Passport（ESP32-C3 掌上硬件，240 × 320 竖屏彩色液晶）。

Codex Passport 可以放在显示器下方作为桌面副屏，也可以作为工卡随身携带。它通过低功耗蓝牙（BLE）与 Mac 电脑无感连接，实时呈现你的 AI Agent 任务进展、待确认提问、执行结果与账号额度，并提供轻柔贴心的事件声光交互。

---

## 核心特性

- 📡 **实时任务状态与消息列表**：开机即览当前 Codex 任务，清晰显示**等待用户输入回复**、**未读已完成**与**执行异常**的任务，每条任务均保留真实标题与对应工程项目。
- 🔔 **智能事件声光提醒**：仅当检测到新的待回复提问、新完成的任务或执行失败时，发出一次轻柔短促的 C5/E5 双音提示；开机历史消息同步、翻页、轮询与蓝牙重连全程静默，绝不打扰工作。
- 💤 **未读感知与智能休眠**：跨主机、跨项目存在未读待处理任务时屏幕保持常亮；在 Codex 中查阅消除未读后，设备无操作 30 秒平滑熄屏节电，按确定键一键唤醒。
- 📊 **账号额度与 Token 消耗看板**：实时读取本地 OpenCodex / Codex 账本，监控 3 个登录账号的 5 小时与周额度占用百分比、今日 Token 消耗、累计用量与连续活跃天数。
- 📶 **Mac 无感自动同步**：配套 macOS 后台登录项守护程序，基于 BLE 自动发现、自动重连与增量通信，设备端无需配置或输入 Wi-Fi 密码。
- 🔤 **原生高清全量中文**：内置基于思源黑体（SIL OFL 许可）的 30,440 字中文字库，完整覆盖常用汉字与符号，彻底告别方框缺字与乱码。

---

## 新手 1 分钟极速上手

### 准备工作

1. 一台 **FoloToy AI Passport** 硬件设备
2. 一根具备**数据传输功能**的 USB Type-C 线（避免使用仅能供电的纯充电线）
3. 一台运行 macOS 的电脑

---

### 第 1 步：烧录固件到设备

你可以选择以下两种方式之一烧录固件：

#### 方式 A：免开发环境网页一键烧录（最推荐新手）

1. 用 Chrome 或 Edge 浏览器打开 [ESP Web Flasher 网页烧录工具](https://espressif.github.io/esptool-js/)。
2. 将 AI Passport 通过 Type-C 线连接到电脑。
3. 获取预编译合并固件文件 `codex-passport-full.bin`（可从 Releases 下载或本地编译产物获取）。
4. 页面参数设置：
   - 波特率选择：`460800`
   - 写入地址填写：`0x0`
5. 点击 **Connect** 选中设备的 USB 串口并连接，然后点击 **Program** 开始烧录。烧录完成后设备将自动重启并进入系统。

#### 方式 B：开发者本地命令行烧录

如果你已安装并激活了 **ESP-IDF 5.5.3**：

```bash
# 编译并烧录固件，同时打开串口监视器
idf.py flash monitor
```

---

### 第 2 步：安装 Mac 桌面端同步服务

在你的 Mac 终端中进入项目目录，执行一键安装：

```bash
./tools/passport-sync install
```

- **全自动配置**：该脚本会自动在本地创建独立的 Python 虚拟环境并安装所需依赖，注册为 macOS 登录启动项（LaunchAgent）。
- **后台常驻**：安装后立即开始在后台扫描蓝牙并同步，每次开机登录自动启动，意外退出自动恢复。
- **日常管理命令**：
  ```bash
  ./tools/passport-sync status   # 查看服务运行状态与 PID
  ./tools/passport-sync logs     # 查看最近同步日志
  ./tools/passport-sync restart  # 重启同步服务
  ./tools/passport-sync stop     # 暂时停止同步
  ```
- **Raycast 快捷集成**：打开 Raycast 设置 → Extensions → Script Commands → Add Directories，添加本项目的 `tools/raycast` 目录，即可直接在 Raycast 中快速搜索并控制伴侣服务。

---

### 第 3 步：开机与日常使用

1. 打开 AI Passport 电源，设备开机后自动展示 **MESSAGES**（消息列表页）。
2. Mac 端同步服务会自动通过蓝牙连接名为 `Codex-Passport` 的设备。
3. 当你在电脑上使用 Codex 或 OpenCodex 进行编程协作时：
   - 产生新提问需要你确认/回复时，设备将亮屏并发出轻柔短音提示。
   - 任务顺利执行完成时，设备将更新未读完成卡片。
   - 在电脑端查阅对应任务后，设备端未读计数清空，并在 30 秒后自动熄屏待机。

---

## 屏幕页面与按键交互

AI Passport 正面配备三枚轻触按键：

| 按键 | 消息列表页 (MESSAGES) | 首页 (Home) / 额度页 (Quota) | 二维码页 (QR) | 熄屏休眠时 |
| :--- | :--- | :--- | :--- | :--- |
| **上键 (UP)** | 切换上一页视图 | 切换上一页视图 | - | 无响应（防误触） |
| **下键 (DOWN)** | 切换下一页视图 | 切换下一页视图 | - | 无响应（防误触） |
| **确定键 (OK)** | **查看下一组三条消息** | **打开主页二维码** | **关闭二维码** | **一键唤醒屏幕**（亮屏 30s） |

### 界面布局一览

- **消息列表页 (MESSAGES)**：默认启动页。分栏卡片展示任务列表，每页 3 条。每张卡片清晰标注【状态标签（WAIT/DONE/ERR）】、【任务真实标题】与【所属项目文件夹】。
- **个人首页 (Home)**：展示个人昵称、上次蓝牙同步时间、今日消耗 Token 数，底部展示总计使用量、近 7 天消耗与连续打卡天数。
- **额度看板页 (Quota)**：清晰呈现 3 个 Codex 账号的 5 小时短期额度柱状图与周度总额度百分比。
- **个人二维码页 (QR)**：展示可供手机扫描的个人 GitHub / 主页二维码。
- **顶部微型状态栏**：实时指示蓝牙连接状态、当前 Codex 整体状态（`IDLE` / `RUN` / `WAIT` / `DONE` / `ERR`）与电量计百分比。

---

## 常见问题排查 (FAQ)

<details>
<summary><strong>Q: 为什么设备屏幕会自动熄灭？</strong></summary>

这是内置的智能节能设计。当你在电脑上已读了所有已完成任务、且没有等待你回复的问题时，未读计数归零。设备在无按键操作 30 秒后会自动平滑熄灭背光省电。当有新消息到来时会立即重新点亮，或者你随时单击一下【确定键 (OK)】即可唤醒屏幕 30 秒。
</details>

<details>
<summary><strong>Q: 提示音什么时候会响？会打扰日常工作吗？</strong></summary>

提示音遵循**严格的事件驱动原则**：
- 仅在**产生新的待回复问题**、**新完成且未读的任务**或**任务报错**时播放一次轻柔的 C5/E5 双音（带 15ms 渐入与平滑衰减）。
- 首次连接、开机同步旧任务、翻页浏览、心跳轮询以及蓝牙重连时均**完全静默**，不会造成无意义的杂音打扰。
</details>

<details>
<summary><strong>Q: 为什么电脑识别不到 USB 串口？</strong></summary>

1. 检查 USB 数据线：必须是支持**数据传输**的 Type-C 线，部分廉价线缆仅支持充电。
2. ESP32-C3 采用原生 USB-Serial-JTAG 协议，macOS 与现代 Linux 系统免装驱动即可自动识别（串口设备路径通常为 `/dev/cu.usbmodem*`）。
</details>

<details>
<summary><strong>Q: 蓝牙连接不上或显示未连接？</strong></summary>

1. 确认 Mac 端是否已运行 `./tools/passport-sync start` 或处于活跃状态。
2. 运行 `./tools/passport-sync logs` 查看通信日志。设备广播名为 `Codex-Passport`，使用系统原生蓝牙服务，无需在系统蓝牙设置中手动配对。
</details>

---

## 进阶与开发者指南

### 本地编译固件

确保系统已安装并配置好 **ESP-IDF 5.5.3**：

```bash
# 1. 编译固件
idf.py build

# 2. 烧录并监控
idf.py flash monitor

# 3. 生成合并镜像（用于网页一键烧录）
idf.py merge-bin -o build/codex-passport-full.bin
```

### 运行单元测试与校验

```bash
# 验证音频发生器平滑衰减包络
python3 tests/test_passport_audio.py

# 验证 30,440 字点阵字库偏移与完整性
python3 tests/test_passport_font.py

# 验证增量事件提示音与任务去重逻辑
python3 tests/test_project_sync.py

# 验证用量统计解析与去重
python3 tests/test_codex_analytics.py
```

### 自定义机主个人资料

复制配置模板：

```bash
cp config.example.json profile.json
```

编辑 `profile.json`，填入你的姓名、兴趣、个性签名和个人主页链接。重新同步后，设备首页和二维码将自动更新为你专属的个性名片。

---

## 开源许可与致谢

- 固件与工具源码采用与原项目一致的开源许可。
- 内置中文字体基于 Adobe 思源黑体（Source Han Sans SC），采用 [SIL Open Font License 1.1](assets/fonts/OFL.txt) 许可。
- 硬件设计源自 FoloToy AI Passport 开源硬件方案。
