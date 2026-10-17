"""English-first, bilingual descriptions for IPA and resource Releases."""

import ci


INSTALLER_LINKS = '[Sideloadly](https://sideloadly.io/), [iloader](https://iloader.app/), [AltStore Classic](https://faq.altstore.io/altstore-classic/your-altstore), and [SideStore](https://sidestore.io/)'
CHINESE_INSTALLER_LINKS = '[Sideloadly](https://sideloadly.io/)、[iloader](https://iloader.app/)、[AltStore Classic](https://faq.altstore.io/altstore-classic/your-altstore)、[SideStore](https://sidestore.io/)'

def bilingual(english, chinese):
    return ('[English](#english) | [简体中文](#简体中文)\n\n'
            '## English\n\n' + english.strip() + '\n\n---\n\n'
            '## 简体中文\n\n' + chinese.strip() + '\n')


def ipa(repo, config, reference, legacy=None):
    standard, compatibility = ci.ipa_names(config)
    readme = f'https://github.com/{repo}#readme'
    chinese_readme = f'https://github.com/{repo}/blob/main/README.zh-CN.md'
    data_url = reference['source_release']['url']
    identity = reference['resource_id']
    links = '\n'.join(f"- [{a['name']}]({a['url']})" for a in reference['assets']
                      if a['name'] != 'resources-report.json')
    english_legacy = chinese_legacy = ''
    if legacy:
        url = next(a['url'] for a in legacy['assets'] if a['name'] == 'Legacy-Device-Pack.zip')
        english_legacy = (
            '### A14–A16 devices\n\n'
            f'Also download [Legacy-Device-Pack.zip]({url}), extract it, and copy the entire '
            '`Legacy Device Pack` folder into the app beside `D2R Mobile Resources`. '
            'Both IPA variants use this pack. A17 Pro and newer devices and M-series iPads do not need it.\n\n')
        chinese_legacy = (
            '### A14–A16设备\n\n'
            f'还需下载 [Legacy-Device-Pack.zip]({url})，解压后将整个 `Legacy Device Pack` 文件夹'
            '与 `D2R Mobile Resources` 并排导入。两份 IPA 共用本补充包；A17 Pro 及更新芯片和 M 系列 iPad 无需导入。\n\n')
    english = (
        f"Game version **{config['game_version']}**, Switch update **{config['switch_version']}**.\n\n"
        f'For detailed installation and usage instructions, see the [README]({readme}).\n\n'
        f'### Install an IPA\n\nSign and install using one of these tools: {INSTALLER_LINKS}. Choose by system:\n\n'
        f'- iOS 26 and later: `{standard}` (Metal 4).\n'
        f'- iOS 18–25: `{compatibility}` (Metal 3 compatibility build).\n\n'
        'The variants share an app identifier, so installing one replaces the other.\n\n'
        + english_legacy +
        f'### Game data\n\n[Download the required game data]({data_url}). Download all three parts '
        'and both checksum files, then follow `RESOURCE-INSTALL.txt` to combine and import them.\n\n'
        + links + '\n\n'
        f'Resource ID: `{identity}`. If this data is already imported, you do not need to download or import it again.\n\n'
        'First-launch shader compilation reference: about 6 minutes on iPhone 17 Pro Max. '
        'The current packages have not yet been verified on physical devices.\n')
    chinese = (
        f"游戏版本 **{config['game_version']}**，Switch 更新 **{config['switch_version']}**。\n\n"
        f'详细使用方式请参考 [中文 README]({chinese_readme})。\n\n'
        f'### 安装 IPA\n\n可使用 {CHINESE_INSTALLER_LINKS} 签名安装，按系统选择：\n\n'
        f'- iOS 26 及以上：`{standard}`（Metal 4）。\n'
        f'- iOS 18–25：`{compatibility}`（Metal 3 兼容版）。\n\n'
        '两份 IPA 使用相同应用标识，安装另一份会覆盖当前版本。\n\n'
        + chinese_legacy +
        f'### 配套 Data\n\n[下载配套 Data]({data_url})。下载全部三个分卷和两个校验文件，'
        '按本页 `RESOURCE-INSTALL.txt` 合并并导入。\n\n'
        + links + '\n\n'
        f'资源标识：`{identity}`。已导入相同资源时无需重复下载或导入。\n\n'
        '首次着色器编译参考：iPhone 17 Pro Max 约 6 分钟。当前版本包尚未进行真机运行验证。\n')
    return bilingual(english, chinese)


def data(repo, manifest):
    english = (
        f"Game data **{manifest['game_version']}**, Switch update **{manifest['switch_version']}**.\n\n"
        'Download all three resource parts and both checksum files, then follow '
        '`RESOURCE-INSTALL.txt` to combine and import them.\n\n'
        f"Resource ID: `{manifest['resource_id']}`.\n\n"
        f'For detailed instructions, see the [README](https://github.com/{repo}#readme).\n\n'
        'Download a matching IPA from an app Release. Multiple IPA versions can reuse this data; '
        'keep these assets available so their download links continue to work.\n')
    chinese = (
        f"游戏资源 **{manifest['game_version']}**，Switch 更新 **{manifest['switch_version']}**。\n\n"
        '下载全部三个资源分卷及两个校验文件，按 `RESOURCE-INSTALL.txt` 合并并导入。\n\n'
        f"资源标识：`{manifest['resource_id']}`。\n\n"
        f'详细使用方式请参考 [中文 README](https://github.com/{repo}/blob/main/README.zh-CN.md)。\n\n'
        '配套 IPA 在各版本 Release 中下载。此资源版本可供多个 IPA 版本复用，请保留其附件。\n')
    return bilingual(english, chinese)


def legacy(repo, archive='Legacy-Device-Pack.zip'):
    english = (
        'Additional textures for A14–A16 devices, shared by both system variants of the IPA.\n\n'
        f'Download `{archive}`, extract it, and copy the entire `Legacy Device Pack` folder '
        'into the app beside `D2R Mobile Resources`.\n\n'
        'Use an IPA Release that links to this pack. For detailed instructions, '
        f'see the [README](https://github.com/{repo}#readme).\n')
    chinese = (
        'A14–A16设备的配套贴图补充包，两种系统版本的 IPA 共用。\n\n'
        f'下载 `{archive}`，解压后把整个 `Legacy Device Pack` 文件夹与 '
        '`D2R Mobile Resources` 并排放进应用。\n\n'
        f'请使用引用本包的 IPA。详细使用方式参考 [中文 README](https://github.com/{repo}/blob/main/README.zh-CN.md)。\n')
    return bilingual(english, chinese)
