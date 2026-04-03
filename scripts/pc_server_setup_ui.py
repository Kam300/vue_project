from __future__ import annotations

import importlib
import importlib.util
import json
import locale
import os
import queue
import shlex
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    import paramiko as bundled_paramiko
except ImportError:
    bundled_paramiko = None


APP_TITLE = "FamilyOne: настройка сервера на ПК"
DEFAULTS = {
    "vps_host": "",
    "vps_user": "root",
    "ssh_port": "22",
    "domain": "totalcode.online",
    "server_ip": "",
    "token": "",
    "proxy_name": "familyone-web",
    "local_port": "8080",
    "startup_delay": "45",
    "start_after_setup": True,
    "check_public_health": True,
}

HELP_VPS_MIGRATION_TEXT = """Переезд на другой VPS

1. Подготовьте новый VPS.
   Нужен Ubuntu/Debian-сервер с белым IP и доступом по SSH.
   На сервере должны быть открыты порты 22, 80, 443 и 7000.

2. Обновите DNS домена.
   Для домена нужно перевести A-запись @ на IP нового VPS.
   Если есть www, оставьте CNAME www -> ваш_домен.
   После смены DNS локальный кэш Windows может еще показывать старый IP.
   Если в журнале виден старый адрес, выполните ipconfig /flushdns и повторите проверку.
   Если смена DNS была совсем недавно, временно снимите галочку
   "Проверять внешний HTTPS после действий" и повторите внешнюю проверку позже.

3. Откройте этот мастер на текущем ПК.
   В поле "Хост VPS" укажите новый IP или новый DNS-адрес сервера.
   В поле "IP сервера" обычно указывается тот же адрес, что и в "Хост VPS".
   Это адрес, к которому подключается локальный frpc.
   Если оставить "IP сервера" пустым, мастер сам подставит "Хост VPS".

4. Получите новый FRP токен.
   Нажмите "Получить токен".
   Если на новом VPS еще нет frps/caddy, мастер сам попытается настроить их по SSH.
   После этого токен будет считан с нового сервера и сохранен в поле "FRP токен".

5. Перенастройте текущий ПК на новый VPS.
   Нажмите "Настроить этот ПК".
   Мастер перепишет C:\\frp\\frpc.toml на новый IP и новый токен.

6. При необходимости включите автозапуск.
   Нажмите "Включить автозапуск VPS", чтобы включить frps и caddy на новом сервере.
   Нажмите "Включить автозапуск ПК", если нужно автоматически запускать стек на Windows.

7. Проверьте запуск.
   Нажмите "Запустить сервер", затем "Проверка здоровья".
   Убедитесь, что локальные URL отвечают и внешний HTTPS открывается уже через новый VPS.

8. После успешной миграции отключите старый VPS.
   Когда новый сервер уже работает, можно остановить frps/caddy на старом VPS
   или удалить старые правила/службы, чтобы не путаться в дальнейшем.
"""

HELP_PC_CHANGE_TEXT = """Смена ПК

1. Скопируйте проект на новый компьютер.
   Лучше переносить всю папку vue_project целиком.
   Так вы сохраните backend/.env, базу данных, runtime-файлы и скрипты в одном месте.

2. На старом ПК остановите сервер.
   Нажмите "Остановить сервер" или выполните .\\stop-server.ps1,
   чтобы одновременно не работали два одинаковых экземпляра.

3. Откройте мастер на новом ПК.
   Укажите текущий "Хост VPS", пользователя, пароль и домен.
   Поле "IP сервера" обычно совпадает с "Хост VPS".
   "FRP токен" можно оставить пустым, если хотите получить его автоматически.

4. Используйте "Полная настройка".
   Для нового ПК это основной сценарий.
   Мастер проверит VPS, получит токен, настроит frpc, включит автозапуск,
   запустит локальный стек и выполнит проверки.

5. Если нужна ручная последовательность, используйте шаги отдельно.
   Сначала "Получить токен".
   Затем "Настроить этот ПК".
   Потом "Включить автозапуск ПК".
   После этого "Запустить сервер" и "Проверка здоровья".

6. Проверьте внешний доступ.
   Убедитесь, что https://ваш_домен/ и https://ваш_домен/api/health отвечают с нового ПК.

7. После успешной проверки отключите старый ПК.
   Остановите сервер на старом компьютере и отключите там автозапуск,
   чтобы запросы шли только через новый рабочий ПК.

8. Если домен указывает на старый IP, это не проблема нового ПК.
   Сначала обновите DNS домена на нужный VPS и очистите локальный DNS-кэш Windows,
   если журнал продолжает показывать старый адрес.
   Если DNS только что меняли, можно временно снять галочку
   "Проверять внешний HTTPS после действий" и закончить локальную настройку без внешней проверки.
"""


def resolve_project_root() -> Path:
    markers = [
        "start-server.ps1",
        Path("scripts") / "setup-frpc.ps1",
        Path("scripts") / "setup-pc-autostart.ps1",
    ]

    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent

    candidates = [base] + list(base.parents)
    for candidate in candidates:
        if all((candidate / marker).exists() for marker in markers):
            return candidate

    raise FileNotFoundError(
        "Не удалось найти корень проекта. Поместите программу внутрь папки проекта FamilyOne."
    )


def powershell_executable() -> str:
    return "powershell.exe"


class SetupUi(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x830")
        self.minsize(1020, 700)

        self.project_root = resolve_project_root()
        self.runtime_dir = self.project_root / ".runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.runtime_dir / "pc_setup_ui.json"

        self.output_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.busy = False
        self.paramiko_module = None
        self.help_window: tk.Toplevel | None = None
        self.action_buttons: list[ttk.Button] = []

        self.vars: dict[str, tk.Variable] = {}
        self._init_vars()
        self._build_ui()
        self._load_settings()
        self.bind("<F1>", lambda event: self._show_help_window())
        self.after(120, self._drain_output_queue)

        self._set_status("Готово")
        self._log(f"Папка проекта: {self.project_root}")

    def _init_vars(self) -> None:
        self.vars["project_root"] = tk.StringVar(value=str(self.project_root))
        self.vars["vps_host"] = tk.StringVar(value=DEFAULTS["vps_host"])
        self.vars["vps_user"] = tk.StringVar(value=DEFAULTS["vps_user"])
        self.vars["vps_password"] = tk.StringVar(value="")
        self.vars["show_password"] = tk.BooleanVar(value=False)
        self.vars["ssh_port"] = tk.StringVar(value=DEFAULTS["ssh_port"])
        self.vars["domain"] = tk.StringVar(value=DEFAULTS["domain"])
        self.vars["server_ip"] = tk.StringVar(value=DEFAULTS["server_ip"])
        self.vars["token"] = tk.StringVar(value=DEFAULTS["token"])
        self.vars["proxy_name"] = tk.StringVar(value=DEFAULTS["proxy_name"])
        self.vars["local_port"] = tk.StringVar(value=DEFAULTS["local_port"])
        self.vars["startup_delay"] = tk.StringVar(value=DEFAULTS["startup_delay"])
        self.vars["start_after_setup"] = tk.BooleanVar(value=DEFAULTS["start_after_setup"])
        self.vars["check_public_health"] = tk.BooleanVar(value=DEFAULTS["check_public_health"])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root = ttk.Frame(self, padding=12)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        project_frame = ttk.LabelFrame(top, text="Проект")
        project_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        project_frame.columnconfigure(1, weight=1)
        ttk.Label(project_frame, text="Папка").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(
            project_frame,
            textvariable=self.vars["project_root"],
            state="readonly",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=8)
        ttk.Label(
            project_frame,
            text="Пароль не сохраняется на диск. Токен можно сохранять.",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        vps_frame = ttk.LabelFrame(top, text="VPS и домен")
        vps_frame.grid(row=0, column=1, sticky="nsew")
        for index in range(4):
            vps_frame.columnconfigure(index, weight=1 if index % 2 == 1 else 0)

        self._entry(vps_frame, "Хост VPS", "vps_host", 0, 0)
        self._entry(vps_frame, "Пользователь", "vps_user", 0, 2)
        ttk.Label(vps_frame, text="Пароль").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        password_row = ttk.Frame(vps_frame)
        password_row.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(0, 8), pady=6)
        password_row.columnconfigure(0, weight=1)

        self.password_entry = tk.Entry(
            password_row,
            textvariable=self.vars["vps_password"],
            show="*",
            relief="solid",
            borderwidth=1,
            background="white",
            foreground="black",
            insertbackground="black",
        )
        self.password_entry.grid(row=0, column=0, sticky="ew")
        self._bind_paste_support(self.password_entry)

        ttk.Checkbutton(
            password_row,
            text="Показать пароль",
            variable=self.vars["show_password"],
            command=self._update_password_visibility,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Button(
            password_row,
            text="Вставить",
            command=lambda: self._paste_into_entry(self.password_entry),
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        self._entry(vps_frame, "SSH порт", "ssh_port", 2, 0)
        self._entry(vps_frame, "Домен", "domain", 2, 2)
        self._entry(vps_frame, "IP сервера", "server_ip", 3, 0)
        self._entry(vps_frame, "FRP токен", "token", 3, 2)
        self._entry(vps_frame, "Имя прокси", "proxy_name", 4, 0)
        self._entry(vps_frame, "Локальный порт", "local_port", 4, 2)
        self._entry(vps_frame, "Задержка старта (сек)", "startup_delay", 5, 0)

        options = ttk.Frame(root)
        options.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(
            options,
            text="Запустить сервер сразу после полной настройки",
            variable=self.vars["start_after_setup"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Checkbutton(
            options,
            text="Проверять внешний HTTPS после действий",
            variable=self.vars["check_public_health"],
        ).grid(row=0, column=1, sticky="w")

        actions = ttk.LabelFrame(root, text="Действия")
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for col in range(5):
            actions.columnconfigure(col, weight=1)

        self._button(actions, "Сохранить поля", self._save_settings, 0, 0)
        self._button(actions, "Проверить VPS", self._start_check_vps, 0, 1)
        self._button(actions, "Получить токен", self._start_fetch_token, 0, 2)
        self._button(actions, "Включить автозапуск VPS", self._start_enable_vps_autostart, 0, 3)
        self._button(actions, "Полная настройка", self._start_full_setup, 0, 4)

        self._button(actions, "Настроить этот ПК", self._start_configure_pc, 1, 0)
        self._button(actions, "Включить автозапуск ПК", self._start_enable_pc_autostart, 1, 1)
        self._button(actions, "Запустить сервер", self._start_server, 1, 2)
        self._button(actions, "Остановить сервер", self._stop_server, 1, 3)
        self._button(actions, "Проверка здоровья", self._start_health_check, 1, 4)

        ttk.Button(
            actions,
            text="Помощь: переезд на VPS / смена ПК",
            command=self._show_help_window,
        ).grid(row=2, column=0, columnspan=5, sticky="ew", padx=6, pady=(6, 6))

        logs = ttk.LabelFrame(root, text="Журнал")
        logs.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)

        self.log_text = ScrolledText(logs, wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        status_bar = ttk.Frame(root)
        status_bar.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        status_bar.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="")
        ttk.Label(status_bar, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def _show_help_window(self) -> None:
        if self.help_window is not None and self.help_window.winfo_exists():
            self.help_window.deiconify()
            self.help_window.lift()
            self.help_window.focus_force()
            return

        window = tk.Toplevel(self)
        self.help_window = window
        window.title(f"{APP_TITLE} — помощь")
        window.geometry("920x720")
        window.minsize(760, 560)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        def on_destroy(event: tk.Event) -> None:
            if event.widget is window:
                self.help_window = None

        window.bind("<Destroy>", on_destroy)

        ttk.Label(
            window,
            text=(
                "Пошаговые инструкции для двух частых сценариев. "
                "Все шаги привязаны к кнопкам этого мастера."
            ),
            wraplength=860,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        notebook = ttk.Notebook(window)
        notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        self._add_help_tab(notebook, "Переезд на VPS", HELP_VPS_MIGRATION_TEXT)
        self._add_help_tab(notebook, "Смена ПК", HELP_PC_CHANGE_TEXT)

        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        buttons.columnconfigure(0, weight=1)
        ttk.Button(buttons, text="Закрыть", command=window.destroy).grid(row=0, column=1, sticky="e")

    def _add_help_tab(self, notebook: ttk.Notebook, title: str, content: str) -> None:
        frame = ttk.Frame(notebook, padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        text = ScrolledText(frame, wrap="word", font=("Segoe UI", 10))
        text.grid(row=0, column=0, sticky="nsew")
        text.insert("1.0", content.strip())
        text.configure(state="disabled")

        notebook.add(frame, text=title)

    def _entry(
        self,
        parent: ttk.LabelFrame,
        label: str,
        key: str,
        row: int,
        column: int,
        show: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=8, pady=6)
        entry = ttk.Entry(parent, textvariable=self.vars[key], show=show or "")
        entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 8), pady=6)

    def _update_password_visibility(self) -> None:
        if getattr(self, "password_entry", None) is None:
            return

        show_password = bool(self.vars["show_password"].get())
        self.password_entry.configure(show="" if show_password else "*")

    def _bind_paste_support(self, entry: tk.Entry) -> None:
        entry.bind("<Control-v>", lambda event: self._paste_into_entry(entry))
        entry.bind("<Control-V>", lambda event: self._paste_into_entry(entry))
        entry.bind("<Shift-Insert>", lambda event: self._paste_into_entry(entry))
        entry.bind("<Button-3>", lambda event: self._show_entry_context_menu(event, entry))

    def _show_entry_context_menu(self, event: tk.Event, entry: tk.Entry) -> str:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Вставить", command=lambda: self._paste_into_entry(entry))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()
        return "break"

    def _paste_into_entry(self, entry: tk.Entry) -> str:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"

        if not isinstance(text, str):
            text = str(text)

        try:
            if entry.selection_present():
                entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

        insert_pos = entry.index("insert")
        entry.insert(insert_pos, text)
        entry.icursor(insert_pos + len(text))
        return "break"

    def _button(
        self,
        parent: ttk.LabelFrame,
        text: str,
        command: Any,
        row: int,
        column: int,
    ) -> None:
        button = ttk.Button(parent, text=text, command=command)
        button.grid(row=row, column=column, sticky="ew", padx=6, pady=6)
        self.action_buttons.append(button)

    def _load_settings(self) -> None:
        if not self.settings_path.exists():
            return

        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log(f"Не удалось загрузить сохраненные поля: {exc}")
            return

        for key, value in data.items():
            if key not in self.vars:
                continue
            if isinstance(self.vars[key], tk.BooleanVar):
                self.vars[key].set(bool(value))
            else:
                self.vars[key].set("" if value is None else str(value))

        self._log(f"Загружены сохраненные поля из {self.settings_path}")

    def _save_settings(self) -> None:
        data = self._settings_payload()
        self.settings_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._set_status("Поля сохранены")
        self._log(f"Поля сохранены в {self.settings_path}")

    def _settings_payload(self) -> dict[str, Any]:
        return {
            "vps_host": self.vars["vps_host"].get().strip(),
            "vps_user": self.vars["vps_user"].get().strip(),
            "ssh_port": self.vars["ssh_port"].get().strip(),
            "domain": self.vars["domain"].get().strip(),
            "server_ip": self.vars["server_ip"].get().strip(),
            "token": self.vars["token"].get().strip(),
            "proxy_name": self.vars["proxy_name"].get().strip(),
            "local_port": self.vars["local_port"].get().strip(),
            "startup_delay": self.vars["startup_delay"].get().strip(),
            "start_after_setup": bool(self.vars["start_after_setup"].get()),
            "check_public_health": bool(self.vars["check_public_health"].get()),
        }

    def _collect_config(self) -> dict[str, Any]:
        config = self._settings_payload()
        config["vps_password"] = self.vars["vps_password"].get()

        if not config["domain"]:
            raise ValueError("Поле домена обязательно.")
        if not config["proxy_name"]:
            config["proxy_name"] = "familyone-web"
        if not config["local_port"]:
            config["local_port"] = "8080"
        if not config["ssh_port"]:
            config["ssh_port"] = "22"
        if not config["startup_delay"]:
            config["startup_delay"] = "45"

        try:
            config["ssh_port"] = int(str(config["ssh_port"]).strip())
            config["local_port"] = int(str(config["local_port"]).strip())
            config["startup_delay"] = int(str(config["startup_delay"]).strip())
        except ValueError as exc:
            raise ValueError("Порты и задержка старта должны быть числами.") from exc

        config["server_ip"] = config["server_ip"] or config["vps_host"]
        return config

    def _start_task(self, title: str, worker: Any, config: dict[str, Any] | None = None) -> None:
        if self.busy:
            messagebox.showinfo(APP_TITLE, "Сейчас уже выполняется другая задача.")
            return

        self.busy = True
        self._set_buttons_state("disabled")
        self._set_status(f"{title}...")
        self._log("")
        self._log(f"=== {title} ===")

        def run() -> None:
            try:
                worker(config or {})
            except Exception as exc:
                self.output_queue.put(("log", traceback.format_exc().rstrip()))
                self.output_queue.put(("done", (title, False, str(exc))))
            else:
                self.output_queue.put(("done", (title, True, "")))

        threading.Thread(target=run, daemon=True).start()

    def _drain_output_queue(self) -> None:
        while True:
            try:
                kind, payload = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._log(str(payload))
            elif kind == "status":
                self._set_status(str(payload))
            elif kind == "set_value":
                key, value = payload
                if key in self.vars:
                    self.vars[key].set(value)
            elif kind == "done":
                title, ok, message = payload
                self.busy = False
                self._set_buttons_state("normal")
                if ok:
                    self._set_status(f"{title}: готово")
                    self._save_settings()
                    self._log(f"=== {title}: готово ===")
                else:
                    self._set_status(f"{title}: ошибка")
                    self._log(f"=== {title}: ошибка ===")
                    messagebox.showerror(APP_TITLE, f"{title}: ошибка.\n\n{message}")

        self.after(120, self._drain_output_queue)

    def _set_buttons_state(self, state: str) -> None:
        for button in self.action_buttons:
            button.configure(state=state)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _enqueue_log(self, message: str) -> None:
        self.output_queue.put(("log", message))

    def _enqueue_status(self, message: str) -> None:
        self.output_queue.put(("status", message))

    def _run_command(self, args: list[str], cwd: Path | None = None) -> str:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            args,
            cwd=str(cwd or self.project_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
            creationflags=creationflags,
        )

        collected: list[str] = []
        stdout_done = threading.Event()
        output_queue: queue.Queue[str] = queue.Queue()

        def pump_stdout() -> None:
            try:
                assert process.stdout is not None
                for raw_line in process.stdout:
                    output_queue.put(raw_line.rstrip())
            finally:
                stdout_done.set()

        threading.Thread(target=pump_stdout, daemon=True).start()

        return_code: int | None = None
        process_exited_at: float | None = None
        warned_about_stdout = False
        detached_stdout = False

        while True:
            try:
                while True:
                    line = output_queue.get_nowait()
                    collected.append(line)
                    self._enqueue_log(line)
            except queue.Empty:
                pass

            if return_code is None:
                return_code = process.poll()
                if return_code is not None:
                    process_exited_at = time.monotonic()

            if return_code is not None:
                if stdout_done.wait(timeout=0.2):
                    break

                assert process_exited_at is not None
                if time.monotonic() - process_exited_at >= 1.0:
                    if not warned_about_stdout:
                        self._enqueue_log(
                            "Команда уже завершилась, но поток вывода не закрылся сразу. "
                            "Продолжаю работу без дополнительного ожидания."
                        )
                        warned_about_stdout = True
                    detached_stdout = True
                    break
            else:
                time.sleep(0.1)

        try:
            while True:
                line = output_queue.get_nowait()
                collected.append(line)
                self._enqueue_log(line)
        except queue.Empty:
            pass

        if process.stdout is not None and not detached_stdout:
            try:
                process.stdout.close()
            except Exception:
                pass

        if return_code is None:
            return_code = process.wait(timeout=1)

        output = "\n".join(collected).strip()
        if return_code != 0:
            raise RuntimeError(f"Команда завершилась с кодом {return_code}.")
        return output

    def _run_powershell_script(
        self,
        script_path: Path,
        named_args: dict[str, Any] | None = None,
        switches: list[str] | None = None,
    ) -> str:
        command = [
            powershell_executable(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]

        for key, value in (named_args or {}).items():
            if value is None or value == "":
                continue
            command.extend([f"-{key}", str(value)])

        for switch in switches or []:
            command.append(f"-{switch}")

        self._enqueue_log(f"Запуск PowerShell: {script_path.name}")
        return self._run_command(command, cwd=self.project_root)

    def _ensure_paramiko(self) -> Any:
        if self.paramiko_module is not None:
            return self.paramiko_module

        if bundled_paramiko is not None:
            self.paramiko_module = bundled_paramiko
            return self.paramiko_module

        if getattr(sys, "frozen", False):
            raise RuntimeError(
                "SSH-модуль paramiko не найден внутри EXE. Пересоберите программу с включенным paramiko."
            )

        if importlib.util.find_spec("paramiko") is None:
            self._enqueue_log("Модуль paramiko не найден. Устанавливаю для текущего Python...")
            self._run_command(
                [sys.executable, "-m", "pip", "install", "--user", "paramiko"],
                cwd=self.project_root,
            )

        self.paramiko_module = importlib.import_module("paramiko")
        return self.paramiko_module

    def _open_ssh_client(self, config: dict[str, Any]) -> Any:
        if not config["vps_host"]:
            raise ValueError("Нужно указать хост VPS.")
        if not config["vps_user"]:
            raise ValueError("Нужно указать пользователя VPS.")
        if not config["vps_password"]:
            raise ValueError("Для этого действия нужен пароль от VPS.")

        paramiko = self._ensure_paramiko()
        self._enqueue_log(f"Подключение к {config['vps_user']}@{config['vps_host']}:{config['ssh_port']} ...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=config["vps_host"],
            port=int(config["ssh_port"]),
            username=config["vps_user"],
            password=config["vps_password"],
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
        )
        return client

    def _ssh_exec(self, config: dict[str, Any], command: str, timeout: int = 60) -> str:
        client = self._open_ssh_client(config)
        try:
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "replace").strip()
            err = stderr.read().decode("utf-8", "replace").strip()
            exit_code = stdout.channel.recv_exit_status()
        finally:
            client.close()

        if out:
            self._enqueue_log(out)
        if err:
            self._enqueue_log(err)

        if exit_code != 0:
            raise RuntimeError(f"SSH-команда завершилась с кодом {exit_code}.")

        return out

    def _bootstrap_frps_on_vps(self, config: dict[str, Any]) -> None:
        vps_user = str(config.get("vps_user", "")).strip().lower()
        if vps_user != "root":
            raise RuntimeError(
                "Автоматическая настройка FRPS на новом VPS поддерживается только для пользователя root."
            )

        local_script = self.project_root / "infra" / "frp" / "setup-frps.sh"
        if not local_script.exists():
            raise RuntimeError(f"Не найден серверный скрипт настройки: {local_script}")

        remote_script = "/root/codex-setup-frps.sh"
        script_text = local_script.read_text(encoding="utf-8").replace("\r\n", "\n")

        self._enqueue_log("Конфиг FRPS не найден. Настраиваю FRPS и Caddy на новом VPS...")
        client = self._open_ssh_client(config)
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_script, "wb") as remote_file:
                    remote_file.write(script_text.encode("utf-8"))
                sftp.chmod(remote_script, 0o755)
            finally:
                sftp.close()

            command_parts = [
                "bash",
                shlex.quote(remote_script),
                "--domain",
                shlex.quote(str(config["domain"]).strip()),
            ]
            token = str(config.get("token", "")).strip()
            if token:
                command_parts.extend(["--token", shlex.quote(token)])

            remote_command = " ".join(command_parts)
            self._enqueue_log("Запускаю настройку VPS. Это может занять несколько минут...")
            _, stdout, stderr = client.exec_command(remote_command, timeout=1800)
            out = stdout.read().decode("utf-8", "replace").strip()
            err = stderr.read().decode("utf-8", "replace").strip()
            exit_code = stdout.channel.recv_exit_status()
        finally:
            client.close()

        if out:
            self._enqueue_log(out)
        if err:
            self._enqueue_log(err)

        if exit_code != 0:
            raise RuntimeError(f"Не удалось настроить FRPS на VPS. Код завершения: {exit_code}.")

        self._enqueue_log("FRPS и Caddy настроены на VPS.")

    def _ensure_token(self, config: dict[str, Any]) -> str:
        token = str(config.get("token", "")).strip()
        if token:
            return token

        token = self._fetch_token(config)
        self.output_queue.put(("set_value", ("token", token)))
        config["token"] = token
        return token

    def _fetch_token(self, config: dict[str, Any], allow_bootstrap: bool = True) -> str:
        script = """
config_path=""
for candidate in \
  /etc/frp/frps.toml \
  /etc/frps.toml \
  /usr/local/etc/frp/frps.toml \
  /etc/frp/frps.ini \
  /etc/frps.ini \
  /usr/local/etc/frp/frps.ini
do
  if [ -f "$candidate" ]; then
    config_path="$candidate"
    break
  fi
done

if [ -z "$config_path" ]; then
  config_path=$(systemctl show -p ExecStart frps 2>/dev/null | sed -n 's/.* -c \\([^ ;"]*\\).*/\\1/p' | head -n 1)
fi

if [ -z "$config_path" ] || [ ! -f "$config_path" ]; then
  config_path=$(find /etc /usr/local/etc /opt /root -maxdepth 4 -type f \\( -name frps.toml -o -name frps.ini \\) 2>/dev/null | head -n 1)
fi

if [ -z "$config_path" ] || [ ! -f "$config_path" ]; then
  echo __FRPS_MISSING__
  exit 0
fi

printf '__FRPS_PATH__=%s\\n' "$config_path"
awk '
/^[[:space:]]*(auth\\.)?token[[:space:]]*=/ {
  line=$0
  sub(/^[[:space:]]*(auth\\.)?token[[:space:]]*=[[:space:]]*/, "", line)
  sub(/[[:space:]]*[#;].*$/, "", line)
  gsub(/^"/, "", line)
  gsub(/"$/, "", line)
  gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
  print line
  exit
}
' "$config_path"
""".strip()
        command = f"sh -lc {shlex.quote(script)}"
        output = self._ssh_exec(config, command)
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        config_path = ""
        token = ""

        for line in lines:
            if line == "__FRPS_MISSING__":
                if allow_bootstrap:
                    self._bootstrap_frps_on_vps(config)
                    return self._fetch_token(config, allow_bootstrap=False)
                raise RuntimeError(
                    "На VPS не найден конфиг FRPS. Проверьте, что frps установлен, "
                    "а его конфиг доступен в /etc, /usr/local/etc, /opt или /root."
                )
            if line.startswith("__FRPS_PATH__="):
                config_path = line.partition("=")[2].strip()
                continue
            token = line

        if not token:
            location_hint = f" из {config_path}" if config_path else ""
            raise RuntimeError(f"Не удалось прочитать FRP токен{location_hint}.")
        if config_path:
            self._enqueue_log(f"FRP токен получен с VPS ({config_path}).")
        else:
            self._enqueue_log("FRP токен получен с VPS.")
        return token

    def _check_vps(self, config: dict[str, Any]) -> None:
        command = (
            "sh -lc '"
            "printf \"frps_enabled=%s\\n\" \"$(systemctl is-enabled frps 2>/dev/null || true)\"; "
            "printf \"frps_active=%s\\n\" \"$(systemctl is-active frps 2>/dev/null || true)\"; "
            "printf \"caddy_enabled=%s\\n\" \"$(systemctl is-enabled caddy 2>/dev/null || true)\"; "
            "printf \"caddy_active=%s\\n\" \"$(systemctl is-active caddy 2>/dev/null || true)\"; "
            "ss -lntp | egrep \":80|:443|:7000|:8080\" || true"
            "'"
        )
        self._ssh_exec(config, command)

    def _enable_vps_autostart(self, config: dict[str, Any]) -> None:
        command = (
            "sh -lc '"
            "systemctl enable --now frps caddy >/dev/null 2>&1; "
            "printf \"frps_enabled=%s\\n\" \"$(systemctl is-enabled frps)\"; "
            "printf \"frps_active=%s\\n\" \"$(systemctl is-active frps)\"; "
            "printf \"caddy_enabled=%s\\n\" \"$(systemctl is-enabled caddy)\"; "
            "printf \"caddy_active=%s\\n\" \"$(systemctl is-active caddy)\""
            "'"
        )
        self._ssh_exec(config, command)

    def _configure_pc(self, config: dict[str, Any]) -> None:
        token = self._ensure_token(config)
        script = self.project_root / "scripts" / "setup-frpc.ps1"
        args = {
            "ServerIp": config["server_ip"],
            "Token": token,
            "Domain": config["domain"],
            "ProxyName": config["proxy_name"],
            "LocalPort": config["local_port"],
        }
        self._run_powershell_script(script, named_args=args)

    def _enable_pc_autostart(self, config: dict[str, Any]) -> None:
        script = self.project_root / "scripts" / "setup-pc-autostart.ps1"
        args = {
            "DelaySeconds": config["startup_delay"],
        }
        self._run_powershell_script(script, named_args=args)

    def _start_server_worker(self, _: dict[str, Any]) -> None:
        script = self.project_root / "start-server.ps1"
        self._run_powershell_script(script, switches=["NoTunnel"])

    def _stop_server_worker(self, _: dict[str, Any]) -> None:
        script = self.project_root / "stop-server.ps1"
        self._run_powershell_script(script)

    def _health_check(self, config: dict[str, Any]) -> None:
        local_urls = [
            "http://127.0.0.1:5000/health",
            "http://127.0.0.1:8080/api/health",
        ]

        for url in local_urls:
            self._http_get(url)

        if config["check_public_health"]:
            expected_ip = self._resolve_host_ip(str(config.get("server_ip", "")).strip())
            if expected_ip:
                self._enqueue_log(f"Ожидаемый IP VPS: {expected_ip}")
            try:
                ip = socket.gethostbyname(config["domain"])
                self._enqueue_log(f"DNS: {config['domain']} -> {ip}")
                if expected_ip and ip != expected_ip:
                    raise RuntimeError(
                        f"Домен {config['domain']} на этом ПК резолвится в {ip}, "
                        f"а в поле 'IP сервера' указан {expected_ip}. "
                        "Похоже, локальный DNS-кэш или DNS-сервер всё ещё отдают старый VPS. "
                        "Выполните 'ipconfig /flushdns' и повторите проверку. "
                        "Если IP домена меняли совсем недавно, можно временно снять галочку "
                        "'Проверять внешний HTTPS после действий' и продолжить настройку без внешней проверки."
                    )
            except Exception as exc:
                self._enqueue_log(f"Ошибка DNS-проверки: {exc}")
                if isinstance(exc, RuntimeError):
                    raise
            self._http_get(f"https://{config['domain']}/api/health")

    def _resolve_host_ip(self, host: str) -> str:
        candidate = host.strip()
        if not candidate:
            return ""

        try:
            return socket.gethostbyname(candidate)
        except Exception:
            return candidate

    def _http_get(self, url: str) -> None:
        self._enqueue_log(f"Проверка URL: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": "FamilyOneSetupUI/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                body = response.read().decode("utf-8", "replace").strip()
                self._enqueue_log(f"HTTP {response.status}: {url}")
                if body:
                    self._enqueue_log(body[:700])
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace").strip()
            raise RuntimeError(f"{url} -> HTTP {exc.code}\n{body[:500]}") from exc
        except Exception as exc:
            raise RuntimeError(f"{url} -> {exc}") from exc

    def _full_setup(self, config: dict[str, Any]) -> None:
        if config["vps_password"]:
            self._enqueue_status("Проверка VPS")
            self._check_vps(config)
            self._enqueue_status("Получение FRP токена")
            self._ensure_token(config)
            self._enqueue_status("Включение автозапуска VPS")
            self._enable_vps_autostart(config)
        else:
            self._enqueue_log("Пароль от VPS не указан. Пропускаю действия на VPS и использую токен/хост вручную.")

        self._enqueue_status("Настройка этого ПК")
        self._configure_pc(config)
        self._enqueue_status("Включение автозапуска ПК")
        self._enable_pc_autostart(config)

        if config["start_after_setup"]:
            self._enqueue_status("Запуск сервера")
            self._start_server_worker(config)

        self._enqueue_status("Проверка доступности")
        self._health_check(config)

    def _config_or_error(self) -> dict[str, Any] | None:
        try:
            return self._collect_config()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return None

    def _start_check_vps(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Проверка VPS", self._check_vps, config)

    def _start_fetch_token(self) -> None:
        config = self._config_or_error()
        if not config:
            return

        def worker(snapshot: dict[str, Any]) -> None:
            token = self._fetch_token(snapshot)
            self.output_queue.put(("set_value", ("token", token)))

        self._start_task("Получение FRP токена", worker, config)

    def _start_enable_vps_autostart(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Включение автозапуска VPS", self._enable_vps_autostart, config)

    def _start_configure_pc(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Настройка этого ПК", self._configure_pc, config)

    def _start_enable_pc_autostart(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Включение автозапуска ПК", self._enable_pc_autostart, config)

    def _start_server(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Запуск сервера", self._start_server_worker, config)

    def _stop_server(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Остановка сервера", self._stop_server_worker, config)

    def _start_health_check(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Проверка доступности", self._health_check, config)

    def _start_full_setup(self) -> None:
        config = self._config_or_error()
        if config:
            self._start_task("Полная настройка", self._full_setup, config)


def main() -> None:
    app = SetupUi()
    app.mainloop()


if __name__ == "__main__":
    main()
