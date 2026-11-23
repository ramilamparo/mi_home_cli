"""English catalog: Chinese source string -> English.

Keys are the exact strings passed to `i18n.t()` (plus command docstrings and the
Chinese column names used as row keys). Placeholders must keep their names.
`tests/test_i18n.py` checks that every `t("...")` literal in the package has an
entry here and that placeholders match.
"""
from __future__ import annotations

CATALOG: dict[str, str] = {
    # ---- shared fragments ------------------------------------------------
    "、": ", ",
    "是": "yes",
    "否": "no",
    "开": "on",
    "关": "off",
    "无": "none",
    "未知": "unknown",
    "未知昵称": "unknown nickname",
    "成功": "OK",
    "可选值：": "Allowed values: ",
    "区域：": "Region: ",
    "[dim]提示：{hint}[/dim]": "[dim]Hint: {hint}[/dim]",
    "[dim]（空）[/dim]": "[dim](empty)[/dim]",
    "\n已取消": "\nCancelled",
    # ---- column names / output keys --------------------------------------
    "已登录": "Logged in",
    "配置项": "Key",
    "当前值": "Value",
    "说明": "Description",
    "家庭": "Home",
    "房间": "Room",
    "房间数": "Rooms",
    "设备数": "Devices",
    "共享": "Shared",
    "别名": "Alias",
    "设备": "Device",
    "检查项": "Check",
    "结果": "Result",
    "支持直连": "LAN capable",
    "原因": "Reason",
    "可达": "Reachable",
    "提示": "Hint",
    "延迟": "Latency",
    "设备时间戳": "Device stamp",
    "上次局域网调用": "Last LAN call",
    "型号": "Model",
    "在线": "Online",
    "应答用时": "Reply time",
    "动作": "Action",
    "返回": "Output",
    "属性": "Property",
    "值": "Value",
    "旧值": "Old value",
    "新值": "New value",
    "写入值": "Value to write",
    "入参": "Inputs",
    "服务": "Service",
    "权限": "Access",
    "类型": "Type",
    "取值": "Values",
    "单位": "Unit",
    "大小": "Size",
    "缓存于": "Cached at",
    "名称": "Name",
    "时间": "Time",
    "变化": "Change",
    "厂商": "Manufacturer",
    "局域网 IP": "LAN IP",
    "固件版本": "Firmware version",
    "固件": "Firmware",
    "子设备": "Sub-device",
    # ---- cli/app.py ------------------------------------------------------
    "命令行控制米家设备": "Control Xiaomi Home (Mi Home) devices from the command line",
    "使用哪个 profile": "Profile to use",
    "输出格式": "Output format",
    "单次请求超时（秒）": "Timeout per request (seconds)",
    "只解析和校验，不真的下发": "Parse and validate only; do not send anything",
    "控制通道：cloud（默认）/ auto（局域网优先，回落云端）/ lan": (
        "Control channel: cloud (default) / auto (LAN first, fall back to cloud) / lan"
    ),
    "忽略默认家庭，跨所有家庭操作": "Ignore the default home and work across all homes",
    "写入后回读确认真实状态（默认不回读，省一次请求）": (
        "Read back after writing to confirm the real state "
        "(off by default, saves one request)"
    ),
    "写入后回读确认真实状态": "Read back after writing to confirm the real state",
    "打印版本。": "Print the version.",
    "检查登录所需的环境（端口、域名解析、网络、时钟）。": (
        "Check the environment needed for login (port, DNS, network, clock)."
    ),
    # ---- cli/auth.py -----------------------------------------------------
    "登录与凭据管理": "Login and credential management",
    "多账号/多区域配置": "Multiple accounts / regions",
    "已过期": "expired",
    "{minutes} 分": "{minutes} min",
    "{days} 天 {hours} 小时": "{days} d {hours} h",
    "{hours} 小时 {minutes} 分": "{hours} h {minutes} min",
    "拿到授权码（来自{v0}），正在换取 token…": (
        "Got the authorization code (from {v0}), exchanging it for a token…"
    ),
    "本地回调": "the local callback",
    "粘贴": "pasted input",
    "登录成功：{v0}（uid {v1}，区域 {region}，profile {name}）": (
        "Logged in: {v0} (uid {v1}, region {region}, profile {name})"
    ),
    "凭据已保存到 {auth_path}（权限 0600）": "Credentials saved to {auth_path} (mode 0600)",
    "有效期约 {v0}，到期前会自动续期": (
        "Valid for about {v0}; it is renewed automatically before it expires"
    ),
    "[bold]正在获取二维码…[/bold]": "[bold]Fetching the QR code…[/bold]",
    "没能自动完成扫码授权（首次登录往往要手动点一次「同意并关联」）。": (
        "Could not finish the QR authorization automatically (the first login usually "
        "needs one manual tap on \"Agree and link\")."
    ),
    "用浏览器打开下面这个地址，登录小米账号并点「同意并关联」完成授权：": (
        "Open the address below in a browser, sign in to your Xiaomi account and "
        "click \"Agree and link\" to authorize:"
    ),
    "完成后二选一：把浏览器跳转后地址栏里的整段地址粘到这里回车立刻换 token，或直接回车让我重新生成扫码二维码（Ctrl-C 取消）：": (
        "When done, either paste the full address from the browser's address bar "
        "(after the redirect) here and press Enter to exchange the token right away, "
        "or just press Enter to generate a new QR code (Ctrl-C to cancel):"
    ),
    "[dim]已通过 mDNS 把 {REDIRECT_HOST} 指向 {address}[/dim]": (
        "[dim]Pointed {REDIRECT_HOST} at {address} via mDNS[/dim]"
    ),
    "{region}（{v0}）": "{region} ({v0})",
    "已刷新，有效期约 {v0}": "Refreshed; valid for about {v0}",
    "已清除 profile `{name}` 的凭据": "Removed the credentials of profile `{name}`",
    "默认 profile 已设为 `{name}`": "Default profile set to `{name}`",
    "已删除 profile `{name}`": "Deleted profile `{name}`",
    "未知区域 `{region}`，可选：{v0}": "Unknown region `{region}`; choose from: {v0}",
    "redirect_uri 的 host 不是 {REDIRECT_HOST}:{REDIRECT_PORT}，小米服务端会拒绝（invalid redirect uri）": (
        "The redirect_uri host is not {REDIRECT_HOST}:{REDIRECT_PORT}; Xiaomi's server "
        "will reject it (invalid redirect uri)"
    ),
    "[bold]1.[/bold] 在浏览器里打开下面的链接，用小米账号登录并授权：": (
        "[bold]1.[/bold] Open the link below in a browser, sign in with your Xiaomi "
        "account and authorize:"
    ),
    "[bold]用小米 App 扫码：[/bold]我的 → 点右上角扫一扫（或设置 → 小米账号），扫码后在手机上点「确认登录」。": (
        "[bold]Scan with a Xiaomi app:[/bold] Profile → the scan icon in the top-right "
        "corner (or Settings → Xiaomi Account), then tap \"Confirm login\" on the phone."
    ),
    "[dim]首次登录还会弹一个授权页，点「同意并关联 / Agree and link」授权即可（以后再扫就免了）；点完这里会自动继续。[/dim]": (
        "[dim]The first login also shows an authorization page: tap \"Agree and link\" "
        "(not needed for later scans); this command continues automatically "
        "afterwards.[/dim]"
    ),
    "[dim]也可以把下面这段地址自行转成二维码后扫：[/dim]": (
        "[dim]Or turn the address below into a QR code yourself and scan that:[/dim]"
    ),
    "[dim]二维码有效期约 {v0} 秒，正在等待确认…[/dim]": (
        "[dim]The QR code is valid for about {v0} seconds; waiting for confirmation…[/dim]"
    ),
    "扫码已确认，正在换取 token…": "Scan confirmed, exchanging for a token…",
    "[dim]或用手机扫这个二维码打开上面的页面：[/dim]": (
        "[dim]Or scan this QR code with your phone to open the page above:[/dim]"
    ),
    "授权完成后，重新运行 `mi auth login --scan` 即可（这次不用再授权）。": (
        "Once authorized, run `mi auth login --scan` again (no authorization needed "
        "this time)."
    ),
    "没有找到上一次登录的记录，先执行 `mi auth login`": (
        "No record of a previous login attempt; run `mi auth login` first"
    ),
    "上一次登录是 {v0} 分钟前发起的，授权码可能已过期": (
        "The previous login was started {v0} minutes ago; the authorization code may "
        "have expired"
    ),
    "{REDIRECT_PORT} 端口被占用（本机在跑 Home Assistant？），只能用粘贴方式登录": (
        "Port {REDIRECT_PORT} is in use (is Home Assistant running on this machine?); "
        "login is only possible by pasting"
    ),
    "[dim]{REDIRECT_HOST} 已解析到本机（{v0}）[/dim]": (
        "[dim]{REDIRECT_HOST} resolves to this machine ({v0})[/dim]"
    ),
    "{REDIRECT_HOST} 解析到 {v0}，不是本机；回调会落到那台机器上": (
        "{REDIRECT_HOST} resolves to {v0}, which is not this machine; the callback "
        "will land on that machine"
    ),
    "[dim]mDNS 不可用（{failure}），可以直接用粘贴方式[/dim]": (
        "[dim]mDNS unavailable ({failure}); you can simply paste instead[/dim]"
    ),
    "profile `{name}` 尚未登录": "Profile `{name}` is not logged in",
    "有效（{v0}）": "valid ({v0})",
    "本来就没有登录信息": "There were no login credentials to begin with",
    "整个 profile 目录": "the entire profile directory",
    "登录凭据": "the login credentials",
    "确认删除 {name} 的{target}？": "Delete {target} of {name}?",
    "profile `{name}` 不存在": "Profile `{name}` does not exist",
    "确认删除 profile `{name}` 的全部数据？": "Delete all data of profile `{name}`?",
    "等待授权超时（{v0} 秒）": "Timed out waiting for authorization ({v0} seconds)",
    "没能自动打开浏览器，请手工复制上面的链接": (
        "Could not open a browser automatically; copy the link above by hand"
    ),
    "[bold]2.[/bold] 授权后浏览器会跳回 {redirect}，本机已在 8123 端口等着接收。": (
        "[bold]2.[/bold] After authorizing, the browser is redirected to {redirect}; "
        "this machine is listening on port 8123 to receive it."
    ),
    "[bold]3.[/bold] 如果那个页面打不开（说明 homeassistant.local 没指向本机），把浏览器地址栏里的整段地址粘到这里回车：": (
        "[bold]3.[/bold] If that page does not load (homeassistant.local does not "
        "point at this machine), paste the full address from the browser's address "
        "bar here and press Enter:"
    ),
    "[bold]2.[/bold] 授权后浏览器会跳到 {redirect}，这个地址多半打不开——没关系，": (
        "[bold]2.[/bold] After authorizing, the browser is redirected to {redirect}; "
        "that address will most likely fail to load, which is fine."
    ),
    "[bold]3.[/bold] 直接把浏览器地址栏里的整段地址粘到这里回车：": (
        "[bold]3.[/bold] Paste the full address from the browser's address bar here "
        "and press Enter:"
    ),
    "授权码还在有效期内的话可以直接重试：": (
        "If the authorization code is still valid you can retry directly:"
    ),
    "scan_device_name `{name}` 含非 ASCII 字符，无法作为设备名，已用默认名": (
        "scan_device_name `{name}` contains non-ASCII characters and cannot be used "
        "as a device name; using the default name"
    ),
    "[dim]二维码有横纹或发虚？把终端行距（line spacing）调到 1.0 就实心了；或直接用下面的图片链接。[/dim]": (
        "[dim]QR code striped or blurry? Set the terminal line spacing to 1.0 to make "
        "it solid, or use the image link below.[/dim]"
    ),
    "无法在终端里渲染二维码，请改用下面的图片链接扫码。": (
        "Cannot render the QR code in this terminal; scan it from the image link below."
    ),
    "[dim]终端里的二维码扫不出？用浏览器打开这个地址看图再扫：[/dim]": (
        "[dim]Cannot scan the QR code in the terminal? Open this address in a browser "
        "and scan the image:[/dim]"
    ),
    "监听 {REDIRECT_PORT} 失败：{err}": "Failed to listen on {REDIRECT_PORT}: {err}",
    "用 `mi auth login --manual` 手工粘贴回调地址": (
        "Use `mi auth login --manual` to paste the callback URL by hand"
    ),
    "标准输入已结束，也没有本地回调可用；请在交互式终端里运行，或用管道传入回调地址": (
        "Standard input is closed and no local callback is available; run in an "
        "interactive terminal, or pipe the callback URL in"
    ),
    "回调的 state 与本次登录不符，已忽略": (
        "The callback's state does not match this login; ignored"
    ),
    "state 不匹配，可能不是本次登录的回调，请重新登录": (
        "State mismatch; this may not be the callback of this login. Please log in again"
    ),
    "账号信息获取失败（不影响登录）：{message}": (
        "Could not fetch account info (login is unaffected): {message}"
    ),
    "好，重新生成扫码二维码…": "OK, generating a new QR code…",
    "再粘一次，或直接回车重新扫码：": "Paste again, or press Enter to scan again:",
    "再试一次，或按 Ctrl-C 退出：": "Try again, or press Ctrl-C to quit:",
    "请重新执行 `mi auth login`": "Run `mi auth login` again",
    "粘贴的内容里没有 state，跳过校验": (
        "The pasted text has no state; skipping the check"
    ),
    "用小米账号扫码登录（终端显示二维码，无需浏览器）": (
        "Log in by scanning a QR code with your Xiaomi account "
        "(QR code shown in the terminal, no browser needed)"
    ),
    "不监听端口，只手工粘贴回调地址": (
        "Do not listen on a port; only paste the callback URL by hand"
    ),
    "不自动打开浏览器": "Do not open a browser automatically",
    "不广播 mDNS": "Do not advertise via mDNS",
    "自定义 redirect_uri（host 必须是 homeassistant.local:8123）": (
        "Custom redirect_uri (the host must be homeassistant.local:8123)"
    ),
    "自定义 device_id（排查用）": "Custom device_id (for troubleshooting)",
    "等待授权的秒数": "Seconds to wait for authorization",
    "已授权过则跳过确认页": "Skip the confirmation page if already authorized",
    "授权码，或浏览器回调地址（整段粘贴）": (
        "Authorization code, or the browser callback URL (paste it whole)"
    ),
    "调用一次云端接口验证 token 是否真的有效": (
        "Call the cloud API once to verify the token really works"
    ),
    "连同设备清单、spec 缓存一起删除": "Also delete the device list and spec cache",
    "不询问": "Do not ask for confirmation",
    "用小米账号登录。": "Log in with a Xiaomi account.",
    "用授权码换 token。\n\n登录时换 token 那一步失败（比如网络抖动）而授权码还没过期时，可以用这个\n命令重试，不必再走一遍浏览器；参数取自上一次 `mi auth login` 的记录。": (
        "Exchange an authorization code for a token.\n\n"
        "If the token exchange step of a login failed (e.g. a network glitch) and the\n"
        "authorization code has not expired yet, retry with this command instead of\n"
        "going through the browser again; parameters come from the last `mi auth login`."
    ),
    "查看当前登录状态。": "Show the current login status.",
    "立刻刷新 access_token。": "Refresh the access_token now.",
    "打印当前账号信息（实时查询）。": "Print the current account info (queried live).",
    "退出登录，删除本地凭据。": "Log out and delete the local credentials.",
    "列出所有 profile。": "List all profiles.",
    "设置默认 profile。": "Set the default profile.",
    "删除一个 profile 的全部本地数据。": "Delete all local data of a profile.",
    "打印配置目录位置。": "Print the location of the config directory.",
    # ---- cli/config.py ---------------------------------------------------
    "默认配置": "Default settings",
    "默认 profile": "Default profile",
    "默认区域：": "Default region: ",
    "默认输出格式：table/json/yaml/plain": "Default output format: table/json/yaml/plain",
    "默认家庭（等价于 mi home use）": "Default home (same as mi home use)",
    "默认控制通道：cloud / auto / lan": "Default control channel: cloud / auto / lan",
    "扫码登录在小米「登录设备」里显示的名字（默认 mi-home-cli/版本）": (
        "Name shown under Xiaomi's \"logged-in devices\" for QR logins "
        "(default: mi-home-cli/version)"
    ),
    "界面语言：zh / en（不设则跟随系统 locale）": (
        "Interface language: zh / en (follows the system locale when unset)"
    ),
    "{name}（{v0}）": "{name} ({v0})",
    "[dim]配置文件：{v0}[/dim]": "[dim]Config file: {v0}[/dim]",
    "已清除 {key}": "Cleared {key}",
    "未知配置项 `{key}`": "Unknown config key `{key}`",
    "{key} 本来就没设": "{key} was not set",
    "未知区域 `{value}`，可选：{v0}": "Unknown region `{value}`; choose from: {v0}",
    "未知通道 `{value}`，可选：{v0}": "Unknown channel `{value}`; choose from: {v0}",
    "未知语言 `{value}`，可选：{v0}": "Unknown language `{value}`; choose from: {v0}",
    "设备名不能为空": "The device name must not be empty",
    "可配置：": "Available keys: ",
    "未知输出格式 `{value}`": "Unknown output format `{value}`",
    "设备名只能用 ASCII 字符（它会作为 HTTP User-Agent 发送，带不了中文等非 ASCII 字符）": (
        "The device name must be ASCII only (it is sent as the HTTP User-Agent, which "
        "cannot carry non-ASCII characters)"
    ),
    "列出所有配置项。": "List all config keys.",
    "读一个配置项。": "Read a config key.",
    "设置一个配置项。": "Set a config key.",
    "清掉一个配置项。": "Unset a config key.",
    "打印配置目录。": "Print the config directory.",
    # ---- cli/device.py ---------------------------------------------------
    "设备清单": "Device list",
    "设备别名": "Device aliases",
    "[dim]已同步 {v0} 台设备、{v1} 个家庭[/dim]": "[dim]Synced {v0} device(s), {v1} home(s)[/dim]",
    "同步完成，{v0} 台设备，耗时 {v1:.1f}s": "Sync complete: {v0} device(s) in {v1:.1f}s",
    "{label} → 别名 `{alias}`": "{label} → alias `{alias}`",
    "已删除别名 `{alias}`": "Deleted alias `{alias}`",
    "默认家庭已设为「{home_name}」": "Default home set to \"{home_name}\"",
    "选择默认家庭：": "Choose the default home:",
    "  0. 取消默认家庭（所有家庭都可见）": "  0. No default home (all homes visible)",
    "输入编号": "Enter a number",
    "[dim]本地还没有设备缓存，正在同步…[/dim]": "[dim]No local device cache yet, syncing…[/dim]",
    "，只看「{name}」，加 --all-homes 看全部": (
        ", showing only \"{name}\"; add --all-homes to see everything"
    ),
    "[dim]共 {n_devices} 台{note}[/dim]": "[dim]{n_devices} device(s) in total{note}[/dim]",
    "{label} 没有局域网 token": "{label} has no LAN token",
    "别名 `{alias}` 不存在": "Alias `{alias}` does not exist",
    "已取消默认家庭，现在所有家庭的设备都可见": (
        "Default home cleared; devices of all homes are now visible"
    ),
    "当前没有设默认家庭，所有家庭的设备都可见": (
        "No default home is set; devices of all homes are visible"
    ),
    "还没有设默认家庭，所有家庭的设备都可见": (
        "No default home has been set; devices of all homes are visible"
    ),
    "没有可选的家庭": "No homes to choose from",
    "select 需要交互式终端": "select needs an interactive terminal",
    "  {index}. {home_name}{mark}（{v0} 台设备）": "  {index}. {home_name}{mark} ({v0} device(s))",
    "编号 {choice} 超出范围（0–{n_homes}）": "Number {choice} is out of range (0–{n_homes})",
    "默认家庭「{name}」里没有 `{ref}`，但在 {names} 找到了": (
        "`{ref}` is not in the default home \"{name}\", but was found in {names}"
    ),
    "（已不在清单里）": "(no longer in the device list)",
    "当前默认家庭：{name}（{id}）": "Current default home: {name} ({id})",
    "先跑 `mi device sync` 从云端同步": "Run `mi device sync` first to sync from the cloud",
    "脚本里请用 `mi home use <家庭>` 或 `mi home unset`": (
        "In scripts use `mi home use <home>` or `mi home unset`"
    ),
    "设备缓存是 {v0} 天前的，需要的话跑 `mi device sync` 刷新": (
        "The device cache is {v0} day(s) old; run `mi device sync` to refresh if needed"
    ),
    "{home_name}/{v0} 的 {label}": "{label} in {home_name}/{v0}",
    "加 --all-homes 跨家庭操作，或用 `mi home use` 换默认家庭": (
        "Add --all-homes to work across homes, or switch the default home with "
        "`mi home use`"
    ),
    "限定家庭": "Only this home",
    "限定房间": "Only this room",
    "限定型号": "Only this model",
    "按名称/型号搜索": "Search by name / model",
    "只看在线/离线设备": "Only online / offline devices",
    "多显示 did、IP、固件": "Also show did, IP and firmware",
    "先从云端刷新缓存": "Refresh the cache from the cloud first",
    "设备名称、别名或 did": "Device name, alias or did",
    "明文显示（默认打码）": "Show in plain text (masked by default)",
    "设备名称或 did": "Device name or did",
    "要设置的别名": "Alias to set",
    "家庭名称或 home_id，不给则显示当前默认": (
        "Home name or home_id; shows the current default when omitted"
    ),
    "取消默认家庭，回到全部家庭": "Clear the default home and go back to all homes",
    "列出设备。": "List devices.",
    "看一台设备的详情。": "Show the details of one device.",
    "从云端重新拉取家庭、房间、设备清单。": (
        "Re-fetch homes, rooms and the device list from the cloud."
    ),
    "打印设备的局域网 token。": "Print a device's LAN token.",
    "给设备起个短名字。": "Give a device a short name.",
    "列出所有别名。": "List all aliases.",
    "删除别名。": "Delete an alias.",
    "列出家庭。": "List homes.",
    "设置默认家庭。设了之后设备解析、device list、room list 都只看这个家庭。": (
        "Set the default home. Once set, device lookup, device list and room list "
        "only look at this home."
    ),
    "取消默认家庭，回到全部家庭（等同 `mi home use --clear`）。": (
        "Clear the default home and go back to all homes "
        "(same as `mi home use --clear`)."
    ),
    "交互式选择默认家庭（也可以选择取消默认家庭）。": (
        "Pick the default home interactively (or choose to clear it)."
    ),
    "列出房间。": "List rooms.",
    # ---- cli/doctor.py ---------------------------------------------------
    "TCP + TLS 均可（{elapsed:.0f}ms）{note}": "TCP + TLS both OK ({elapsed:.0f}ms){note}",
    "；注意解析到 {v0}，流量经过代理": "; note it resolves to {v0}, traffic goes through a proxy",
    "偏差 {skew:.0f} 秒": "skew {skew:.0f} s",
    "{REDIRECT_PORT} 端口": "Port {REDIRECT_PORT}",
    "系统时钟": "System clock",
    "本机时钟与服务端相差 {skew:.0f} 秒": (
        "The local clock differs from the server by {skew:.0f} seconds"
    ),
    "凭据文件权限": "Credential file permissions",
    "凭据文件": "Credential file",
    "未登录（{auth_path} 不存在）": "not logged in ({auth_path} does not exist)",
    "登录态": "Login state",
    "{v0} / {region} / 剩余 {v1} 秒": "{v0} / {region} / {v1} s left",
    "可用": "available",
    "被占用，登录只能用粘贴方式": "in use; login is only possible by pasting",
    "{REDIRECT_HOST} 解析": "{REDIRECT_HOST} resolution",
    "解析不到；登录时会尝试 mDNS，不行就用粘贴方式": (
        "does not resolve; login will try mDNS and otherwise fall back to pasting"
    ),
    "已安装，可自动广播 mDNS": "installed; mDNS can be advertised automatically",
    "域名解析失败：{err}": "DNS resolution failed: {err}",
    "TCP 通（{elapsed:.0f}ms）但证书校验失败：{v0}": (
        "TCP OK ({elapsed:.0f}ms) but certificate verification failed: {v0}"
    ),
    "连接超时，出口多半封了这个端口（mi watch 会用不了）": (
        "connection timed out; this port is probably blocked outbound "
        "(mi watch will not work)"
    ),
    "响应里没有 Date 头": "the response has no Date header",
    "无法判断：{err}": "cannot tell: {err}",
    "指向本机（{v0}）": "points at this machine ({v0})",
    "指向 {v0}，不是本机，回调会落到那台机器": (
        "points at {v0}, not this machine; the callback will land on that machine"
    ),
    "未安装，装了可提高自动回调成功率：uv sync --extra mdns": (
        "not installed; installing it improves the automatic callback success rate: "
        "uv sync --extra mdns"
    ),
    "；域名解析到 {v0}，是代理的 fake-IP，给它加条直连规则": (
        "; the host resolves to {v0}, a proxy fake-IP: add a direct rule for it"
    ),
    "，其他用户可读，建议 chmod 600": ", readable by other users; chmod 600 recommended",
    "（用 certifi 的证书库）": " (using certifi's CA bundle)",
    "TLS 握手失败：{err}": "TLS handshake failed: {err}",
    # ---- cli/lan.py ------------------------------------------------------
    "局域网直连": "Direct LAN control",
    "[dim]{n_rows} 台应答，地址已缓存到 {lan_path}[/dim]": (
        "[dim]{n_rows} device(s) replied; addresses cached in {lan_path}[/dim]"
    ),
    "同一网段？设备在线？先跑 `mi lan discover`": (
        "Same subnet? Device online? Run `mi lan discover` first"
    ),
    "失败：{reason}（{v0}）": "failed: {reason} ({v0})",
    "auto 模式会直接走云端；`mi lan discover` 可清除这个标记": (
        "auto mode goes straight to the cloud; `mi lan discover` clears this mark"
    ),
    "[dim]{supported} / {n_rows} 台支持局域网直连[/dim]": (
        "[dim]{supported} / {n_rows} device(s) support direct LAN control[/dim]"
    ),
    "没有设备应答": "No device replied",
    "[dim]检查：和设备同一网段？路由器开了 AP 隔离？macOS 要在 系统设置 → 隐私与安全性 → 本地网络 放行终端[/dim]": (
        "[dim]Check: same subnet as the devices? AP isolation enabled on the router? "
        "On macOS allow the terminal under System Settings → Privacy & Security → "
        "Local Network[/dim]"
    ),
    "没有局域网 token": "no LAN token",
    "connect_type 不在 {v0} 内（走网关的设备）": (
        "connect_type is not one of {v0} (the device goes through a gateway)"
    ),
    "{elapsed_ms:.0f}ms（广播应答用时，非往返延迟）": (
        "{elapsed_ms:.0f}ms (broadcast reply time, not round-trip latency)"
    ),
    "局域网上找不到 {label}，先跑 `mi lan discover`": (
        "Cannot find {label} on the LAN; run `mi lan discover` first"
    ),
    "--params 不是合法 JSON：{err}": "--params is not valid JSON: {err}",
    "（不在设备清单里）": "(not in the device list)",
    "等待应答的秒数": "Seconds to wait for replies",
    "广播地址，默认 255.255.255.255": "Broadcast address, default 255.255.255.255",
    "设备名称、别名或 did（名字带空格要加引号）": (
        "Device name, alias or did (quote names containing spaces)"
    ),
    "miIO 方法名，如 miIO.info / get_properties": (
        "miIO method name, e.g. miIO.info / get_properties"
    ),
    "参数，JSON 格式": "Parameters, as JSON",
    "等待秒数": "Seconds to wait",
    "广播扫描局域网上的米家设备，并和设备清单对上号。": (
        "Broadcast-scan the LAN for Mi Home devices and match them to the device list."
    ),
    "看一台设备能不能直连、在哪个 IP、延迟多少。": (
        "Check whether a device can be reached directly, at which IP and how fast."
    ),
    "直接对设备发一条 miIO 请求。\n\n排查用：`miIO.info` 每台 miIO 设备都实现，能用来判断「协议通不通」和\n「这个方法设备支不支持」是两回事。": (
        "Send a raw miIO request straight to a device.\n\n"
        "For troubleshooting: every miIO device implements `miIO.info`, so it tells\n"
        "\"is the protocol working\" apart from \"does the device support this method\"."
    ),
    "列出设备清单里哪些设备理论上支持局域网直连。": (
        "List which devices in the device list should support direct LAN control."
    ),
    # ---- cli/prop.py -----------------------------------------------------
    "失败（code={code}）": "failed (code={code})",
    "这里需要一台具体设备，不能只给 urn": "A specific device is required here, not just a urn",
    "{label}（{location}）": "{label} ({location})",
    "[dim]--dry-run，只解析不下发：[/dim]": "[dim]--dry-run: parsed only, nothing sent:[/dim]",
    "云端读回的值还没跟上，可能是设备上报有延迟；隔几秒再 `mi get` 看看": (
        "The value read back from the cloud has not caught up yet, probably because "
        "the device reports with a delay; try `mi get` again in a few seconds"
    ),
    "{full_name} 需要 {v0} 个入参（{v1}），给了 {n_raw_values} 个": (
        "{full_name} takes {v0} input(s) ({v1}), but {n_raw_values} given"
    ),
    "[dim]--dry-run：{label} {full_name}（{ref}）入参 {parsed}[/dim]": (
        "[dim]--dry-run: {label} {full_name} ({ref}) inputs {parsed}[/dim]"
    ),
    "{label} 没有可写的开关属性": "{label} has no writable on/off property",
    "取反当前状态": "toggle the current state",
    "[dim]--dry-run：{label}（{location}） → {full_name}（{ref}）= {target_value}[/dim]": (
        "[dim]--dry-run: {label} ({location}) → {full_name} ({ref}) = {target_value}[/dim]"
    ),
    "{label} 指令已下发，但回读仍是{v0}，可能是上报延迟": (
        "{label}: command sent, but it still reads back as {v0}; the report may be "
        "delayed"
    ),
    "{label} 已打开": "{label} turned on",
    "{label} 已关闭": "{label} turned off",
    "已接受": "accepted",
    "设备不在线": "device is offline",
    "设备不支持这个属性": "the device does not support this property",
    "属性不可写": "the property is not writable",
    "设备拒绝（可能被童锁/物理开关限制）": (
        "rejected by the device (possibly a child lock or a physical switch)"
    ),
    "这些属性不可读：{v0}": "These properties are not readable: {v0}",
    "{label} 没有可读属性": "{label} has no readable properties",
    "`{item}` 不是 属性=值 的形式": "`{item}` is not in property=value form",
    "{full_name} 不可写": "{full_name} is not writable",
    "已下发，回读仍是 {v0}": "sent, still reads back as {v0}",
    "{label} 支持的动作": "Actions supported by {label}",
    "用 --in 依次传入，顺序按上面列的入参": (
        "Pass them one by one with --in, in the order listed above"
    ),
    "用 `mi spec show` 看看它支持什么，再用 `mi set`": (
        "See what it supports with `mi spec show`, then use `mi set`"
    ),
    "{label} 开失败：{reason}": "Failed to turn on {label}: {reason}",
    "{label} 关失败：{reason}": "Failed to turn off {label}: {reason}",
    "权限是 {v0}": "Its access is {v0}",
    "读不到 {label} 的当前开关状态": "Cannot read the current on/off state of {label}",
    "属性，如 on / light.brightness / 2.1": "Property, e.g. on / light.brightness / 2.1",
    "属性=值，可以写多个，如 on=true brightness=60": (
        "property=value, repeatable, e.g. on=true brightness=60"
    ),
    "动作名，不写则列出所有动作": "Action name; lists all actions when omitted",
    "按顺序传入参，可重复": "Input arguments in order, repeatable",
    "读属性。不指定属性就读所有可读属性。": (
        "Read properties. Reads every readable property when none is given."
    ),
    "写属性。": "Write properties.",
    "调用动作。不指定动作名就列出这台设备支持的动作。": (
        "Call an action. Lists the actions the device supports when no name is given."
    ),
    "打开设备。": "Turn a device on.",
    "关闭设备。": "Turn a device off.",
    "切换开关。": "Toggle a device on/off.",
    # ---- cli/semantic.py -------------------------------------------------
    "{label} 没有可读的状态属性": "{label} has no readable state properties",
    "--open / --close / --stop 只能给一个": (
        "Only one of --open / --close / --stop may be given"
    ),
    "开灯 / 关灯": "Turn the light on / off",
    "亮度，一般是 1~100": "Brightness, usually 1~100",
    "色温，单位开尔文，如 4000": "Color temperature in kelvin, e.g. 4000",
    "颜色，如 #ff8800 或 红": "Color, e.g. #ff8800 or red",
    "模式，如 日光 / 月光": "Mode, e.g. Day / Night",
    "开机 / 关机": "Power on / off",
    "模式，如 制冷 / 制热 / 自动": "Mode, e.g. Cool / Heat / Auto",
    "目标温度": "Target temperature",
    "风速挡位": "Fan level",
    "打开": "Open",
    "关闭": "Close",
    "停住": "Stop",
    "开合百分比 0~100": "Position in percent, 0~100",
    "开 / 关": "On / off",
    "模式": "Mode",
    "摇头": "Oscillation",
    "控制灯。不带选项时显示当前状态。": (
        "Control a light. Shows the current state when no option is given."
    ),
    "控制空调、暖风机等温控设备。不带选项时显示当前状态。": (
        "Control air conditioners, heaters and other climate devices. Shows the "
        "current state when no option is given."
    ),
    "控制窗帘等开合类设备。不带选项时显示当前状态。": (
        "Control curtains and other open/close devices. Shows the current state when "
        "no option is given."
    ),
    "控制风扇、净化器等带挡位的设备。不带选项时显示当前状态。": (
        "Control fans, purifiers and other devices with levels. Shows the current "
        "state when no option is given."
    ),
    # ---- cli/spec_cmd.py -------------------------------------------------
    "设备能力（MIoT spec）": "Device capabilities (MIoT spec)",
    "spec 缓存": "Spec cache",
    "已清除 {count} 份 spec 缓存": "Cleared {count} cached spec(s)",
    "设备名称、别名、did 或 urn": "Device name, alias, did or urn",
    "只看某个服务": "Only this service",
    "只看可读属性": "Only readable properties",
    "只看可写属性": "Only writable properties",
    "改为列出动作": "List actions instead",
    "忽略缓存重新拉取": "Ignore the cache and fetch again",
    "关键词，匹配名称和说明": "Keyword, matched against names and descriptions",
    "列出设备的属性（或动作）。": "List a device's properties (or actions).",
    "在一台设备的属性和动作里搜关键词。": (
        "Search a device's properties and actions for a keyword."
    ),
    "输出完整 spec，方便喂给脚本。": "Dump the full spec, handy for feeding scripts.",
    "看看缓存了哪些 spec。": "Show which specs are cached.",
    "清空 spec 缓存。": "Clear the spec cache.",
    # ---- cli/watch.py ----------------------------------------------------
    "[dim]首次运行，正在拉取 {n_missing} 份 spec…[/dim]": (
        "[dim]First run, fetching {n_missing} spec(s)…[/dim]"
    ),
    "上下线": "Online state",
    "事件": "Event",
    "没有可盯的设备": "No devices to watch",
    "[dim]盯着 {n_targets} 台设备（{n_topics} 个订阅），Ctrl-C 退出[/dim]": (
        "[dim]Watching {n_targets} device(s) ({n_topics} subscription(s)), "
        "Ctrl-C to quit[/dim]"
    ),
    "，另有 {repeats} 条值未变的上报已跳过": (
        "; {repeats} more report(s) with unchanged values were skipped"
    ),
    "[dim]共 {seen} 条{tail}[/dim]": "[dim]{seen} message(s) in total{tail}[/dim]",
    "上线": "online",
    "离线": "offline",
    "spec 获取失败（{urn}）：{err}": "Failed to fetch spec ({urn}): {err}",
    "要盯的设备，不给就盯全部": "Devices to watch; all of them when omitted",
    "只看这些属性，可重复，如 --prop on": "Only these properties, repeatable, e.g. --prop on",
    "是否包含事件": "Include events",
    "是否包含上下线": "Include online/offline changes",
    "连值没变的周期上报也显示（默认只显示真的变化）": (
        "Also show periodic reports whose value did not change "
        "(only real changes by default)"
    ),
    "收到 N 条后退出": "Exit after N messages",
    "盯多少秒后退出": "Exit after this many seconds",
    "[dim]已连接[/dim]": "[dim]Connected[/dim]",
    "[yellow]连接断开，正在重连…[/yellow]": "[yellow]Connection lost, reconnecting…[/yellow]",
    "实时盯设备的属性变化、事件和上下线。Ctrl-C 退出。": (
        "Watch property changes, events and online/offline changes live. "
        "Ctrl-C to quit."
    ),
    # ---- core/callback.py ------------------------------------------------
    "没有输入内容": "Nothing was entered",
    "state 不匹配，这不是本次登录的回调；请重新执行 `mi auth login`": (
        "State mismatch: this is not the callback of this login; run `mi auth login` "
        "again"
    ),
    "登录成功": "Login successful",
    "可以关闭这个页面，回到终端。": "You can close this page and return to the terminal.",
    "登录失败": "Login failed",
    "未安装 zeroconf（uv sync --extra mdns）": "zeroconf is not installed (uv sync --extra mdns)",
    "注册 mDNS 失败：{err}": "Failed to register mDNS: {err}",
    "这段内容里没有 code 参数：{v0}": "This text has no code parameter: {v0}",
    "无法识别的内容，请粘贴完整的重定向 URL": (
        "Unrecognized input; paste the complete redirect URL"
    ),
    "缺少 code 参数": "missing code parameter",
    # ---- core/channel.py -------------------------------------------------
    "读取": "read",
    "写入": "write",
    "调用动作": "action call",
    "connect_type={connect_type}，不是直连路由器的设备（蓝牙 Mesh / ZigBee 要走网关）": (
        "connect_type={connect_type}: the device is not connected to the router "
        "directly (Bluetooth Mesh / ZigBee go through a gateway)"
    ),
    "[dim]局域网直连 {ip}（{elapsed_ms:.0f}ms）[/dim]": "[dim]Direct LAN {ip} ({elapsed_ms:.0f}ms)[/dim]",
    "{label} 不能局域网直连：{reason}": "{label} cannot be controlled over the LAN: {reason}",
    "[dim]跳过局域网（上次失败：{v0}），走云端[/dim]": (
        "[dim]Skipping the LAN (last failure: {v0}), using the cloud[/dim]"
    ),
    "局域网上找不到 {label}": "Cannot find {label} on the LAN",
    "确认在同一网段、设备在线；`mi lan discover` 看看扫得到谁": (
        "Make sure you are on the same subnet and the device is online; "
        "`mi lan discover` shows what can be found"
    ),
    "[dim]局域网{action}失败（{message}），改走云端[/dim]": (
        "[dim]LAN {action} failed ({message}), falling back to the cloud[/dim]"
    ),
    # ---- core/cloud.py / const.py ----------------------------------------
    "gethome 响应缺少 result": "The gethome response has no result",
    "device_list_page 响应缺少 result": "The device_list_page response has no result",
    "共享设备": "Shared devices",
    "中国大陆": "Mainland China",
    # ---- core/lan.py -----------------------------------------------------
    "token 长度不对（应为 32 个十六进制字符）：{token!r}": (
        "Wrong token length (expected 32 hex characters): {token!r}"
    ),
    "收到的不是 miIO 包": "Received something that is not a miIO packet",
    "校验失败，token 不对": "Checksum mismatch: wrong token",
    "{ip} 在 {v0:.0f} 秒内没有响应": "{ip} did not respond within {v0:.0f} seconds",
    "广播失败：{err}": "Broadcast failed: {err}",
    "`mi device sync` 刷新一下设备清单，token 会随重新配网变化": (
        "Refresh the device list with `mi device sync`; the token changes when a "
        "device is re-paired"
    ),
    "设备收不下这个包就不会回应答：token 不对（重新配网后会变，跑 `mi device sync` 刷新）、设备刚离线、或换了 IP（`mi lan discover` 重扫）": (
        "A device does not reply to a packet it cannot accept: wrong token (it changes "
        "after re-pairing; refresh with `mi device sync`), the device just went "
        "offline, or its IP changed (rescan with `mi lan discover`)"
    ),
    "设备返回错误：{v0}": "The device returned an error: {v0}",
    "发往 {ip} 失败：{err}": "Sending to {ip} failed: {err}",
    # ---- core/mqtt.py ----------------------------------------------------
    "连不上 broker（TCP 或 TLS 阶段失败）": "cannot reach the broker (failed at the TCP or TLS stage)",
    "broker 拒绝连接：{reason_code}": "the broker refused the connection: {reason_code}",
    "{host}:{BROKER_PORT} 的证书校验失败：{last_error}": (
        "Certificate verification for {host}:{BROKER_PORT} failed: {last_error}"
    ),
    "连接 {v0}:{BROKER_PORT} 超时（{timeout:.0f} 秒内没有任何回应）": (
        "Connecting to {v0}:{BROKER_PORT} timed out (no response within "
        "{timeout:.0f} seconds)"
    ),
    "系统根证书和 certifi 都验不过。若在用 Clash/Surge 这类代理，给 mqtt.io.mi.com 加条直连规则；确实需要中间人证书时用 {CA_BUNDLE_ENV}=/path/to/ca.pem 指定": (
        "Neither the system root certificates nor certifi could verify it. If you use "
        "a proxy such as Clash/Surge, add a direct rule for mqtt.io.mi.com; if you "
        "really need a man-in-the-middle certificate, set "
        "{CA_BUNDLE_ENV}=/path/to/ca.pem"
    ),
    "连接 {v0}:{BROKER_PORT} 失败：{failure}": "Connecting to {v0}:{BROKER_PORT} failed: {failure}",
    "多半是出口封了 8883 端口。用 `mi doctor` 看一眼，或 `nc -vz {host} 8883` 直接测": (
        "Port 8883 is probably blocked outbound. Check with `mi doctor`, or test "
        "directly with `nc -vz {host} 8883`"
    ),
    "系统根证书验不过，已改用 certifi 的证书库": (
        "The system root certificates failed to verify; switched to certifi's CA bundle"
    ),
    "连接 {host}:{BROKER_PORT} 失败：{kind}: {err}": (
        "Connecting to {host}:{BROKER_PORT} failed: {kind}: {err}"
    ),
    "broker 拒绝连接多半是凭据问题，先跑 `mi auth status --check`；TCP/TLS 阶段失败则是网络封了 8883 端口": (
        "A refused connection is usually a credential problem: run "
        "`mi auth status --check` first. A failure at the TCP/TLS stage means the "
        "network blocks port 8883"
    ),
    # ---- core/oauth.py ---------------------------------------------------
    "获取 token 失败（code={code}": "Failed to get a token (code={code}",
    "）：{description}": "): {description}",
    "授权码无效或已被用过，重新执行 `mi auth login`": (
        "The authorization code is invalid or already used; run `mi auth login` again"
    ),
    "换 token 的参数和授权时不一致（redirect_uri / client_id / device_id 三者必须完全相同），用 -v 看实际发出的请求": (
        "The token exchange parameters differ from the ones used to authorize "
        "(redirect_uri / client_id / device_id must all be identical); use -v to see "
        "the request actually sent"
    ),
    "凭据已失效，重新执行 `mi auth login`": (
        "The credentials are no longer valid; run `mi auth login` again"
    ),
    "获取 token 失败：未授权（401）": "Failed to get a token: unauthorized (401)",
    "获取 token 失败：HTTP {status_code}": "Failed to get a token: HTTP {status_code}",
    "响应缺少字段：{v0}": "The response is missing fields: {v0}",
    "获取账号信息失败：{v0}": "Failed to get account info: {v0}",
    "获取账号信息失败：{err}": "Failed to get account info: {err}",
    "连接 {url} 失败：{err}": "Connecting to {url} failed: {err}",
    "重新执行 `mi auth login`": "Run `mi auth login` again",
    "响应不是合法 JSON：{v0}": "The response is not valid JSON: {v0}",
    "账号信息响应不是合法 JSON": "The account info response is not valid JSON",
    # ---- core/qrlogin.py -------------------------------------------------
    "跳转次数过多，未能取到授权码": "Too many redirects; could not obtain an authorization code",
    "账号接口响应结构异常": "The account API returned an unexpected structure",
    "授权页没有跳转到登录页": "The authorization page did not redirect to the login page",
    "获取登录参数失败：{v0}": "Failed to get the login parameters: {v0}",
    "登录页响应缺少字段：{v0}": "The login page response is missing fields: {v0}",
    "获取二维码失败：{v0}": "Failed to get the QR code: {v0}",
    "扫码登录失败：{v0}": "QR login failed: {v0}",
    "连接 {netloc} 失败：{err}": "Connecting to {netloc} failed: {err}",
    "账号接口响应不是合法 JSON：{v0}": "The account API response is not valid JSON: {v0}",
    "小米可能调整了登录流程，改用 `mi auth login`（浏览器/粘贴）": (
        "Xiaomi may have changed the login flow; use `mi auth login` "
        "(browser / paste) instead"
    ),
    "小米可能调整了登录流程，改用 `mi auth login`": (
        "Xiaomi may have changed the login flow; use `mi auth login` instead"
    ),
    "扫码登录超时（二维码已失效）": "QR login timed out (the QR code has expired)",
    "跳转链没有回到回调地址就停了，可能需要在手机上完成授权确认": (
        "The redirect chain stopped before reaching the callback URL; you may need to "
        "confirm the authorization on your phone"
    ),
    "重新执行 `mi auth login --scan`": "Run `mi auth login --scan` again",
    "长轮询失败：{err}": "Long polling failed: {err}",
    "在手机上点「同意/授权」后重试，或改用 `mi auth login`": (
        "Tap \"Agree / Authorize\" on your phone and retry, or use `mi auth login` "
        "instead"
    ),
    # ---- core/registry.py ------------------------------------------------
    "没有找到家庭 `{ref}`": "Home `{ref}` not found",
    "没有找到设备 `{ref}`": "Device `{ref}` not found",
    "用 `mi home list` 看看有哪些家庭": "See the available homes with `mi home list`",
    "当前过滤条件下没有任何设备": "No devices match the current filters",
    "用 `mi device list` 看看有哪些设备，或 `mi device sync` 刷新缓存": (
        "See the available devices with `mi device list`, or refresh the cache with "
        "`mi device sync`"
    ),
    "`{ref}` 匹配到多个家庭：": "`{ref}` matches several homes: ",
    "用完整名称、别名或 did，也可以加 --home / --room 缩小范围": (
        "Use the full name, an alias or the did, or narrow it down with "
        "--home / --room"
    ),
    "`{ref}` 匹配到 {n_candidates} 台设备：\n": "`{ref}` matches {n_candidates} devices:\n",
    "  {location} / {label}（{model}，did {did}）": "  {location} / {label} ({model}, did {did})",
    # ---- core/semantic.py ------------------------------------------------
    "看不懂的颜色 `{text}`": "Unrecognized color `{text}`",
    "{label} 不支持 {option}（spec 里没有可写的 {v0}）": (
        "{label} does not support {option} (the spec has no writable {v0})"
    ),
    "{label} 的 {full_name} 里没有「{v0}」这一档": (
        "{full_name} of {label} has no \"{v0}\" value"
    ),
    "用 `mi spec show {label} --writable` 看看支持什么": (
        "See what is supported with `mi spec show {label} --writable`"
    ),
    "写 #ff8800 这样的十六进制，或 ": "Use hex such as #ff8800, or one of ",
    # ---- core/session.py -------------------------------------------------
    "access_token 已过期且没有 refresh_token": (
        "The access_token has expired and there is no refresh_token"
    ),
    "云端返回 401，登录已失效": "The cloud returned 401; the login is no longer valid",
    "{path} 返回 HTTP {status_code}": "{path} returned HTTP {status_code}",
    "{path} 返回 code={v0}：{v1}": "{path} returned code={v0}: {v1}",
    "请求 {path} 失败：{err}": "Request to {path} failed: {err}",
    "{path} 响应不是合法 JSON": "The {path} response is not valid JSON",
    # ---- core/spec.py ----------------------------------------------------
    "这台设备没有属性 `{ref}`": "This device has no property `{ref}`",
    "这台设备没有动作 `{ref}`": "This device has no action `{ref}`",
    "这台设备没有属性 {ref}": "This device has no property {ref}",
    "这台设备没有动作 {ref}": "This device has no action {ref}",
    "{full_name} 是开关量，`{raw}` 不认识": (
        "{full_name} is a boolean; `{raw}` is not understood"
    ),
    "{full_name} 不接受 `{raw}`": "{full_name} does not accept `{raw}`",
    "用 `mi spec show <设备>` 看看有哪些属性": (
        "See the available properties with `mi spec show <device>`"
    ),
    "用 `mi action list <设备>` 看看有哪些动作": (
        "See the available actions with `mi action list <device>`"
    ),
    "写 on/off、true/false、1/0 都行": "Use on/off, true/false or 1/0",
    "{full_name} 的取值范围是 {low}~{high}，给的是 {value}": (
        "{full_name} must be within {low}~{high}, got {value}"
    ),
    "miot-spec.org 没有返回有效的 spec：{urn}": (
        "miot-spec.org did not return a valid spec: {urn}"
    ),
    "{full_name} 要整数，给的是 `{raw}`": "{full_name} needs an integer, got `{raw}`",
    "{full_name} 要数字，给的是 `{raw}`": "{full_name} needs a number, got `{raw}`",
    "获取 spec 失败（{urn}）：{err}": "Failed to fetch spec ({urn}): {err}",
    "`{ref}` 匹配到多个属性：\n": "`{ref}` matches several properties:\n",
    "用 service.property 全名或 siid.piid": "Use the full service.property name or siid.piid",
    "`{ref}` 匹配到多个动作：\n": "`{ref}` matches several actions:\n",
    "用 service.action 全名或 siid.aiid": "Use the full service.action name or siid.aiid",
    "  {full_name}（{ref}，{description}）": "  {full_name} ({ref}, {description})",
    # ---- errors.py / store.py --------------------------------------------
    "运行 `mi auth login` 重新登录": "Run `mi auth login` to log in again",
    "未登录或登录已失效": "Not logged in, or the login has expired",
    "读取 {path} 失败：{err}": "Failed to read {path}: {err}",
    "登录信息不完整，缺少 {err}": "The login data is incomplete: missing {err}",
}
