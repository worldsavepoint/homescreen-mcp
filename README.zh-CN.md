<div align="center">

<h1>iOS 桌面整理</h1>
<p>iOS Home Screen Organizer</p>
<p><strong>在 Mac 上整理 iPhone 或 iPad 的主屏幕，支持拖拽编辑与 MCP 助手操作。</strong></p>

**原作：Jonathan Kats · 本仓库为 [kats1123/homescreen-mcp](https://github.com/kats1123/homescreen-mcp) 的独立维护 fork。**

[![Release](https://img.shields.io/github/v/release/worldsavepoint/ios-homescreen-organizer)](https://github.com/worldsavepoint/ios-homescreen-organizer/releases)
[![Build](https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml/badge.svg)](https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml)
[![MIT 许可证](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-14%2B-222222?logo=apple)](macapp/BUILDING.md)
[![源码构建](https://img.shields.io/badge/source_build-Python_3.12_%C2%B7_arm64_%26_x86__64-3776AB)](macapp/BUILDING.md)

[English](README.md) · **简体中文**

[安装](#install) · [开始使用](#get-started) · [兼容性](#compatibility) · [可选 MCP](#mcp) · [问题反馈](https://github.com/worldsavepoint/ios-homescreen-organizer/issues)

</div>

拖动真实 App 图标，整理文件夹和小组件，按颜色或使用情况排序，预览布局后通过 USB 应用到设备。iOS Home Screen Organizer 提供 Mac App、浏览器编辑器、CLI，以及供 AI 助手使用的可选 MCP 服务。免费开源，无需账户或越狱。

本 fork 维护设备会话、备份、本地编辑器和 macOS 启动器的改进。原始应用、界面与 SpringBoard 研究由 **Jonathan Kats 及上游贡献者**完成。本 fork 独立维护。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/app-dark.png">
  <img alt="iOS Home Screen Organizer 编辑器：真实 App 图标、小组件、App 资源库和应用使用情况" src="docs/app-light.png">
</picture>

<p align="center"><sub>界面截图来自 Jonathan Kats 的上游 Homescreen 项目。</sub></p>

<a id="features"></a>

## ✨ 功能亮点

- **可视化整理：** 跨页面拖动图标、文件夹、小组件和程序坞项目，支持多选、搜索、撤销/重做，以及按住 ⌥ 拖动交换位置。
- **一键排序：** 按颜色、A–Z、App Store 类别或应用使用情况整理，并估算可减少的翻页次数。
- **整理暂存区：** 将项目暂放在 App Bank，添加、移动或删除页面，编辑包含多页的文件夹。
- **管理 App 资源库：** 将 App 移入或移出资源库；根据已安装应用和可见布局推算资源库内容。
- **预览与应用：** 比较草稿变化，写入前保存对应设备的备份，写入后重新读取结果；比较时包含设备导出的小组件设置。
- **多种操作方式：** Mac App、本地浏览器编辑器、CLI 或 30 个 MCP 工具；草稿与备份按设备分别保存。

<a id="fork-updates"></a>

## 🔧 本 fork 的改进

- **只读会话：** 设置 `HOMESCREEN_READ_ONLY=1` 后，可读取设备并编辑本地草稿；编辑器、CLI 和 MCP 会话中的 Apply 与 Restore 均禁用。
- **设备与备份处理：** Apply 和 Restore 会刷新设备身份与布局、记录备份来源，并核对操作结果。操作中断或结果不符后，重新执行 Read。Restore 选择设备来源信息匹配的备份。
- **本地编辑器与启动器：** 编辑器会话认证、后端健康检查，以及启动器 URL/请求校验。见[本地编辑器 API 参考](docs/LOCAL-EDITOR.md)。
- **旧版布局与分发：** iOS 16 位置调整提示、模拟器图标渲染，以及合并到 main 后自动触发的 DMG/ZIP 版本发布和 SHA256 校验文件。
- **源码构建：** 为 Apple 芯片和 Intel Mac 上的 Python 3.12 固定依赖版本并校验哈希。见[构建说明](macapp/BUILDING.md)。

<a id="install"></a>

## 📦 安装

**Apple 芯片或 Intel Mac · macOS 14 及以上 · iOS 16 / 17 / 18 / 26 / 27**

### 下载 Mac App

打开 [Releases](https://github.com/worldsavepoint/ios-homescreen-organizer/releases)，根据 Mac 的处理器选择下载。在 **Apple 菜单 → 关于本机**中查看**芯片**或**处理器**：

- **Apple 芯片**（Apple M 系列）：下载 `ios-homescreen-organizer-<version>-macos-arm64.dmg`。
- **Intel 处理器**：下载 `ios-homescreen-organizer-<version>-macos-x86_64.dmg`。

打开 DMG，将 **iOS Home Screen Organizer（iOS 桌面整理）**拖入 **Applications（应用程序）**。两种架构均提供 ZIP 压缩包。发行包内置 Python 引擎和依赖，需要 macOS 14 及以上，并与 Mac 的 CPU 架构匹配。

应用使用 **ad-hoc 签名**。macOS 提示确认时，前往**系统设置 → 隐私与安全性 → 仍要打开**，再启动 iOS Home Screen Organizer。

`SHA256SUMS.txt` 包含全部四个发行文件的哈希。将它与所选的 DMG 或 ZIP 放在同一目录，再校验下载文件：

```sh
shasum -a 256 --check --ignore-missing SHA256SUMS.txt
```

PR 构建产物位于 [Actions](https://github.com/worldsavepoint/ios-homescreen-organizer/actions/workflows/tests.yml) → 已完成的运行 → **ios-homescreen-organizer-macos-arm64** 或 **ios-homescreen-organizer-macos-x86_64**。合并到 `main` 且两种架构均构建成功后，会按新的项目版本号自动发布到 Releases。

### 从源码安装

需要 **Apple 芯片或 Intel Mac、macOS 14+ 和对应架构的原生 Python 3.12**。通过 USB 连接 iPhone 或 iPad，并在设备上信任这台 Mac。先克隆仓库并创建虚拟环境：

```sh
git clone https://github.com/worldsavepoint/ios-homescreen-organizer.git
cd ios-homescreen-organizer
python3.12 -m venv .venv
```

**Apple 芯片 Mac** 使用仓库内的依赖锁：

```sh
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
```

**Intel Mac** 先安装[源码构建工具](macapp/BUILDING.md#intel-dependencies)，再准备并安装带哈希校验的 Intel 依赖：

```sh
bash macapp/prepare_intel.sh python3.12 "$PWD/build/dependencies/x86_64"
.venv/bin/python -m pip install --require-hashes --only-binary=:all: \
  --find-links "$PWD/build/dependencies/x86_64/wheels" \
  -r "$PWD/build/dependencies/x86_64/requirements-build.lock"
```

两种架构随后均执行：

```sh
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
```

以只读模式启动浏览器编辑器：

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/ios-homescreen-organizer ui
```

命令行编辑器使用 `ios-homescreen-organizer`，MCP 服务使用 `ios-homescreen-mcp`，同时提供 `homescreen` 与 `homescreen-mcp` 兼容入口。

### 构建 Mac App

安装 Python 3.12 与[源码构建工具](macapp/BUILDING.md)后，在目标 Mac 的仓库根目录执行：

```sh
macapp/build.sh
```

脚本自动选择主机的原生架构（`arm64` 或 `x86_64`），生成 `build/<arch>/iOS Home Screen Organizer.app` 和 `build/<arch>/ios-homescreen-organizer-<version>.dmg`。构建使用全新的 Python 环境，按需准备 Intel 依赖，并应用 **ad-hoc 签名**。详见 [macOS 构建与签名说明](macapp/BUILDING.md)。

执行 `python3.12 macapp/release.py package --arch "$(uname -m)"` 可生成发行文件。`build/release/<arch>/` 中包含对应架构的 DMG、ZIP 与 `SHA256SUMS.txt`。正式发布时，两种架构合并使用一份校验清单。发布步骤见[自动发布说明](macapp/BUILDING.md#automatic-releases)。

<a id="get-started"></a>

## 🚀 开始使用

1. 启动编辑器，通过 USB 连接并解锁 iPhone 或 iPad；出现提示时点击**信任**。
2. 选择设备，点击 **Read**，读取当前布局。
3. 拖动项目、使用排序操作，或将项目暂放在 **App Bank**。应用前，改动保留在本地草稿中。
4. 查看布局差异。只读会话中可以继续浏览和编辑草稿，Apply 与 Restore 均禁用。

需要正常会话时，不设置 `HOMESCREEN_READ_ONLY=1`，直接运行 `.venv/bin/ios-homescreen-organizer ui`，或打开已构建的 Mac App。**Review & Apply** 会先保存备份，再将确认后的草稿写入设备。设备验证情况见[兼容性](#compatibility)。

应用布局前，请先在设备上**取消隐藏主屏幕页面**：长按主屏幕，点击页面圆点。在 iOS Home Screen Organizer 中重新建立需要的空位。见 [USB 布局细节](#usb-details)。

### 按应用使用情况排序

- **设备报告：** iOS 定期生成的内存报告可用于估算应用使用情况。估算会调低频繁或持续驻留内存的 App 权重。
- **屏幕使用时间：** 在设备与 Mac 上开启*设置 → 屏幕使用时间 → 在设备之间共享*。读取同步历史需要在*系统设置 → 隐私与安全性*中，为 iOS Home Screen Organizer 或运行它的终端授予**完全磁盘访问权限**。

### CLI

安装后，使用 `.venv/bin/ios-homescreen-organizer --help` 查看命令：

```text
read · show · diff · preview · apply · backups · restore · diagnose · probe · ui
```

对一台已信任的 USB 设备生成读取兼容性报告：

```sh
HOMESCREEN_READ_ONLY=1 .venv/bin/ios-homescreen-organizer diagnose
```

该命令输出系统报告的软件版本与布局汇总数量。

<a id="compatibility"></a>

## 📱 兼容性

- **iOS 16：** 支持 App 顺序、文件夹、程序坞和 App 资源库整理。图标按页面顺序排列；页面开头有小组件时，将文件夹放在其后。编辑器会提供位置调整提示。
- **iOS 17、18、26、27：** 支持 App 与文件夹整理、程序坞、App 资源库、小组件保留和固定位置布局编辑。
- **模拟器开发：** 覆盖这些版本系列的图标元数据读取与资源目录图标渲染。见[布局模式与兼容性检查](docs/COMPATIBILITY.md)。
- **iPad：** MCP/CLI 与编辑器采用设备提供的网格、程序坞和文件夹容量，小组件页面保留 iPadOS 提供的结构。
- **macOS：** 提供适用于 macOS 14 及以上的 Apple 芯片（`arm64`）和 Intel（`x86_64`）原生 App。
- **Python：** 包元数据支持 Python 3.11+；文档中的源码与发行构建使用 Python 3.12，以及对应架构的哈希校验依赖。

iOS Home Screen Organizer 根据已安装应用和布局读取结果推算 App 资源库。应用布局前，保留一份归档的设备备份，并在编辑器中重新建立需要的空位。

<a id="mcp"></a>

## 🔌 可选：使用 AI 助手

MCP 可让助手查看、整理、排序并解释布局。Mac App 配合 Claude Code 时，选择 **Device → Copy MCP Setup Command**，命令指向 App 内置引擎：

```sh
claude mcp add ios-homescreen-mcp -- "/Applications/iOS Home Screen Organizer.app/Contents/Resources/engine/engine" mcp
```

使用 Python 安装时，在仓库根目录运行以下命令，使用虚拟环境中的可执行文件：

```sh
claude mcp add ios-homescreen-mcp -- "$PWD/.venv/bin/ios-homescreen-mcp"
```

配置 Claude Desktop 的 `claude_desktop_config.json` 时，将 `/path/to/ios-homescreen-organizer` 替换为仓库实际所在的绝对路径：

```json
{
  "mcpServers": {
    "ios-homescreen-mcp": {
      "command": "/path/to/ios-homescreen-organizer/.venv/bin/ios-homescreen-mcp",
      "env": { "HOMESCREEN_READ_ONLY": "1" }
    }
  }
}
```

可以尝试：“按颜色整理我的 App”或“把最常用的 App 放到第一页”。助手修改的是草稿。正常会话中，可通过编辑器或 `ios-homescreen-organizer apply <token>` 应用草稿。让助手直接发起写入需要设置 `HOMESCREEN_ALLOW_APPLY=1`；设置 `HOMESCREEN_READ_ONLY=1` 时，Apply 与 Restore 始终禁用。

<a id="usb-details"></a>

## 🧠 工作原理

[pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 负责 USB 通信：`com.apple.springboardservices` 读取布局和图标，`installation_proxy` 读取已安装应用。编辑器运行于 `127.0.0.1`，使用认证的本地会话。草稿、备份和图标缓存保存在 `~/Library/Application Support/homescreen-mcp`。

可选的 **Group by App Store category** 操作会先征求同意，再将 bundle ID 发往 Apple 公共查询 API，并缓存结果。屏幕使用时间来自本地同步的 Biome `App.InFocus` 流。翻页估算将第 *N* 页计为 *N−1* 次滑动，再加上文件夹翻页；程序坞不计滑动次数。

<details>
<summary><strong>App 资源库与小组件研究——来自上游项目</strong></summary>

Jonathan Kats 的上游研究描述了 SpringBoard 图标状态的导入路径：

1. USB `getIconState` 按 `[dock, page 1, page 2, …]` 返回图标顺序。
2. `setIconState` 进入 `-[SBIconController importIconState:]`；`+[SBIconStateArchiver rootArchiveFromITunesRepresentation:]` 将列表转换为 `buttonBar` 和 `iconLists`。
3. 列表未提及的 App 可能被放到主屏幕页面。字典导入格式使用 `ignored` 保留 App 资源库中的项目位置。

iOS Home Screen Organizer 因此使用 SpringBoard 的字典形式：`buttonBar`、`iconLists`，以及存放资源库项目的 `ignored`。后者通过已安装应用（含已卸载但保留数据的 App）减去主屏幕应用、隐藏与仅供系统使用的应用推算。移动项目时保留 App、文件夹数据及未知字段。

**小组件：** 配置关联到元素 ID，USB 以 `userSelectedElementIdentifier` 导出。iOS Home Screen Organizer 将其作为 `uniqueIdentifier` 写回，并跨读取记住 ID。回读核对导出的小组件设置和元素标识。

**网页快捷方式：** iOS Home Screen Organizer 按设备记住从布局中读取的快捷方式，并将主屏幕外的快捷方式放入 `ignored`。若写入后出现新的快捷方式，结果会在 `hidden_webclips` 中列出。将其移回 App 资源库后，再次应用布局。

上游实现会在需要保留设备现值时省略 Today View 和页面 ID 键。模拟器研究工具位于 [`tools/sbhelper/`](tools/sbhelper/README.md)，原始研究见[上游项目](https://github.com/kats1123/homescreen-mcp)。

</details>

<details>
<summary><strong>空位、隐藏页面与布局校验</strong></summary>

iOS 在 `listMetadata` → `fixedLocations` 中按页面 ID 保存固定空位。写入时携带页面 ID 和空位元数据，以保留各页面的空位。

- iOS Home Screen Organizer 按设备记住编辑器中创建的空位，并在写入时发送页面 ID 与固定位置。
- 在编辑器中将 App 拖到目标空位置，重新建立需要的空位。
- 应用布局前，取消隐藏主屏幕页面。

布局校验涵盖页面/程序坞/文件夹容量、项目重复或丢失、文件夹中的嵌套文件夹或小组件，以及 App Bank 是否已清空。iPhone 的 4×6 页面有 24 格，小/中/大小组件占 4/8/16 格，程序坞容纳 4 个 App，文件夹每页容纳 9 项。iPad 的容量来自设备提供的图标布局参数。

不会在主屏幕显示的系统应用列在 [`homescreen/device.py`](homescreen/device.py) 的 `NEVER_ON_HOME_SCREEN` 中。如果 `added_by_ios` 报告了意外的系统 App，可能需要更新该列表。

</details>

<a id="development"></a>

## 🛠️ 开发

按前文完成源码安装后，运行仓库检查：

```sh
.venv/bin/python -m pytest -q tests
```

使用示例布局探索编辑器：

```sh
.venv/bin/python tests/fake_phone.py fake.plist --dict
HOMESCREEN_FIXTURE=fake.plist .venv/bin/ios-homescreen-organizer ui
```

或使用已启动的模拟器：

```sh
HOMESCREEN_SIM=booted .venv/bin/ios-homescreen-organizer ui
```

参考：[macOS 构建与依赖锁](macapp/BUILDING.md) · [本地编辑器会话与 API](docs/LOCAL-EDITOR.md) · [兼容性检查](docs/COMPATIBILITY.md)。

<a id="credits"></a>

## 🤝 致谢与支持

**Jonathan Kats** 创建了 Homescreen。原始 Mac App、编辑器、截图和 SpringBoard 研究的贡献归属于[上游项目](https://github.com/kats1123/homescreen-mcp)及其贡献者。感谢 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 提供 USB 设备通信接口。

- **本 fork：** [源码与改动](https://github.com/worldsavepoint/ios-homescreen-organizer) · [问题反馈与支持](https://github.com/worldsavepoint/ios-homescreen-organizer/issues)。
- **原始项目：** [上游源码](https://github.com/kats1123/homescreen-mcp) · [上游问题反馈与支持](https://github.com/kats1123/homescreen-mcp/issues) · [上游发行版](https://github.com/kats1123/homescreen-mcp/releases)。

本 fork 的问题请附安装方式、复现步骤、预期结果和脱敏后的错误信息。

<a id="license"></a>

## 📄 许可证

[MIT](LICENSE)。Copyright © 2026 Jonathan Kats。保留原始许可证与版权声明。

iPhone、iOS 和屏幕使用时间是 Apple 的商标。iOS Home Screen Organizer 使用私有设备接口执行布局操作。
