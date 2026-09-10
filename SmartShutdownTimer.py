#!/usr/bin/env python3
"""
Smart shutdown timer - v4.9
Tabs: Basic | Firefox | Shotcut | Audio
Audio detection skips speech-dispatcher-dummy and other system streams.
Shutdown uses systemctl poweroff – no password/keyring prompt.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading, time, subprocess, os, json, re
from pathlib import Path

try:
    import psutil
    HAS_PSUTIL = True
except:
    HAS_PSUTIL = False

try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    HAS_DBUS = True
except:
    HAS_DBUS = False

PROGRESS_FILE = "/tmp/shotcut_panel_progress.json"

class SmartShutdownTimer:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Shutdown Timer")
        self.root.geometry("780x520")
        self.root.minsize(680, 450)
        self.root.configure(bg="#f0f0f0")

        # ---- Portable default: expands to the current user's Desktop ----
        self.watch_dir = tk.StringVar(value=os.path.expanduser("~/Desktop"))
        self.after_delay_sec = tk.IntVar(value=5)
        self.basic_hour = tk.IntVar(value=0)
        self.basic_min = tk.IntVar(value=30)
        self.after_shotcut_sec = tk.IntVar(value=5)
        self.audio_delay_sec = tk.IntVar(value=10)
        self.GRACE_SEC = 10

        self.monitoring = False
        self.in_shutdown_countdown = False
        self.in_basic_countdown = False
        self.in_shotcut_countdown = False
        self.shotcut_monitoring = False
        self.audio_monitoring = False
        self.in_audio_countdown = False

        self.monitor_stop = threading.Event()
        self.after_stop = threading.Event()
        self.basic_stop = threading.Event()
        self.shotcut_stop = threading.Event()
        self.shotcut_after_stop = threading.Event()
        self.audio_stop = threading.Event()
        self.audio_after_stop = threading.Event()

        self.monitor_thread = None
        self.after_thread = None
        self.basic_thread = None
        self.shotcut_thread = None
        self.shotcut_after_thread = None
        self.audio_thread = None
        self.audio_after_thread = None

        self.shotcut_jobs = []
        self.shotcut_progress = 0
        self.shotcut_progress_history = []
        self.shotcut_eta_text = ""
        self.last_status_update = 0

        self.build_ui()
        self.update_file_status()
        self.start_dbus_listener()

    def build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
            style.configure("TNotebook.Tab", padding=[12, 6], font=("Sans", 10, "bold"))
            style.configure("TFrame", background="#f0f0f0")
            style.configure("TLabel", background="#f0f0f0", font=("Sans", 10))
        except:
            pass

        main = tk.Frame(self.root, bg="#f0f0f0", padx=20, pady=15)
        main.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill="both", expand=True, pady=(0,12))

        # Basic tab
        self.basic_frame = tk.Frame(self.notebook, bg="#f0f0f0", padx=12, pady=12)
        self.notebook.add(self.basic_frame, text="⏰ Basic")
        self._build_basic_ui(self.basic_frame)

        # Firefox tab
        self.firefox_frame = tk.Frame(self.notebook, bg="#f0f0f0", padx=12, pady=12)
        self.notebook.add(self.firefox_frame, text="🦊 Firefox")
        self._build_firefox_ui(self.firefox_frame)

        # Shotcut tab
        self.shotcut_frame = tk.Frame(self.notebook, bg="#f0f0f0", padx=12, pady=12)
        self.notebook.add(self.shotcut_frame, text="🎬 Shotcut")
        self._build_shotcut_ui(self.shotcut_frame)

        # Audio tab
        self.audio_frame = tk.Frame(self.notebook, bg="#f0f0f0", padx=12, pady=12)
        self.notebook.add(self.audio_frame, text="🔊 Audio")
        self._build_audio_ui(self.audio_frame)

        # Global status box
        status_box = tk.Frame(main, bg="white", relief="solid", bd=1, padx=12, pady=12)
        status_box.pack(fill="x", pady=(0,10))
        self.status_var = tk.StringVar(value="Idle")
        self.status_label = tk.Label(status_box, textvariable=self.status_var,
                                     font=("Sans", 12, "bold"), bg="white", anchor="center")
        self.status_label.pack(fill="x", pady=2)
        self.detail_var = tk.StringVar(value="Select a tab and start a timer")
        self.detail_label = tk.Label(status_box, textvariable=self.detail_var,
                                     font=("Sans", 9), bg="white", fg="#555", anchor="center")
        self.detail_label.pack(fill="x", pady=2)

        # Global Cancel button
        cancel_border = tk.Frame(main, bg="#d32f2f", bd=2, relief="solid")
        cancel_border.pack(fill="x", pady=(4,0))
        cancel_row = tk.Frame(cancel_border, bg="#ffebee")
        cancel_row.pack(fill="x", padx=2, pady=2)
        self.cancel_btn = tk.Button(cancel_row, text="✕ Cancel Process", command=self.cancel_everything,
                                    bg="#ffcdd2", fg="#b71c1c", activebackground="#ef9a9a", activeforeground="#7f0000",
                                    font=("Sans", 10, "bold"), relief="raised", bd=2, padx=10, pady=6,
                                    state="disabled")
        self.cancel_btn.pack(fill="x", expand=True)

    def _build_basic_ui(self, parent):
        tk.Label(parent, text="Basic shutdown timer", font=("Sans", 14, "bold"),
                 bg="#f0f0f0").pack(pady=(0,8))
        row = tk.Frame(parent, bg="#f0f0f0")
        row.pack(fill="x", pady=6)
        self.basic_start_btn = tk.Button(row, text="▶ Start", command=self.start_basic_timer,
                                         bg="#a5d6a7", fg="#1b5e20", activebackground="#81c784",
                                         font=("Sans", 10, "bold"), relief="raised", bd=2, padx=12, pady=6)
        self.basic_start_btn.pack(side="left", padx=(0,12))
        frame = tk.Frame(row, bg="#e6e6e6", relief="groove", bd=1, padx=10, pady=6)
        frame.pack(side="left", fill="x", expand=True)
        inner = tk.Frame(frame, bg="#e6e6e6")
        inner.pack(anchor="center")
        tk.Label(inner, text="Shutdown in :", bg="#e6e6e6", font=("Sans", 10)).pack(side="left")
        self.basic_hour_spin = tk.Spinbox(inner, from_=0, to=23, width=4,
                                          textvariable=self.basic_hour, font=("Sans", 10), justify="center")
        self.basic_hour_spin.pack(side="left", padx=4)
        tk.Label(inner, text="Hours", bg="#e6e6e6", font=("Sans", 10)).pack(side="left", padx=2)
        self.basic_min_spin = tk.Spinbox(inner, from_=0, to=59, width=4,
                                         textvariable=self.basic_min, font=("Sans", 10), justify="center")
        self.basic_min_spin.pack(side="left", padx=4)
        tk.Label(inner, text="Minutes", bg="#e6e6e6", font=("Sans", 10)).pack(side="left", padx=2)

    def _build_firefox_ui(self, parent):
        tk.Label(parent, text="Shutdown after Firefox downloads", font=("Sans", 14, "bold"),
                 bg="#f0f0f0").pack(pady=(0,8))
        tk.Label(parent, text="Download's Path", bg="#f0f0f0", anchor="w", font=("Sans", 10)).pack(fill="x")
        folder_row = tk.Frame(parent, bg="#f0f0f0")
        folder_row.pack(fill="x", pady=4)
        self.watch_entry = tk.Entry(folder_row, textvariable=self.watch_dir, font=("Sans", 10))
        self.watch_entry.pack(side="left", fill="x", expand=True, padx=(0,8), ipady=2)
        self.browse_btn = ttk.Button(folder_row, text="Browse", command=self.browse, width=10)
        self.browse_btn.pack(side="left")
        ctrl_row = tk.Frame(parent, bg="#f0f0f0")
        ctrl_row.pack(fill="x", pady=8)
        self.start_btn = tk.Button(ctrl_row, text="▶ Start", command=self.start_watching,
                                   bg="#a5d6a7", fg="#1b5e20", activebackground="#81c784",
                                   font=("Sans", 10, "bold"), relief="raised", bd=2, padx=12, pady=6)
        self.start_btn.pack(side="left", padx=(0,12))
        after_frame = tk.Frame(ctrl_row, bg="#e6e6e6", relief="groove", bd=1, padx=10, pady=6)
        after_frame.pack(side="left", fill="x", expand=True)
        inner = tk.Frame(after_frame, bg="#e6e6e6")
        inner.pack(anchor="center")
        tk.Label(inner, text="Shutdown in", bg="#e6e6e6", font=("Sans", 10)).pack(side="left")
        self.after_spin = tk.Spinbox(inner, from_=5, to=600, width=5,
                                     textvariable=self.after_delay_sec, justify="center",
                                     font=("Sans", 10))
        self.after_spin.pack(side="left", padx=6)
        tk.Label(inner, text="seconds after finish", bg="#e6e6e6", font=("Sans", 10)).pack(side="left")

    def _build_shotcut_ui(self, parent):
        tk.Label(parent, text="Shutdown after Shotcut export", font=("Sans", 14, "bold"),
                 bg="#f0f0f0").pack(pady=(0,8))
        row = tk.Frame(parent, bg="#f0f0f0")
        row.pack(fill="x", pady=6)
        self.shotcut_start_btn = tk.Button(row, text="▶ Start", command=self.start_shotcut_watching,
                                           bg="#a5d6a7", fg="#1b5e20", activebackground="#81c784",
                                           font=("Sans", 10, "bold"), relief="raised", bd=2, padx=12, pady=6)
        self.shotcut_start_btn.pack(side="left", padx=(0,12))
        after_frame = tk.Frame(row, bg="#e6e6e6", relief="groove", bd=1, padx=10, pady=6)
        after_frame.pack(side="left", fill="x", expand=True)
        inner = tk.Frame(after_frame, bg="#e6e6e6")
        inner.pack(anchor="center")
        tk.Label(inner, text="Shutdown in", bg="#e6e6e6", font=("Sans", 10)).pack(side="left")
        self.shotcut_spin = tk.Spinbox(inner, from_=5, to=600, width=5,
                                       textvariable=self.after_shotcut_sec, justify="center",
                                       font=("Sans", 10))
        self.shotcut_spin.pack(side="left", padx=6)
        tk.Label(inner, text="seconds after export", bg="#e6e6e6", font=("Sans", 10)).pack(side="left")

    def _build_audio_ui(self, parent):
        tk.Label(parent, text="Shutdown when audio stops playing", font=("Sans", 14, "bold"),
                 bg="#f0f0f0").pack(pady=(0,8))
        tk.Label(parent, text="Monitors system audio – shuts down after silence period",
                 font=("Sans", 9), bg="#f0f0f0", fg="#444").pack(pady=(0,10))

        row = tk.Frame(parent, bg="#f0f0f0")
        row.pack(fill="x", pady=6)
        self.audio_start_btn = tk.Button(row, text="▶ Start", command=self.start_audio_monitoring,
                                         bg="#a5d6a7", fg="#1b5e20", activebackground="#81c784",
                                         font=("Sans", 10, "bold"), relief="raised", bd=2, padx=12, pady=6)
        self.audio_start_btn.pack(side="left", padx=(0,12))
        after_frame = tk.Frame(row, bg="#e6e6e6", relief="groove", bd=1, padx=10, pady=6)
        after_frame.pack(side="left", fill="x", expand=True)
        inner = tk.Frame(after_frame, bg="#e6e6e6")
        inner.pack(anchor="center")
        tk.Label(inner, text="Shutdown after", bg="#e6e6e6", font=("Sans", 10)).pack(side="left")
        self.audio_spin = tk.Spinbox(inner, from_=0, to=120, width=5,
                                     textvariable=self.audio_delay_sec, justify="center",
                                     font=("Sans", 10))
        self.audio_spin.pack(side="left", padx=6)
        tk.Label(inner, text="seconds of silence", bg="#e6e6e6", font=("Sans", 10)).pack(side="left")

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.watch_dir.get())
        if d:
            self.watch_dir.set(d)

    def update_status(self, status, detail=""):
        now = time.time()
        if now - self.last_status_update < 0.8 and status == self.status_var.get() and detail == self.detail_var.get():
            return
        self.last_status_update = now
        def _u():
            status_clean = status.lstrip('● ').strip()
            if not detail:
                self.status_label.config(font=("Sans", 14, "bold"), justify="center")
                self.status_var.set(status_clean)
                self.detail_var.set(" ")
            else:
                self.status_label.config(font=("Sans", 11, "bold"), justify="center")
                self.detail_label.config(font=("Sans", 9), justify="center")
                self.status_var.set(status_clean)
                self.detail_var.set(detail)
        self.root.after(0, _u)

    def update_status_simple(self, text):
        now = time.time()
        if now - self.last_status_update < 0.9 and text == self.status_var.get():
            return
        self.last_status_update = now
        def _u():
            text_clean = text.lstrip('● ').strip()
            self.status_label.config(font=("Sans", 14, "bold"), justify="center")
            self.status_var.set(text_clean)
            self.detail_var.set(" ")
        self.root.after(0, _u)

    def update_cancel_button(self):
        active = (self.monitoring or self.in_shutdown_countdown or
                  self.in_basic_countdown or self.in_shotcut_countdown or
                  self.shotcut_monitoring or self.audio_monitoring or
                  self.in_audio_countdown)
        state = "normal" if active else "disabled"
        self.cancel_btn.config(state=state)

    # ---- Firefox watcher ----
    def start_watching(self):
        if self.monitoring:
            return
        watch_path = Path(self.watch_dir.get())
        if not watch_path.exists():
            messagebox.showerror("Error", f"Folder not found:\n{watch_path}")
            return
        self.basic_stop.set()
        self.shotcut_stop.set(); self.shotcut_after_stop.set()
        self.audio_stop.set(); self.audio_after_stop.set()
        self.in_basic_countdown = False
        self.shotcut_monitoring = False; self.in_shotcut_countdown = False
        self.audio_monitoring = False; self.in_audio_countdown = False
        self.monitor_stop.clear(); self.after_stop.clear()
        self.monitoring = True; self.in_shutdown_countdown = False
        self.start_btn.config(state="disabled")
        self.basic_start_btn.config(state="disabled")
        self.shotcut_start_btn.config(state="disabled")
        self.audio_start_btn.config(state="disabled")
        self.lock_controls()
        self.update_status("Waiting for download...", f"Watching {watch_path.name}")
        self.update_cancel_button()
        self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
        self.monitor_thread.start()

    def monitor_loop(self):
        watch_path = Path(self.watch_dir.get())
        found = False
        part_info = {}
        STALL_THRESHOLD = 45
        try:
            while not self.monitor_stop.is_set():
                parts = list(watch_path.glob("*.part"))
                now = time.time()
                current_strs = set(str(p) for p in parts)
                for old in list(part_info.keys()):
                    if old not in current_strs:
                        del part_info[old]
                for p in parts:
                    p_str = str(p)
                    try:
                        st = p.stat()
                        size = st.st_size
                    except:
                        continue
                    if p_str not in part_info:
                        part_info[p_str] = {"size": size, "last_size": size, "last_change": now, "stalled": False}
                    else:
                        info = part_info[p_str]
                        if size != info["last_size"]:
                            info["last_size"] = size
                            info["size"] = size
                            info["last_change"] = now
                            info["stalled"] = False
                        else:
                            if now - info["last_change"] > STALL_THRESHOLD:
                                if not info["stalled"]:
                                    info["stalled"] = True
                active_parts = [p for p in parts if not part_info.get(str(p), {}).get("stalled", False)]
                stalled_parts = [p for p in parts if part_info.get(str(p), {}).get("stalled", False)]
                if not found:
                    if active_parts:
                        found = True
                        self.update_status("Downloading...", f"{len(active_parts)} file(s) in progress" + (f" + {len(stalled_parts)} stalled/failed (skipped)" if stalled_parts else ""))
                    elif stalled_parts:
                        self.update_status("Waiting (only stalled .part)", f"{len(stalled_parts)} failed .part - waiting for new download")
                        time.sleep(2)
                        continue
                    else:
                        self.update_status("Waiting for download...", f"Waiting for .part in {watch_path.name}")
                        time.sleep(2)
                        continue
                else:
                    if active_parts:
                        msg = f"{len(active_parts)} file(s) remaining"
                        if stalled_parts:
                            msg += f" + {len(stalled_parts)} failed (skipped)"
                        self.update_status("Downloading...", msg)
                        time.sleep(3)
                        continue
                    else:
                        if stalled_parts and not active_parts:
                            self.update_status("Finishing (last failed, skipping)...", f"{len(stalled_parts)} failed .part skipped, {self.GRACE_SEC}s grace")
                            for _ in range(self.GRACE_SEC):
                                if self.monitor_stop.is_set():
                                    return
                                time.sleep(1)
                                new_parts = list(watch_path.glob("*.part"))
                                new_active = [p for p in new_parts if not part_info.get(str(p), {}).get("stalled", False) or str(p) not in part_info]
                                if new_active:
                                    self.update_status("Downloading...", "New download detected during grace")
                                    break
                            else:
                                self.root.after(0, self.start_after_shutdown_countdown)
                                return
                        elif not parts:
                            self.update_status("Finishing...", f"No .part files, {self.GRACE_SEC}s grace")
                            for _ in range(self.GRACE_SEC):
                                if self.monitor_stop.is_set():
                                    return
                                time.sleep(1)
                                if list(watch_path.glob("*.part")):
                                    self.update_status("Downloading...", "New download detected")
                                    break
                            else:
                                if not list(watch_path.glob("*.part")):
                                    self.root.after(0, self.start_after_shutdown_countdown)
                                    return
                time.sleep(1)
        except Exception as e:
            self.update_status("Error", str(e))
            self.monitoring = False
            self.start_btn.config(state="normal")
            self.basic_start_btn.config(state="normal")
            self.shotcut_start_btn.config(state="normal")
            self.audio_start_btn.config(state="normal")
            self.unlock_controls()
            self.update_cancel_button()

    def start_after_shutdown_countdown(self):
        self.monitoring = False
        self.in_shutdown_countdown = True
        self.start_btn.config(state="disabled")
        self.basic_start_btn.config(state="disabled")
        self.shotcut_start_btn.config(state="disabled")
        self.audio_start_btn.config(state="disabled")
        self.after_stop.clear()
        self.update_cancel_button()
        self.after_thread = threading.Thread(target=self.after_countdown, daemon=True)
        self.after_thread.start()

    def after_countdown(self):
        delay = self.after_delay_sec.get()
        for sec in range(delay, 0, -1):
            if self.after_stop.is_set() or self.monitor_stop.is_set():
                self.cleanup_after()
                return
            self.update_status_simple(f"Shutdown in {sec} sec")
            time.sleep(1)
        if not self.after_stop.is_set():
            self.do_shutdown("After download complete")
        self.cleanup_after()

    def cleanup_after(self):
        self.in_shutdown_countdown = False
        self.start_btn.config(state="normal")
        self.basic_start_btn.config(state="normal")
        self.shotcut_start_btn.config(state="normal")
        self.audio_start_btn.config(state="normal")
        self.unlock_controls()
        self.update_status("Idle", "No timer running")
        self.update_cancel_button()

    # ---- Basic timer ----
    def get_basic_total_seconds(self):
        return self.basic_hour.get()*3600 + self.basic_min.get()*60

    def start_basic_timer(self):
        if hasattr(self,'_basic_last_start') and time.time()-self._basic_last_start<1: return
        self._basic_last_start=time.time()
        self.monitor_stop.set(); self.after_stop.set()
        self.shotcut_stop.set(); self.shotcut_after_stop.set()
        self.audio_stop.set(); self.audio_after_stop.set()
        self.monitoring=False; self.in_shutdown_countdown=False
        self.shotcut_monitoring=False; self.in_shotcut_countdown=False
        self.audio_monitoring=False; self.in_audio_countdown=False
        self.basic_stop.set()
        if self.basic_thread and self.basic_thread.is_alive(): time.sleep(0.1)
        total = self.get_basic_total_seconds()
        if total<=0: return
        self.basic_stop.clear(); self.in_basic_countdown=True
        self.start_btn.config(state="disabled")
        self.basic_start_btn.config(state="disabled")
        self.shotcut_start_btn.config(state="disabled")
        self.audio_start_btn.config(state="disabled")
        self.lock_controls()
        self.update_cancel_button()
        self.basic_thread=threading.Thread(target=self.basic_countdown, args=(total,), daemon=True)
        self.basic_thread.start()

    def basic_countdown(self, total):
        for sec in range(total,0,-1):
            if self.basic_stop.is_set():
                self.in_basic_countdown=False
                self.cleanup_after_basic()
                return
            h = sec // 3600
            m = (sec % 3600) // 60
            s = sec % 60
            if h>0:
                self.update_status_simple(f"Shutdown in {h}h {m}m {s}s")
            else:
                self.update_status_simple(f"Shutdown in {m} min {s} sec")
            time.sleep(1)
        if not self.basic_stop.is_set():
            self.in_basic_countdown=False
            self.do_shutdown(f"Basic timer {self.basic_hour.get()}h {self.basic_min.get()}m")
        self.cleanup_after_basic()

    def cleanup_after_basic(self):
        self.in_basic_countdown = False
        self.start_btn.config(state="normal")
        self.basic_start_btn.config(state="normal")
        self.shotcut_start_btn.config(state="normal")
        self.audio_start_btn.config(state="normal")
        self.unlock_controls()
        self.update_status("Idle", "No timer running")
        self.update_cancel_button()

    # ---- Shotcut timer ----
    def get_shotcut_jobs(self):
        jobs = []
        try:
            if HAS_PSUTIL:
                for proc in psutil.process_iter(['pid','name','cmdline']):
                    try:
                        info = proc.info
                        cmd = " ".join(info['cmdline'] or [])
                        if "-progress2" in cmd and "melt" in cmd.lower():
                            m = re.search(r'avformat:([^\s]+)', cmd)
                            if m:
                                file_path = m.group(1).strip('"').strip("'")
                            else:
                                file_path = "export"
                                for p in info['cmdline']:
                                    if p.endswith(('.mp4','.mov','.mkv','.avi','.webm','.m4v')):
                                        file_path = p
                                        break
                            basename = os.path.basename(file_path) if file_path != "export" else "export"
                            jobs.append({"pid": info['pid'], "file": file_path, "basename": basename})
                    except:
                        continue
        except:
            pass
        return jobs

    def format_eta(self, remaining_sec):
        if remaining_sec <=0: return "finishing"
        h = remaining_sec // 3600
        m = (remaining_sec % 3600) // 60
        if h>0:
            return f"~{h}h {m}m left"
        elif m>0:
            s = remaining_sec % 60
            return f"~{m}m {s}s left"
        else:
            return f"~{remaining_sec}s left"

    def calculate_eta(self):
        if len(self.shotcut_progress_history) < 2: return ""
        if self.shotcut_progress <=0 or self.shotcut_progress >=100: return ""
        now = time.time()
        recent = [(t,p) for t,p in self.shotcut_progress_history if now - t < 90]
        if len(recent) < 2: recent = self.shotcut_progress_history[-5:]
        if len(recent) <2: return ""
        t0, p0 = recent[0]
        t1, p1 = recent[-1]
        dt = t1 - t0
        dp = p1 - p0
        if dt <=0 or dp <=0.1: return ""
        speed = dp / dt
        remaining_pct = 100 - self.shotcut_progress
        if speed <=0: return ""
        remaining_sec = int(remaining_pct / speed)
        if remaining_sec > 24*3600: return ""
        return self.format_eta(remaining_sec)

    def start_dbus_listener(self):
        def dbus_loop():
            if not HAS_DBUS: return
            try:
                DBusGMainLoop(set_as_default=True)
                bus = dbus.SessionBus()
                def handler(app_uri, props):
                    try:
                        p = props.get("progress", None)
                        if p is not None:
                            pct = int(float(p)*100)
                            if 0 < pct <= 100:
                                self.shotcut_progress = pct
                                self.shotcut_progress_history.append((time.time(), pct))
                                if len(self.shotcut_progress_history) > 100:
                                    self.shotcut_progress_history = self.shotcut_progress_history[-100:]
                                try:
                                    data={"progress": pct, "timestamp": time.time()}
                                    with open(PROGRESS_FILE+".tmp","w") as f:
                                        json.dump(data,f)
                                    os.rename(PROGRESS_FILE+".tmp", PROGRESS_FILE)
                                except:
                                    pass
                                self.shotcut_eta_text = self.calculate_eta()
                    except:
                        pass
                bus.add_signal_receiver(handler, dbus_interface="com.canonical.Unity.LauncherEntry", signal_name="Update")
                loop = GLib.MainLoop()
                loop.run()
            except:
                pass
        def file_loop():
            last_mt = 0
            while True:
                try:
                    if os.path.exists(PROGRESS_FILE):
                        mt = os.path.getmtime(PROGRESS_FILE)
                        if mt != last_mt and time.time() - mt < 10:
                            last_mt = mt
                            try:
                                d = json.load(open(PROGRESS_FILE))
                                if time.time() - d.get("timestamp",0) < 30:
                                    pct = d.get("progress",0)
                                    if 0 < pct <=100 and pct != self.shotcut_progress:
                                        self.shotcut_progress = pct
                                        self.shotcut_progress_history.append((time.time(), pct))
                                        if len(self.shotcut_progress_history) > 100:
                                            self.shotcut_progress_history = self.shotcut_progress_history[-100:]
                                        self.shotcut_eta_text = self.calculate_eta()
                            except:
                                pass
                except:
                    pass
                time.sleep(1)
        threading.Thread(target=dbus_loop, daemon=True).start()
        threading.Thread(target=file_loop, daemon=True).start()

    def start_shotcut_watching(self):
        self.monitor_stop.set(); self.after_stop.set(); self.basic_stop.set()
        self.audio_stop.set(); self.audio_after_stop.set()
        self.monitoring=False; self.in_shutdown_countdown=False
        self.in_basic_countdown=False
        self.audio_monitoring=False; self.in_audio_countdown=False
        self.shotcut_stop.clear(); self.shotcut_after_stop.clear()
        self.shotcut_monitoring=True; self.in_shotcut_countdown=False
        self.shotcut_jobs = []; self.shotcut_progress = 0
        self.shotcut_progress_history = []; self.shotcut_eta_text = ""
        self.start_btn.config(state="disabled")
        self.basic_start_btn.config(state="disabled")
        self.shotcut_start_btn.config(state="disabled")
        self.audio_start_btn.config(state="disabled")
        self.lock_controls()
        self.update_status("Waiting for Shotcut export...", "Start export in Shotcut (before or midway OK)")
        self.update_cancel_button()
        self.shotcut_thread=threading.Thread(target=self.shotcut_monitor_loop, daemon=True)
        self.shotcut_thread.start()

    def shotcut_monitor_loop(self):
        found=False
        consecutive_empty = 0
        try:
            jobs = self.get_shotcut_jobs()
            if jobs:
                found=True
                self.shotcut_jobs = jobs
                fn = jobs[0]['basename']
                self.update_status(f"Shotcut exporting... {self.shotcut_progress}%", f"{fn} - midway start - {self.shotcut_eta_text}")
            while not self.shotcut_stop.is_set():
                if self.in_basic_countdown or self.monitoring: return
                jobs = self.get_shotcut_jobs()
                job_count = len(jobs)
                exporting = job_count > 0
                if not found:
                    if exporting:
                        found=True
                        self.shotcut_jobs = jobs
                        fn = jobs[0]['basename'] if jobs else "export"
                        if job_count>1:
                            self.update_status(f"Shotcut exporting {job_count} jobs ({self.shotcut_progress}%)", f"{fn} +{job_count-1} queued - {self.shotcut_eta_text}")
                        else:
                            self.update_status(f"Shotcut exporting... {self.shotcut_progress}%", f"{fn} - {self.shotcut_eta_text}")
                    else:
                        self.update_status("Waiting for Shotcut export...", "Waiting for melt job to start")
                        time.sleep(2); continue
                else:
                    if exporting:
                        consecutive_empty = 0
                        self.shotcut_jobs = jobs
                        fn = jobs[0]['basename'] if jobs else "export"
                        if job_count>1:
                            status = f"Shotcut exporting {job_count} jobs ({self.shotcut_progress}%)"
                            detail = f"{fn} +{job_count-1} queued - {self.shotcut_eta_text}" if self.shotcut_progress>0 else f"{fn} +{job_count-1} queued"
                        else:
                            if self.shotcut_progress>0:
                                status = f"Shotcut exporting... {self.shotcut_progress}%"
                                detail = f"{fn} - {self.shotcut_eta_text}" if self.shotcut_eta_text else fn
                            else:
                                status = f"Shotcut exporting..."
                                detail = fn
                        self.update_status(status, detail)
                        time.sleep(1.5); continue
                    else:
                        consecutive_empty += 1
                        if consecutive_empty < 8:
                            self.update_status("Finishing...", f"Checking for next export - queue grace {consecutive_empty}/8")
                            for _ in range(2):
                                time.sleep(1)
                                if self.shotcut_stop.is_set(): return
                                if self.get_shotcut_jobs():
                                    self.update_status("Shotcut exporting...", "Next queued export detected")
                                    consecutive_empty = 0
                                    found=True
                                    break
                            else:
                                time.sleep(1)
                                continue
                        else:
                            if not self.get_shotcut_jobs():
                                self.root.after(0, self.start_shotcut_countdown)
                                return
                time.sleep(1)
        except Exception as e:
            self.update_status("Error", str(e))
            self.shotcut_monitoring=False
            self.cleanup_after_shotcut()

    def start_shotcut_countdown(self):
        self.shotcut_monitoring=False
        self.in_shotcut_countdown=True
        self.start_btn.config(state="disabled")
        self.basic_start_btn.config(state="disabled")
        self.shotcut_start_btn.config(state="disabled")
        self.audio_start_btn.config(state="disabled")
        self.shotcut_after_stop.clear()
        self.update_cancel_button()
        self.shotcut_after_thread=threading.Thread(target=self.shotcut_after_countdown, daemon=True)
        self.shotcut_after_thread.start()

    def shotcut_after_countdown(self):
        delay=self.after_shotcut_sec.get()
        for sec in range(delay,0,-1):
            if self.shotcut_after_stop.is_set() or self.shotcut_stop.is_set() or self.in_basic_countdown or self.monitoring:
                self.cleanup_after_shotcut()
                return
            self.update_status_simple(f"Shutdown in {sec} sec - Shotcut done")
            time.sleep(1)
        if not self.shotcut_after_stop.is_set():
            self.do_shutdown("After Shotcut export")
        self.cleanup_after_shotcut()

    def cleanup_after_shotcut(self):
        self.in_shotcut_countdown = False
        self.shotcut_monitoring = False
        self.start_btn.config(state="normal")
        self.basic_start_btn.config(state="normal")
        self.shotcut_start_btn.config(state="normal")
        self.audio_start_btn.config(state="normal")
        self.unlock_controls()
        self.update_status("Idle", "No timer running")
        self.update_cancel_button()

    # ---- Audio timer ----
    def is_audio_playing(self):
        try:
            output = subprocess.check_output(["pactl", "list", "sink-inputs"], text=True, timeout=2, stderr=subprocess.DEVNULL)
            if "State: RUNNING" in output:
                return True
            sink_output = subprocess.check_output(["pactl", "list", "sinks"], text=True, timeout=2, stderr=subprocess.DEVNULL)
            if "State: RUNNING" in sink_output and "Sink Input" in output:
                return True
            return False
        except (subprocess.SubprocessError, FileNotFoundError):
            try:
                for p in Path("/proc/asound").glob("card*/pcm*/sub*/status"):
                    if p.exists() and "RUNNING" in p.read_text():
                        return True
            except:
                pass
            return False

    def get_audio_app_name(self):
        try:
            output = subprocess.check_output(["pactl", "list", "sink-inputs"], text=True, timeout=2, stderr=subprocess.DEVNULL)
            lines = output.splitlines()
            excluded = {"speech-dispatcher-dummy", "pulseaudio", "pipewire", "Mute", "ALSA plug-in"}
            streams = []
            for i, line in enumerate(lines):
                if "State: RUNNING" in line:
                    pid = None
                    app_name = None
                    for j in range(i, max(i-30, -1), -1):
                        if "application.process.id" in lines[j]:
                            pid = lines[j].split("=")[-1].strip()
                        if "application.name" in lines[j]:
                            app_name = lines[j].split("=")[-1].strip('"')
                    if app_name and app_name in excluded:
                        continue
                    streams.append({"pid": pid, "app_name": app_name, "index": i})
            for stream in streams:
                if stream["pid"] and HAS_PSUTIL:
                    try:
                        p = psutil.Process(int(stream["pid"]))
                        proc_name = p.name()
                        if proc_name and proc_name not in excluded:
                            return proc_name
                    except:
                        pass
            for stream in streams:
                if stream["app_name"] and stream["app_name"] not in excluded:
                    return stream["app_name"]
            for line in lines:
                if "application.name" in line:
                    name = line.split("=")[-1].strip('"')
                    if name not in excluded:
                        return name
            return None
        except:
            return None

    def start_audio_monitoring(self):
        if self.audio_monitoring or self.in_audio_countdown:
            return
        if not self.is_audio_playing():
            if not messagebox.askyesno("No audio detected",
                                       "No audio is currently playing.\n"
                                       "Start playing something and click OK."):
                return
        self.monitor_stop.set(); self.after_stop.set()
        self.basic_stop.set()
        self.shotcut_stop.set(); self.shotcut_after_stop.set()
        self.monitoring=False; self.in_shutdown_countdown=False
        self.in_basic_countdown=False
        self.shotcut_monitoring=False; self.in_shotcut_countdown=False
        self.audio_stop.clear(); self.audio_after_stop.clear()
        self.audio_monitoring=True; self.in_audio_countdown=False
        self.start_btn.config(state="disabled")
        self.basic_start_btn.config(state="disabled")
        self.shotcut_start_btn.config(state="disabled")
        self.audio_start_btn.config(state="disabled")
        self.lock_controls()
        self.update_status("Monitoring audio...", "Waiting for audio to stop")
        self.update_cancel_button()
        self.audio_thread = threading.Thread(target=self.audio_monitor_loop, daemon=True)
        self.audio_thread.start()

    def audio_monitor_loop(self):
        silence_count = 0
        max_silence = self.audio_delay_sec.get()
        while not self.audio_stop.is_set():
            playing = self.is_audio_playing()
            if playing:
                silence_count = 0
                app = self.get_audio_app_name()
                detail = f"Playing via {app}" if app else "Audio playing"
                self.update_status("Monitoring audio...", detail)
            else:
                silence_count += 2
                self.update_status("Audio stopped...", f"Silence {silence_count}s / {max_silence}s")
                if silence_count >= max_silence and max_silence > 0:
                    self.root.after(0, self.start_audio_countdown)
                    return
            time.sleep(2)
        self.root.after(0, self.cleanup_after_audio)

    def start_audio_countdown(self):
        if self.in_audio_countdown:
            return
        self.audio_monitoring = False
        self.in_audio_countdown = True
        self.start_btn.config(state="disabled")
        self.basic_start_btn.config(state="disabled")
        self.shotcut_start_btn.config(state="disabled")
        self.audio_start_btn.config(state="disabled")
        self.update_cancel_button()
        self.audio_after_stop.clear()
        self.audio_after_thread = threading.Thread(target=self.audio_after_countdown, daemon=True)
        self.audio_after_thread.start()

    def audio_after_countdown(self):
        delay = self.audio_delay_sec.get()
        if delay <= 0:
            if not self.audio_after_stop.is_set():
                self.do_shutdown("After audio stopped")
            self.cleanup_after_audio()
            return
        for sec in range(delay, 0, -1):
            if self.audio_after_stop.is_set() or self.audio_stop.is_set():
                self.cleanup_after_audio()
                return
            self.update_status_simple(f"Shutdown in {sec} sec - audio stopped")
            time.sleep(1)
        if not self.audio_after_stop.is_set():
            self.do_shutdown("After audio stopped")
        self.cleanup_after_audio()

    def cleanup_after_audio(self):
        self.audio_monitoring = False
        self.in_audio_countdown = False
        self.start_btn.config(state="normal")
        self.basic_start_btn.config(state="normal")
        self.shotcut_start_btn.config(state="normal")
        self.audio_start_btn.config(state="normal")
        self.unlock_controls()
        if not self.in_shutdown_countdown and not self.in_basic_countdown:
            self.update_status("Idle", "No timer running")
            self.update_cancel_button()

    # ---- Lock / unlock ----
    def lock_controls(self):
        for spin in [self.after_spin, self.basic_hour_spin, self.basic_min_spin,
                     self.shotcut_spin, self.audio_spin, self.watch_entry, self.browse_btn]:
            try:
                spin.config(state="disabled")
            except:
                pass
        for btn in [self.start_btn, self.basic_start_btn, self.shotcut_start_btn, self.audio_start_btn]:
            try:
                btn.config(state="disabled")
            except:
                pass

    def unlock_controls(self):
        for spin in [self.after_spin, self.basic_hour_spin, self.basic_min_spin,
                     self.shotcut_spin, self.audio_spin, self.watch_entry, self.browse_btn]:
            try:
                spin.config(state="normal")
            except:
                pass
        for btn in [self.start_btn, self.basic_start_btn, self.shotcut_start_btn, self.audio_start_btn]:
            try:
                btn.config(state="normal")
            except:
                pass

    # ---- Global cancel ----
    def cancel_everything(self):
        self.monitor_stop.set(); self.after_stop.set()
        self.basic_stop.set()
        self.shotcut_stop.set(); self.shotcut_after_stop.set()
        self.audio_stop.set(); self.audio_after_stop.set()
        self.monitoring=False; self.in_shutdown_countdown=False
        self.in_basic_countdown=False
        self.shotcut_monitoring=False; self.in_shotcut_countdown=False
        self.audio_monitoring=False; self.in_audio_countdown=False
        try:
            subprocess.run(["shutdown","-c"], capture_output=True)
        except:
            pass
        self.start_btn.config(state="normal")
        self.basic_start_btn.config(state="normal")
        self.shotcut_start_btn.config(state="normal")
        self.audio_start_btn.config(state="normal")
        self.unlock_controls()
        self.update_status("Idle", "All processes cancelled")
        self.update_cancel_button()

    # ---- SHUTDOWN WITHOUT PASSWORD ----
    def do_shutdown(self, reason):
        try:
            subprocess.Popen(["systemctl", "poweroff"])
        except Exception as e:
            try:
                subprocess.Popen(["sudo", "shutdown", "-h", "now", reason])
            except Exception as e2:
                messagebox.showerror("Shutdown failed", f"systemctl failed: {e}\nsudo failed: {e2}")

    def update_file_status(self):
        if self.monitoring or self.in_shutdown_countdown or self.in_basic_countdown or self.shotcut_monitoring or self.in_shotcut_countdown or self.audio_monitoring or self.in_audio_countdown:
            self.root.after(3000, self.update_file_status)
            return
        self.detail_var.set("No timer running")
        self.root.after(3000, self.update_file_status)

    def on_close(self):
        any_active = (self.monitoring or self.in_shutdown_countdown or self.in_basic_countdown or
                      self.shotcut_monitoring or self.in_shotcut_countdown or
                      self.audio_monitoring or self.in_audio_countdown)
        if any_active:
            resp = messagebox.askyesno("Cancel process?",
                                       "A timer is running.\n\nClosing the window will stop it and cancel the shutdown.\n\nAre you sure?",
                                       icon="warning")
            if not resp:
                return
        self.cancel_everything()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = SmartShutdownTimer(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
