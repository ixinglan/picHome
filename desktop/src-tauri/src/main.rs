#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::os::unix::process::CommandExt; // 提供 process_group(0)，让 sidecar 成为独立进程组
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use tauri::Manager;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_dialog::MessageDialogButtons;

/// 保存后端 sidecar 子进程，便于退出时清理，避免端口 14567 残留。
struct AppState {
    sidecar: Mutex<Option<Child>>,
}

/// 后端数据目录（与 settings.py 的桌面模式约定一致：~/Library/Application Support/pichome）。
fn data_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_default();
    PathBuf::from(home).join("Library/Application Support/pichome")
}

/// 从资源目录定位冻结后的 pichome-server 可执行文件并拉起。
fn spawn_backend(app: &tauri::AppHandle) -> std::io::Result<Child> {
    let resource_dir = app.path().resource_dir().expect("无法获取应用资源目录");
    let sidecar_exe = resource_dir.join("pichome-server").join("pichome-server");
    Command::new(&sidecar_exe)
        .env("PICHOME_DESKTOP", "1")
        .env("PICHOME_DESKTOP_PORT", "14567")
        // stdin 设成管道：sidecar 用它监听「宿主 app 是否还活着」。app 退出（含被强杀）
        // 时写端关闭，sidecar 读到 EOF 即自动退出，端口 14567 绝不残留。这是生命周期
        // 兜底，不依赖 Tauri 退出事件回调是否触发。
        .stdin(Stdio::piped())
        // 独立进程组：退出时 killpg 整组回收（PyInstaller 即使 fork 也能一并杀掉）。
        .process_group(0)
        .spawn()
}

/// 杀掉后端子进程（退出 / 重启前调用）。
fn kill_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut guard) = state.sidecar.lock() {
            if let Some(mut child) = guard.take() {
                let pid = child.id() as i32;
                // 先杀整个进程组（含 PyInstaller 可能 fork 出的子进程），再 wait 回收。
                // 即便这里失败，stdin EOF 兜底（run_server.py 监听 stdin 关闭）也会让
                // sidecar 自动退出，端口 14567 不残留。
                unsafe {
                    libc::killpg(pid, libc::SIGKILL);
                }
                let _ = child.wait();
            }
        }
    }
}

/// 轮询 127.0.0.1:14567 直到就绪（首次启动需 migrate / collectstatic，可能十几秒）。
fn wait_backend_ready() {
    use std::net::TcpStream;
    use std::time::{Duration, Instant};
    let start = Instant::now();
    loop {
        if TcpStream::connect(("127.0.0.1", 14567u16)).is_ok() {
            println!("[pichome] 后端已就绪 (耗时 {:?})", start.elapsed());
            break;
        }
        if start.elapsed() > Duration::from_secs(90) {
            eprintln!("[pichome] 后端在 90s 内未就绪，仍尝试显示窗口");
            break;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
}

/// 当前客户端版本（取自 Cargo.toml 的 version，由编译期宏 CARGO_PKG_VERSION 注入）。
const CURRENT_VERSION: &str = env!("CARGO_PKG_VERSION");
/// GitHub Release 接口（用于查询最新版本判断是否出新版本）。
const GITHUB_RELEASE_API: &str = "https://api.github.com/repos/ixinglan/picHome/releases/latest";

/// 把 "v1.2.3" / "1.2.3" 解析成数字段，便于逐段比较。
fn parse_version(v: &str) -> Vec<u32> {
    v.trim_start_matches('v')
        .split('.')
        .map(|s| {
            s.chars()
                .take_while(|c| c.is_ascii_digit())
                .collect::<String>()
                .parse::<u32>()
                .unwrap_or(0)
        })
        .collect()
}

/// latest 是否比 current 新（语义化版本比较，缺失段视作 0）。
fn is_newer(latest: &str, current: &str) -> bool {
    let lv = parse_version(latest);
    let cv = parse_version(current);
    let n = lv.len().max(cv.len());
    for i in 0..n {
        let l = lv.get(i).copied().unwrap_or(0);
        let c = cv.get(i).copied().unwrap_or(0);
        if l != c {
            return l > c;
        }
    }
    false
}

struct ReleaseInfo {
    tag: String,
    url: String,
    notes: String,
}

/// 调 GitHub API 取最新 Release（macOS 自带 curl，无需引入额外 HTTP 依赖）。
/// 任何失败（无网络 / 被限流 / 解析异常）都返回 None，静默跳过，绝不影响主流程。
fn fetch_latest_release() -> Option<ReleaseInfo> {
    let out = std::process::Command::new("curl")
        .args(["-s", "-m", "8", "-A", "pichome-desktop", GITHUB_RELEASE_API])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let v: serde_json::Value = serde_json::from_str(&text).ok()?;
    let tag = v.get("tag_name")?.as_str()?.to_string();
    let url = v
        .get("html_url")
        .and_then(|u| u.as_str())
        .unwrap_or("https://github.com/ixinglan/picHome/releases")
        .to_string();
    let notes = v.get("body").and_then(|b| b.as_str()).unwrap_or("").to_string();
    Some(ReleaseInfo { tag, url, notes })
}

/// 更新检查本地缓存：限频（24h 内复用）＋ 去重提醒（已提醒过的版本不再弹）。
/// 落盘在用户数据目录 update_check.json。
#[derive(serde::Serialize, serde::Deserialize, Default)]
struct UpdateCache {
    last_check_ts: u64,
    latest_tag: String,
    last_notified_tag: String,
}

fn update_cache_path() -> PathBuf {
    data_dir().join("update_check.json")
}

fn load_update_cache() -> UpdateCache {
    if let Ok(s) = std::fs::read_to_string(update_cache_path()) {
        serde_json::from_str(&s).unwrap_or_default()
    } else {
        UpdateCache::default()
    }
}

fn save_update_cache(c: &UpdateCache) {
    if let Ok(s) = serde_json::to_string(c) {
        let _ = std::fs::write(update_cache_path(), s);
    }
}

/// 执行一次更新检查并在有新版本时弹窗提醒。
/// manual=true：用户主动点「检查更新」——始终联网、始终给结果反馈；
/// manual=false：启动自动检查——24h 内复用缓存、已提醒过的版本不再弹。
fn run_update_check(app: tauri::AppHandle, manual: bool) {
    std::thread::spawn(move || {
        let mut cache = load_update_cache();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        // 非手动且 24h 内已查过：直接使用缓存的 latest_tag，不再打网络。
        let latest = if !manual
            && (now.saturating_sub(cache.last_check_ts) < 86400)
            && !cache.latest_tag.is_empty()
        {
            Some(ReleaseInfo {
                tag: cache.latest_tag.clone(),
                url: "https://github.com/ixinglan/picHome/releases".into(),
                notes: String::new(),
            })
        } else {
            fetch_latest_release()
        };

        cache.last_check_ts = now;

        match latest {
            Some(rel) => {
                cache.latest_tag = rel.tag.clone();
                let has_update = is_newer(&rel.tag, CURRENT_VERSION);
                let should_pop = has_update && (manual || rel.tag != cache.last_notified_tag);
                if has_update {
                    cache.last_notified_tag = rel.tag.clone();
                }
                save_update_cache(&cache);

                if should_pop {
                    let notes_hint = rel.notes.lines().next().unwrap_or("").trim();
                    let hint = if notes_hint.is_empty() {
                        "前往发布页查看本次更新内容"
                    } else {
                        notes_hint
                    };
                    let msg = format!(
                        "发现新版本 {tag}（当前 {cur}）。\n\n{hint}\n\n点击「前往下载」打开 GitHub 发布页。",
                        tag = rel.tag,
                        cur = CURRENT_VERSION,
                        hint = hint
                    );
                    let url = rel.url.clone();
                    let app2 = app.clone();
                    let _ = app2.run_on_main_thread(move || {
                        app.dialog()
                            .message(msg)
                            .title("PicHome 更新可用")
                            .buttons(MessageDialogButtons::OkCancelCustom(
                                "前往下载".to_string(),
                                "稍后".to_string(),
                            ))
                            .show(move |yes| {
                                if yes {
                                    let _ = std::process::Command::new("open").arg(&url).status();
                                }
                            });
                    });
                } else if manual {
                    let msg = format!("当前已是最新版本（{cur}）。", cur = CURRENT_VERSION);
                    let app2 = app.clone();
                    let _ = app2.run_on_main_thread(move || {
                        app.dialog()
                            .message(msg)
                            .title("PicHome")
                            .buttons(MessageDialogButtons::Ok)
                            .show(|_| {});
                    });
                }
            }
            None => {
                save_update_cache(&cache);
                if manual {
                    let app2 = app.clone();
                    let _ = app2.run_on_main_thread(move || {
                        app.dialog()
                            .message("暂时无法连接更新服务器，请稍后再试。")
                            .title("PicHome")
                            .buttons(MessageDialogButtons::Ok)
                            .show(|_| {});
                    });
                }
            }
        }
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // 1) 校验 sidecar 是否存在（dev 模式在 src-tauri/，打包后在 .app/Contents/Resources/）。
            let resource_dir = app.path().resource_dir().expect("无法获取应用资源目录");
            let sidecar_exe = resource_dir
                .join("pichome-server")
                .join("pichome-server");
            if !sidecar_exe.exists() {
                return Err(Box::new(std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    format!("未找到 pichome-server sidecar: {:?}", sidecar_exe),
                )));
            }

            // 2) 拉起后端（Django + waitress），绑定 127.0.0.1:14567。
            let app_handle = app.app_handle();
            let child = spawn_backend(&app_handle)?;
            app.manage(AppState {
                sidecar: Mutex::new(Some(child)),
            });

            // 3) 等后端就绪再显示主窗口，避免 WebView 先加载出「连接失败」空白页。
            wait_backend_ready();
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.show();
            }

            // 4) 菜单栏托盘图标 + 右键菜单。
            //    右键菜单按用户要求去掉了「重启后端」，只保留最常用入口。
            let open_item = MenuItem::with_id(app, "open", "打开 PicHome", true, None::<&str>)?;
            let folder_item =
                MenuItem::with_id(app, "folder", "打开数据目录", true, None::<&str>)?;
            let update_item =
                MenuItem::with_id(app, "check_update", "检查更新", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[&open_item, &folder_item, &update_item, &sep, &quit_item],
            )?;

            // 菜单栏图标用单色 template（只取透明轮廓），macOS 自动适配明暗模式。
            let menubar_icon = tauri::image::Image::from_bytes(
                include_bytes!("../icons/menubar.png"),
            )
            .expect("加载菜单栏图标失败");

            let _tray = TrayIconBuilder::with_id("main-tray")
                .icon(menubar_icon)
                .icon_as_template(true)
                .tooltip("PicHome 桌面端")
                .menu(&menu)
                .show_menu_on_left_click(false) // 左键切换窗口，右键出菜单
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "folder" => {
                        let _ = std::process::Command::new("open")
                            .arg(data_dir())
                            .status();
                    }
                    "quit" => {
                        kill_backend(app);
                        app.exit(0);
                    }
                    "check_update" => {
                        let h = app.app_handle().clone();
                        run_update_check(h, true);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // 左键点击：窗口可见则收起，不可见则唤出（最小化到菜单栏）。
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(w) = app.get_webview_window("main") {
                            if w.is_visible().unwrap_or(false) {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                    }
                })
                .build(app)?;
            // TrayIcon 在 drop 时会移除托盘，用 mem::forget 保持常驻。
            std::mem::forget(_tray);

            // 5) 启动后自动检查新版本（延迟 3s 等窗口就绪，避免弹窗抢在窗口前）。
            let upd_app = app.app_handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_secs(3));
                run_update_check(upd_app, false);
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // 点击关闭按钮：仅隐藏窗口（不杀 sidecar、不退出进程），应用继续留在
            // 程序坞 / 菜单栏，后端仍在 14567 端口运行。想彻底退出请用菜单栏图标
            // 右键「退出」或 Cmd+Q——这两条路径会先 kill_backend 再退出（见
            // on_menu_event 的 "quit" 与 RunEvent::ExitRequested）。
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| match event {
            // 点击程序坞图标（窗口已隐藏）时重新打开窗口；
            // 若用户勾选了「程序坞中保留」，点击程序坞图标同样走这里。
            tauri::RunEvent::Reopen { .. } => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
            // 任意退出路径都先回收后端子进程，避免端口 14567 残留。
            tauri::RunEvent::ExitRequested { .. } => {
                kill_backend(app);
            }
            _ => {}
        });
}
