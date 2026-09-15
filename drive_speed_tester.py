import os
import time
import threading
import statistics
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class DriveSpeedTesterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Drive Speed Benchmark Tool")
        self.root.geometry("900x880")
        self.root.minsize(850, 780)

        # State Variables
        self.target_path = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="size")  
        self.test_type_var = tk.StringVar(value="both") 
        self.preset_var = tk.StringVar(value="Standard (500 MB)")
        self.size_mb_var = tk.IntVar(value=500)
        self.duration_sec_var = tk.IntVar(value=15)
        
        self.is_running = False
        self.test_thread = None

        # Data series for live graphing & stats
        self.write_times = []
        self.write_speeds = []
        self.read_times = []
        self.read_speeds = []
        
        self.current_bytes_written = 0
        self.current_bytes_read = 0
        self.target_bytes = 0
        self.target_seconds = 0

        self._create_ui()
        self.populate_drives()  # Auto-detect drives on launch

    def _create_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ---------------- 1. Target Path Selection ----------------
        path_frame = ttk.LabelFrame(main_frame, text=" Storage Location ", padding="10")
        path_frame.pack(fill=tk.X, pady=(0, 10))

        # Replaced standard Entry with Combobox for auto-detected drives
        self.drive_cb = ttk.Combobox(path_frame, textvariable=self.target_path)
        self.drive_cb.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        btn_frame = ttk.Frame(path_frame)
        btn_frame.pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="↻ Refresh", command=self.populate_drives, width=9).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Browse...", command=self.browse_path, width=9).pack(side=tk.LEFT)

        # ---------------- 2. Settings & Templates ----------------
        settings_frame = ttk.LabelFrame(main_frame, text=" Benchmark Configuration ", padding="10")
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        # Row 0: Preset and Mode
        ttk.Label(settings_frame, text="Preset Template:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        preset_cb = ttk.Combobox(
            settings_frame, textvariable=self.preset_var, 
            values=["Quick Test (100 MB)", "Standard (500 MB)", "Sustained Stress (2 GB)", "Timed Run (30s)", "Custom"],
            state="readonly", width=22
        )
        preset_cb.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        preset_cb.bind("<<ComboboxSelected>>", self.on_preset_change)

        ttk.Label(settings_frame, text="Stop Condition:").grid(row=0, column=2, sticky=tk.W, padx=(20, 5), pady=5)
        ttk.Radiobutton(settings_frame, text="Fixed Size", variable=self.mode_var, value="size", command=self.toggle_mode_fields).grid(row=0, column=3, sticky=tk.W, padx=5)
        ttk.Radiobutton(settings_frame, text="Fixed Duration", variable=self.mode_var, value="duration", command=self.toggle_mode_fields).grid(row=0, column=4, sticky=tk.W, padx=5)

        # Row 1: Values and Test Type
        self.lbl_size = ttk.Label(settings_frame, text="File Size (MB):")
        self.lbl_size.grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_size = ttk.Spinbox(settings_frame, from_=50, to_=20000, increment=50, textvariable=self.size_mb_var, width=10)
        self.entry_size.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)

        self.lbl_duration = ttk.Label(settings_frame, text="Duration (sec):")
        self.lbl_duration.grid(row=1, column=2, sticky=tk.W, padx=(20, 5), pady=5)
        self.entry_duration = ttk.Spinbox(settings_frame, from_=5, to_=300, increment=5, textvariable=self.duration_sec_var, width=10)
        self.entry_duration.grid(row=1, column=3, sticky=tk.W, padx=5, pady=5)

        # Row 2: Test Type Selection
        ttk.Label(settings_frame, text="Test Operation:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        op_frame = ttk.Frame(settings_frame)
        op_frame.grid(row=2, column=1, columnspan=4, sticky=tk.W, padx=5, pady=5)
        ttk.Radiobutton(op_frame, text="Write + Read", variable=self.test_type_var, value="both").pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(op_frame, text="Write Only", variable=self.test_type_var, value="write").pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(op_frame, text="Read Only", variable=self.test_type_var, value="read").pack(side=tk.LEFT)

        self.toggle_mode_fields()

        # ---------------- 3. Controls ----------------
        ctrl_frame = ttk.Frame(main_frame)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))

        self.btn_start = ttk.Button(ctrl_frame, text="▶ Start Benchmark", command=self.start_benchmark)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_stop = ttk.Button(ctrl_frame, text="⏹ Stop", command=self.stop_benchmark, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_export = ttk.Button(ctrl_frame, text="💾 Export Report (PDF)", command=self.export_pdf, state=tk.DISABLED)
        self.btn_export.pack(side=tk.RIGHT)

        self.progress = ttk.Progressbar(main_frame, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=(0, 10))

        self.lbl_status = ttk.Label(main_frame, text="Ready", font=("Helvetica", 10, "italic"))
        self.lbl_status.pack(anchor=tk.W, pady=(0, 10))

        # ---------------- 4. Live Statistics Blocks ----------------
        stats_container = ttk.Frame(main_frame)
        stats_container.pack(fill=tk.X, pady=(0, 10))
        stats_container.columnconfigure(0, weight=1)
        stats_container.columnconfigure(1, weight=1)

        # Write Stats
        write_frame = ttk.LabelFrame(stats_container, text=" Write Performance ", padding="10")
        write_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.lbl_w_cur = ttk.Label(write_frame, text="Current: -- MB/s", font=("Helvetica", 11, "bold"), foreground="#d32f2f")
        self.lbl_w_cur.pack(anchor=tk.W)
        self.lbl_w_avg = ttk.Label(write_frame, text="Average: -- MB/s")
        self.lbl_w_avg.pack(anchor=tk.W)
        self.lbl_w_med = ttk.Label(write_frame, text="Median: -- MB/s")
        self.lbl_w_med.pack(anchor=tk.W)
        self.lbl_w_min = ttk.Label(write_frame, text="Minimum: -- MB/s")
        self.lbl_w_min.pack(anchor=tk.W)
        self.lbl_w_max = ttk.Label(write_frame, text="Maximum: -- MB/s")
        self.lbl_w_max.pack(anchor=tk.W)
        self.lbl_w_data = ttk.Label(write_frame, text="Data Written: 0.00 MB", font=("Helvetica", 10, "bold"))
        self.lbl_w_data.pack(anchor=tk.W, pady=(5,0))
        self.lbl_w_time = ttk.Label(write_frame, text="Time: 0.0s")
        self.lbl_w_time.pack(anchor=tk.W)
        self.lbl_w_eta = ttk.Label(write_frame, text="ETA: --:--", font=("Helvetica", 10, "italic"), foreground="gray")
        self.lbl_w_eta.pack(anchor=tk.W)

        # Read Stats
        read_frame = ttk.LabelFrame(stats_container, text=" Read Performance ", padding="10")
        read_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.lbl_r_cur = ttk.Label(read_frame, text="Current: -- MB/s", font=("Helvetica", 11, "bold"), foreground="#2e7d32")
        self.lbl_r_cur.pack(anchor=tk.W)
        self.lbl_r_avg = ttk.Label(read_frame, text="Average: -- MB/s")
        self.lbl_r_avg.pack(anchor=tk.W)
        self.lbl_r_med = ttk.Label(read_frame, text="Median: -- MB/s")
        self.lbl_r_med.pack(anchor=tk.W)
        self.lbl_r_min = ttk.Label(read_frame, text="Minimum: -- MB/s")
        self.lbl_r_min.pack(anchor=tk.W)
        self.lbl_r_max = ttk.Label(read_frame, text="Maximum: -- MB/s")
        self.lbl_r_max.pack(anchor=tk.W)
        self.lbl_r_data = ttk.Label(read_frame, text="Data Read: 0.00 MB", font=("Helvetica", 10, "bold"))
        self.lbl_r_data.pack(anchor=tk.W, pady=(5,0))
        self.lbl_r_time = ttk.Label(read_frame, text="Time: 0.0s")
        self.lbl_r_time.pack(anchor=tk.W)
        self.lbl_r_eta = ttk.Label(read_frame, text="ETA: --:--", font=("Helvetica", 10, "italic"), foreground="gray")
        self.lbl_r_eta.pack(anchor=tk.W)

        # ---------------- 5. Live Matplotlib Graph ----------------
        graph_frame = ttk.LabelFrame(main_frame, text=" Live Speed Chart ", padding="5")
        graph_frame.pack(fill=tk.BOTH, expand=True)

        self.fig = Figure(figsize=(6, 3.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Time (seconds)", fontsize=9)
        self.ax.set_ylabel("Speed (MB/s)", fontsize=9)
        self.ax.grid(True, linestyle="--", alpha=0.5)

        (self.line_write,) = self.ax.plot([], [], label="Write Speed", color="#d32f2f", linewidth=2)
        (self.line_read,) = self.ax.plot([], [], label="Read Speed", color="#2e7d32", linewidth=2)
        self.ax.legend(loc="upper left")
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ---------------- UI Logic & Callbacks ----------------

    def populate_drives(self):
        """Auto-detects available storage volumes and populates the dropdown."""
        drives = []
        if os.name == 'posix' and os.path.exists('/Volumes'):
            # macOS drive detection
            for d in os.listdir('/Volumes'):
                path = os.path.join('/Volumes', d)
                if os.path.isdir(path):
                    drives.append(path)
        elif os.name == 'nt':
            # Windows drive detection
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]

        self.drive_cb['values'] = drives
        
        # Set a default option if drives are found
        if drives:
            # Try to avoid selecting standard system drives automatically
            for d in drives:
                if "Macintosh HD" not in d and d != "C:\\":
                    self.target_path.set(d)
                    break
            else:
                self.target_path.set(drives[0])
        else:
            self.target_path.set("")

    def browse_path(self):
        folder = filedialog.askdirectory(title="Select External Drive Directory")
        if folder:
            self.target_path.set(folder)
            # Add to combobox history if not already there
            current_values = list(self.drive_cb['values'])
            if folder not in current_values:
                current_values.append(folder)
                self.drive_cb['values'] = current_values

    def toggle_mode_fields(self):
        if self.mode_var.get() == "size":
            self.entry_size.config(state="normal")
            self.entry_duration.config(state="disabled")
        else:
            self.entry_size.config(state="disabled")
            self.entry_duration.config(state="normal")

    def on_preset_change(self, event=None):
        selection = self.preset_var.get()
        if "Quick" in selection:
            self.mode_var.set("size")
            self.size_mb_var.set(100)
        elif "Standard" in selection:
            self.mode_var.set("size")
            self.size_mb_var.set(500)
        elif "Sustained" in selection:
            self.mode_var.set("size")
            self.size_mb_var.set(2000)
        elif "Timed" in selection:
            self.mode_var.set("duration")
            self.duration_sec_var.set(30)
        self.toggle_mode_fields()

    def reset_stats_ui(self):
        self.lbl_w_cur.config(text="Current: -- MB/s")
        self.lbl_w_avg.config(text="Average: -- MB/s")
        self.lbl_w_med.config(text="Median: -- MB/s")
        self.lbl_w_min.config(text="Minimum: -- MB/s")
        self.lbl_w_max.config(text="Maximum: -- MB/s")
        self.lbl_w_data.config(text="Data Written: 0.00 MB")
        self.lbl_w_time.config(text="Time: 0.0s")
        self.lbl_w_eta.config(text="ETA: --:--")

        self.lbl_r_cur.config(text="Current: -- MB/s")
        self.lbl_r_avg.config(text="Average: -- MB/s")
        self.lbl_r_med.config(text="Median: -- MB/s")
        self.lbl_r_min.config(text="Minimum: -- MB/s")
        self.lbl_r_max.config(text="Maximum: -- MB/s")
        self.lbl_r_data.config(text="Data Read: 0.00 MB")
        self.lbl_r_time.config(text="Time: 0.0s")
        self.lbl_r_eta.config(text="ETA: --:--")

    def get_eta_string(self, elapsed_time, current_bytes, avg_speed_mb_s):
        """Calculates and formats the ETA string (MM:SS)."""
        if self.mode_var.get() == "size":
            if avg_speed_mb_s <= 0:
                return "--:--"
            bytes_remaining = max(0, self.target_bytes - current_bytes)
            mb_remaining = bytes_remaining / (1024 * 1024)
            eta_sec = mb_remaining / avg_speed_mb_s
        else: # duration mode
            eta_sec = max(0, self.target_seconds - elapsed_time)
            
        m, s = divmod(int(eta_sec), 60)
        return f"{m:02d}:{s:02d}"

    def update_graph_and_stats(self):
        # Update Graph Data
        self.line_write.set_data(self.write_times, self.write_speeds)
        self.line_read.set_data(self.read_times, self.read_speeds)

        all_times = self.write_times + self.read_times
        all_speeds = self.write_speeds + self.read_speeds

        if all_times:
            self.ax.set_xlim(0, max(max(all_times) * 1.05, 5))
        if all_speeds:
            self.ax.set_ylim(0, max(max(all_speeds) * 1.15, 10))

        self.canvas.draw_idle()

        # Update Write Stats
        if self.write_speeds:
            cur_w = self.write_speeds[-1]
            avg_w = sum(self.write_speeds) / len(self.write_speeds)
            med_w = statistics.median(self.write_speeds)
            min_w = min(self.write_speeds)
            max_w = max(self.write_speeds)
            time_w = self.write_times[-1]

            self.lbl_w_cur.config(text=f"Current: {cur_w:.1f} MB/s")
            self.lbl_w_avg.config(text=f"Average: {avg_w:.1f} MB/s")
            self.lbl_w_med.config(text=f"Median: {med_w:.1f} MB/s")
            self.lbl_w_min.config(text=f"Minimum: {min_w:.1f} MB/s")
            self.lbl_w_max.config(text=f"Maximum: {max_w:.1f} MB/s")
            self.lbl_w_data.config(text=f"Data Written: {self.current_bytes_written / (1024 * 1024):.2f} MB")
            self.lbl_w_time.config(text=f"Time: {time_w:.1f}s")
            self.lbl_w_eta.config(text=f"ETA: {self.get_eta_string(time_w, self.current_bytes_written, avg_w)}")

        # Update Read Stats
        if self.read_speeds:
            cur_r = self.read_speeds[-1]
            avg_r = sum(self.read_speeds) / len(self.read_speeds)
            med_r = statistics.median(self.read_speeds)
            min_r = min(self.read_speeds)
            max_r = max(self.read_speeds)
            time_r = self.read_times[-1] - (self.write_times[-1] if self.write_times else 0)

            self.lbl_r_cur.config(text=f"Current: {cur_r:.1f} MB/s")
            self.lbl_r_avg.config(text=f"Average: {avg_r:.1f} MB/s")
            self.lbl_r_med.config(text=f"Median: {med_r:.1f} MB/s")
            self.lbl_r_min.config(text=f"Minimum: {min_r:.1f} MB/s")
            self.lbl_r_max.config(text=f"Maximum: {max_r:.1f} MB/s")
            self.lbl_r_data.config(text=f"Data Read: {self.current_bytes_read / (1024 * 1024):.2f} MB")
            self.lbl_r_time.config(text=f"Time: {time_r:.1f}s")
            self.lbl_r_eta.config(text=f"ETA: {self.get_eta_string(time_r, self.current_bytes_read, avg_r)}")

    # ---------------- Benchmark Execution Thread ----------------

    def start_benchmark(self):
        path = self.target_path.get()
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "Please select a valid target drive path first.")
            return

        self.is_running = True
        self.btn_start.config(state=tk.DISABLED)
        self.btn_export.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.progress.start(10)

        # Store targets for ETA calculation
        self.target_bytes = self.size_mb_var.get() * 1024 * 1024
        self.target_seconds = self.duration_sec_var.get()

        # Reset Data
        self.write_times.clear()
        self.write_speeds.clear()
        self.read_times.clear()
        self.read_speeds.clear()
        self.current_bytes_written = 0
        self.current_bytes_read = 0
        
        self.reset_stats_ui()
        self.update_graph_and_stats()

        # Launch Thread
        self.test_thread = threading.Thread(
            target=self.run_speed_test, 
            args=(path, self.test_type_var.get(), self.mode_var.get()),
            daemon=True
        )
        self.test_thread.start()

    def stop_benchmark(self):
        self.is_running = False
        self.lbl_status.config(text="Stopping benchmark...")

    def run_speed_test(self, path, test_type, mode):
        dummy_file = os.path.join(path, ".speed_test_temp.bin")
        chunk_size = 4 * 1024 * 1024  # 4 MB blocks
        data = os.urandom(chunk_size)

        bytes_written_total = self.target_bytes

        # --- PREPARATION (If Read Only, we must create a file to read first) ---
        if test_type == "read":
            self.root.after(0, self.lbl_status.config, {"text": "Preparing dummy file for read test (Please wait)..."})
            try:
                with open(dummy_file, "wb") as f:
                    prep_bytes = 0
                    while prep_bytes < bytes_written_total:
                        f.write(data)
                        prep_bytes += len(data)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Preparation Error", f"Failed to create read test file: {e}")
                self.finish_benchmark(dummy_file)
                return

        # --- 1. WRITE TEST ---
        if test_type in ["write", "both"] and self.is_running:
            self.root.after(0, self.lbl_status.config, {"text": "Testing Write Speed..."})
            write_start_time = time.time()
            
            try:
                with open(dummy_file, "wb") as f:
                    while self.is_running:
                        c_start = time.time()
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())  
                        c_end = time.time()

                        self.current_bytes_written += len(data)
                        elapsed = c_end - write_start_time
                        chunk_duration = c_end - c_start
                        
                        inst_speed = (len(data) / (1024 * 1024)) / chunk_duration if chunk_duration > 0 else 0

                        self.write_times.append(elapsed)
                        self.write_speeds.append(inst_speed)

                        self.root.after(0, self.update_graph_and_stats)

                        if mode == "size" and self.current_bytes_written >= self.target_bytes:
                            break
                        elif mode == "duration" and elapsed >= self.target_seconds:
                            break

                bytes_written_total = self.current_bytes_written 
                self.root.after(0, self.lbl_w_eta.config, {"text": "ETA: 00:00"}) # Finalize ETA

            except Exception as e:
                self.root.after(0, messagebox.showerror, "Write Error", str(e))
                self.finish_benchmark(dummy_file)
                return

        # --- 2. READ TEST ---
        if test_type in ["read", "both"] and self.is_running:
            self.root.after(0, self.lbl_status.config, {"text": "Testing Read Speed..."})
            
            time_offset = self.write_times[-1] if self.write_times else 0
            read_start_time = time.time()

            # Ensure ETA uses correct file size if dynamic duration changed the final write size
            if mode == "duration" and test_type == "both":
                self.target_bytes = bytes_written_total

            try:
                with open(dummy_file, "rb") as f:
                    while self.is_running:
                        c_start = time.time()
                        chunk = f.read(chunk_size)
                        c_end = time.time()

                        if not chunk:
                            if mode == "duration":
                                f.seek(0)
                                continue
                            else:
                                break

                        self.current_bytes_read += len(chunk)
                        elapsed = c_end - read_start_time
                        chunk_duration = c_end - c_start
                        
                        inst_speed = (len(chunk) / (1024 * 1024)) / chunk_duration if chunk_duration > 0 else 0

                        self.read_times.append(time_offset + elapsed)
                        self.read_speeds.append(inst_speed)

                        self.root.after(0, self.update_graph_and_stats)

                        if mode == "size" and self.current_bytes_read >= bytes_written_total:
                            break
                        elif mode == "duration" and elapsed >= self.target_seconds:
                            break

                self.root.after(0, self.lbl_r_eta.config, {"text": "ETA: 00:00"}) # Finalize ETA

            except Exception as e:
                self.root.after(0, messagebox.showerror, "Read Error", str(e))

        self.root.after(0, self.lbl_status.config, {"text": "Benchmark Complete."})
        self.finish_benchmark(dummy_file)

    def finish_benchmark(self, dummy_file):
        # Cleanup temp file
        if os.path.exists(dummy_file):
            try:
                os.remove(dummy_file)
            except Exception:
                pass

        self.root.after(0, self._cleanup_ui_state)

    def _cleanup_ui_state(self):
        self.is_running = False
        self.progress.stop()
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        
        # Only enable export if we actually gathered data
        if self.write_speeds or self.read_speeds:
            self.btn_export.config(state=tk.NORMAL)

    # ---------------- Data Export ----------------
    def export_pdf(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF Documents", "*.pdf")],
            title="Save Benchmark Report"
        )
        if not file_path:
            return

        try:
            # Generate summary text for the PDF
            summary_lines = ["Drive Speed Benchmark Report", "-"*30, f"Target Path: {self.target_path.get()}"]
            
            if self.write_speeds:
                avg_w = sum(self.write_speeds) / len(self.write_speeds)
                med_w = statistics.median(self.write_speeds)
                summary_lines.append(
                    f"WRITE -> Avg: {avg_w:.2f} MB/s | Med: {med_w:.2f} MB/s | Min: {min(self.write_speeds):.2f} MB/s | "
                    f"Max: {max(self.write_speeds):.2f} MB/s | Time: {self.write_times[-1]:.2f}s"
                )
            
            if self.read_speeds:
                avg_r = sum(self.read_speeds) / len(self.read_speeds)
                med_r = statistics.median(self.read_speeds)
                time_r = self.read_times[-1] - (self.write_times[-1] if self.write_times else 0)
                summary_lines.append(
                    f"READ  -> Avg: {avg_r:.2f} MB/s | Med: {med_r:.2f} MB/s | Min: {min(self.read_speeds):.2f} MB/s | "
                    f"Max: {max(self.read_speeds):.2f} MB/s | Time: {time_r:.2f}s"
                )

            # Add text annotation to the Matplotlib figure temporarily
            summary_text = "\n".join(summary_lines)
            
            # Create a temporary figure to hold both text and plot beautifully
            export_fig = Figure(figsize=(8, 6), dpi=100)
            export_ax = export_fig.add_subplot(111)
            
            export_ax.set_title("Read & Write Throughput", fontsize=12)
            export_ax.set_xlabel("Time (seconds)")
            export_ax.set_ylabel("Speed (MB/s)")
            export_ax.grid(True, linestyle="--", alpha=0.5)

            if self.write_speeds:
                export_ax.plot(self.write_times, self.write_speeds, label="Write Speed", color="#d32f2f", linewidth=2)
            if self.read_speeds:
                export_ax.plot(self.read_times, self.read_speeds, label="Read Speed", color="#2e7d32", linewidth=2)
            
            export_ax.legend(loc="upper left")
            
            # Place summary text at the bottom of the figure
            export_fig.text(0.5, 0.02, summary_text, ha='center', va='bottom', fontsize=10, 
                            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
            
            # Adjust layout so text isn't cut off
            export_fig.subplots_adjust(bottom=0.25)
            
            # Save
            export_fig.savefig(file_path, format="pdf")
            messagebox.showinfo("Export Successful", f"Report successfully saved to:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Export Failed", f"Failed to save PDF:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = DriveSpeedTesterApp(root)
    root.mainloop()