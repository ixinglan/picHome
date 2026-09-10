#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::Manager;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

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
        .spawn()
}

/// 杀掉后端子进程（退出 / 重启前调用）。
fn kill_backend(app: &tauri::AppHandle) {
    if let Some(state) = app.try_state::<AppState>() {
        if let Ok(mut guard) = state.sidecar.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
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

fn main() {
    tauri::Builder::default()
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
            let sep = PredefinedMenuItem::separator(app)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_item, &folder_item, &sep, &quit_item])?;

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
