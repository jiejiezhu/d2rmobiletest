# D2R Mobile · GitHub Actions 构建

[English](README.md) | **简体中文**

[![Build IPA](https://github.com/jiayx/d2r-mobile-build/actions/workflows/pack.yml/badge.svg)](https://github.com/jiayx/d2r-mobile-build/actions/workflows/pack.yml)

基于 [jhaizhou-ops/d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile) 的 **NO_XCODE** 方案，使用 GitHub Actions 构建未签名 IPA 和配套 Data 资源。可以从 Releases 下载，也可以按下方步骤自行构建。

## 下载与安装

进入 **[最新 Release](https://github.com/jiayx/d2r-mobile-build/releases/latest)**：IPA 从 **Assets 附件**下载，Data 从 Release 正文的**配套 Data**中直接点击下载链接。

**手机上已经有 Data？** 请先看[更新 IPA 与复用 Data](#4-更新-ipa-与复用-data)，确认是否需要重新下载。

| 文件 | 下载位置 | 用途 |
| --- | --- | --- |
| `D2RMobile-v1.0.15.ipa` | Assets 附件 | iOS 26 及以上，使用下方工具签名安装 |
| `D2RMobile-v1.0.15-ios18.ipa` | Assets 附件 | iOS 18–25，Metal 3 兼容版 |
| `Legacy-Device-Pack.zip` | 正文的老设备补充包链接 | A14–A16设备需要的额外贴图，约 1GB |
| `D2R-Mobile-Resources.zip.001`、`.002`、`.003` | 正文的配套 Data 链接 | 三个资源分卷，必须全部下载，总计约 5.42GB |
| `Resources-Parts-SHA256SUMS.txt`、`Resources-SHA256SUMS.txt` | 正文的配套 Data 链接 | 校验分卷与合并后的 ZIP |
| `RESOURCE-INSTALL.txt` | Assets 附件 | 分卷合并与资源导入说明 |

`Source code` 压缩包是构建脚本，不是安装包。

### 1. 安装 IPA

按系统选择：**iOS 26 及以上**使用 `D2RMobile-v1.0.15.ipa`；**iOS 18–25**使用 `D2RMobile-v1.0.15-ios18.ipa`。排查图形问题时，也可以在 iOS 26 及以上测试兼容版，但它并非已确认的系统崩溃修复。

两份安装包均支持 **A17 Pro 或更新芯片、M 系列 iPad，以及导入配套老设备补充包的 A14–A16芯片**。设备最低要求为 A14 / M1 及更新芯片、至少 6 GB 内存，不代表每种机型都已验证能稳定运行。

可选择以下 IPA 安装工具：

| 工具 | 使用条件 |
| --- | --- |
| [Sideloadly](https://sideloadly.io/) | macOS / Windows |
| [iloader](https://iloader.app/) | macOS / Windows / Linux |
| [AltStore Classic](https://faq.altstore.io/altstore-classic/your-altstore) | 先在 Mac 或 Windows 电脑上配置 AltServer |
| [SideStore](https://sidestore.io/) | 首次配置需要电脑，之后可在手机上导入 IPA |

按工具的官方说明完成配置，导入所选 IPA，并按 iOS 提示完成信任设置。两份 IPA 的应用标识相同，安装另一份会覆盖当前版本。**IPA 需要配合下方 Data 资源使用。**

### 2. 合并并解压 Data

将三个分卷和两个校验文件放在同一目录。

macOS：在该目录打开终端，执行：

```sh
shasum -a 256 -c Resources-Parts-SHA256SUMS.txt
cat D2R-Mobile-Resources.zip.001 D2R-Mobile-Resources.zip.002 D2R-Mobile-Resources.zip.003 > D2R-Mobile-Resources.zip
shasum -a 256 -c Resources-SHA256SUMS.txt
```

Linux 可使用 `sha256sum -c` 替代 `shasum -a 256 -c`。

Windows：在该目录打开**命令提示符（cmd）**，执行：

```bat
copy /b D2R-Mobile-Resources.zip.001+D2R-Mobile-Resources.zip.002+D2R-Mobile-Resources.zip.003 D2R-Mobile-Resources.zip
```

解压合并后的 ZIP，得到 `D2R Mobile Resources` 文件夹，内含 **18 个 `.data` 文件，约 5.56GB**。

### 3. 导入 Data 并启动

用数据线连接 iPhone，在 **Finder → iPhone → 文件 → D2R Mobile** 中拖入整个 `D2R Mobile Resources` 文件夹；也可以放进手机的 **文件 → 我的 iPhone → D2R Mobile**。

**A14–A16设备**还需从当前 IPA Release 正文的链接下载 `Legacy-Device-Pack.zip`，解压后把整个 `Legacy Device Pack` 文件夹放进应用，与 `D2R Mobile Resources` 并排。请使用当前 IPA Release 链接的配套补充包，两种系统版本共用这一份。A17 Pro 及更新芯片和 M 系列 iPad 无需导入补充包。

打开应用，点击“重试”。首次启动需等待着色器编译完成，**iPhone 17 Pro Max 参考耗时约 6 分钟**，其他机型耗时不同。当前 v1.0.15 包尚未进行真机运行验证。

### 4. 更新 IPA 与复用 Data

**v1.0.1 或 v1.0.6 下载的 Data 可以直接用于 v1.0.15 IPA，无需重新下载。**

如果手机上已经导入 `D2R Mobile Resources` 文件夹，保持应用标识不变，直接覆盖安装新版 IPA 即可，通常会保留资源和存档，无需再次导入。**不要先卸载应用，否则资源和存档会被删除。** 如果只是下载了资源、尚未导入，按上方第 2、3 步合并、解压并导入即可。

后续升级时，请先查看新 Release 的资源要求，再决定是否更换 Data。需要老设备补充包的机型，请使用当前 IPA Release 链接的配套补充包。

## 配套版本

| 项目 | 版本 |
| --- | --- |
| 上游 | v1.0.15 |
| Switch 更新 | `1.0.34.0` / `v2228224` |
| 游戏内部版本 | `3.3.94012` |
| 所需版本 | 包含「术士君临」资料片 |

## 自己运行构建

### 1. Fork 仓库

点击 **Fork** 创建自己的副本，打开 **Actions**，如有提示则启用工作流。请仅使用自己有权使用的游戏文件和密钥。

### 2. 配置输入

在自己的仓库进入 **Settings → Secrets and variables → Actions → New repository secret**，名称填写 **`GAME_INPUT_MANIFEST`**，完整粘贴以下 JSON。下载地址和 SHA256 已填好：

```json
{
  "kind": "packages",
  "files": [
    {
      "name": "game.torrent",
      "url": "https://gamegula.com/index.php?do=download&id=405",
      "sha256": "016f7c907deb1f4cd6098a7cd06823907a589ff2502aa2c8b341a89ccf984266",
      "select": [1, 2]
    }
  ],
  "key_archive": {
    "url": "https://drive.google.com/uc?export=download&id=147IsDRRJNF_VMT6Fj50glrnqAeb7oR_1",
    "sha256": "b73573af5eae6c9f7739ca9931cebf04774cf2ba9d6ee98f2f04c2dc88fca71c"
  }
}
```

种子中包含本体与更新包，`select: [1, 2]` 选择这两项；`key_archive` 是包含解包密钥的 ZIP。使用这份配置，无需另外填写 `PROD_KEYS` Secret。

### 3. 运行构建

进入 **Actions → Build D2R Mobile IPA → Run workflow**，选择 `main`，使用下表参数：

| 参数 | 填写内容 |
| --- | --- |
| `publish_release` | 正式发布保持 `true`；仅测试打包时取消勾选，产物只保存在 Actions |
| `prepare_only` | `false`，不勾选 |
| `input_revision` | `game-3.3.94012-v1`；更换游戏文件或修改种子下载项时更换 |

**只需运行这一个工作流。** 它会构建两份带老设备支持的 IPA，并自动发布 Release。已有相同 Data 时直接复用，不重新压缩或上传；没有配套资源或内容发生变化时，自动打包并发布 Data。老设备补充包也只生成一次，后续输入和转换设置匹配时直接复用。

构建成功后，进入**自己仓库的 Releases**。正文提供配套 Data 分卷与校验文件的直接下载链接，即使这些文件保存在较早的 Release，也可以从当前页面直接下载。按上方步骤合并并导入。资源标识与手机上已有 Data 相同时，更新 IPA 无需重新下载 Data。

请保留配套 Data 和老设备补充包所在的 Release 及其附件，确保下载链接持续可用。

Actions 运行摘要中也有 IPA 和 Data 的下载入口。IPA 构建附件内包含两份安装包、资源下载信息（`resources.json`、`legacy-resources.json`）和导入说明，保留期为 **3 天**。

编译工具和着色器按各自依赖缓存，单独更新应用版本不会使这些缓存失效。两份 IPA 共用一次生成的游戏内容，各自保留对应官方主程序和最低系统版本。


## 测试源码修改

打开 **Actions → Build from source (test) → Run workflow**。`source_repository` 填上游仓库或自己的 fork；`source_ref` 填分支、标签或提交，留空使用当前固定版本。如果要直接在本构建仓库维护补丁，将 `*.patch` 放入 `source-patches/` 并提交，从该分支运行工作流；补丁会先应用到所选源码，再生成内容和编译。

工作流在 Linux 上生成匹配的游戏内容，再在 **macOS 26** 上编译两份 App，要求 Xcode 带 **iOS 26.4 或更新 SDK**，不会下载上游的壳 IPA。游戏输入沿用上面的 Secret 配置，兼容的 Data 和 Legacy Device Pack 继续复用。着色器仍以源码放入包中，在手机上编译，与正式包相同。

运行完成后下载 `D2RMobile-source-ios26.0-*` 或 `D2RMobile-source-ios18.0-*` 附件，签名后覆盖安装其中的 IPA。附件保留 7 天；报告记录源码提交、补丁摘要和构建环境。源码测试不会发布 Release，产物尚未进行真机验证。
