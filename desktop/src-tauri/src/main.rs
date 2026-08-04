// Prevents an additional console window from opening on Windows in
// release builds. Without this the main LifeTree.exe also spawns a
// cmd.exe window alongside the GUI. DO NOT REMOVE.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    lifetree_desktop_lib::run();
}
