"""
EcoAlerta - Protótipo acadêmico em Python/Tkinter com armazenamento JSON local
Requisitos: Python 3.10+ (recomendado), Tkinter (normalmente incluído).
Bibliotecas opcionais/recomendadas:
    python -m pip install Pillow cryptography

Execute:
    python ecoalerta.py

Observações:
- A recuperação gera um código de demonstração na própria tela. Para envio real por e-mail,
  é necessário configurar um serviço SMTP e credenciais fora do código.
- A criptografia de evidências usa Fernet quando cryptography está instalado.
- Os dados são salvos localmente em ecoalerta_dados/ecoalerta_dados.json; o GitHub compartilha o código, não sincroniza alterações em tempo real.
- Este é um protótipo acadêmico local, não um sistema pronto para produção.
"""

import os
import json
import hmac
import shutil
import hashlib
import secrets
import sqlite3
import zipfile
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None

try:
    from PIL import Image
except ImportError:
    Image = None


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "ecoalerta_dados"
EVIDENCE_DIR = DATA_DIR / "evidencias"
JSON_PATH = DATA_DIR / "ecoalerta_dados.json"
LEGACY_DB_PATH = DATA_DIR / "ecoalerta.db"  # usado apenas para migrar instalações antigas
KEY_PATH = DATA_DIR / "chave_fernet.key"

DATA_DIR.mkdir(exist_ok=True)
EVIDENCE_DIR.mkdir(exist_ok=True)


def now():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 300_000)
    return salt.hex() + "$" + digest.hex()


def password_matches(password, stored):
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 300_000
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


class JsonBackedConnection(sqlite3.Connection):
    """Conexão somente em memória; a persistência é feita em arquivo JSON."""
    persist_callback = None

    def commit(self):
        super().commit()
        if self.persist_callback:
            self.persist_callback()


class Database:
    TABLES = {
        "users": ("id", "name", "email", "password_hash", "role", "created_at"),
        "occurrences": ("id", "title", "category", "description", "location", "occurrence_date", "status", "created_by", "created_at"),
        "evidences": ("id", "occurrence_id", "stored_name", "original_name", "sha256", "encrypted", "added_at"),
        "audit": ("id", "user_id", "action", "details", "created_at"),
    }

    def __init__(self):
        # O SQLite existe apenas durante a execução para organizar consultas.
        # Nenhum arquivo de banco de dados é criado: os dados persistentes ficam em JSON.
        self.conn = sqlite3.connect(":memory:", factory=JsonBackedConnection)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
        self.conn.persist_callback = self.save_json
        if JSON_PATH.exists():
            self.load_json()
            self.ensure_demo_images()
        elif LEGACY_DB_PATH.exists():
            # Migra a base local da versão anterior para JSON sem descartar os registros.
            self.migrate_legacy_database()
            self.seed_demo_data()
            self.save_json()
            LEGACY_DB_PATH.unlink(missing_ok=True)
        else:
            self.seed_demo_data()
            self.save_json()

    def create_tables(self):
        self.conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'tecnico', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            category TEXT NOT NULL, description TEXT NOT NULL, location TEXT NOT NULL,
            occurrence_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Aberta',
            created_by INTEGER NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS evidences (
            id INTEGER PRIMARY KEY AUTOINCREMENT, occurrence_id INTEGER NOT NULL,
            stored_name TEXT NOT NULL, original_name TEXT NOT NULL, sha256 TEXT NOT NULL,
            encrypted INTEGER NOT NULL DEFAULT 0, added_at TEXT NOT NULL,
            FOREIGN KEY(occurrence_id) REFERENCES occurrences(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            action TEXT NOT NULL, details TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """)

    def save_json(self):
        payload = {"format_version": 1, "saved_at": now(), "tables": {}}
        for table, columns in self.TABLES.items():
            rows = self.conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            payload["tables"][table] = [
                {column: row[column] for column in columns} for row in rows
            ]
        temp_path = JSON_PATH.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(JSON_PATH)

    def load_json(self):
        try:
            payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            tables = payload.get("tables", {})
            for table, columns in self.TABLES.items():
                for item in tables.get(table, []):
                    values = [item.get(column) for column in columns]
                    marks = ",".join("?" for _ in columns)
                    names = ",".join(columns)
                    self.conn.execute(
                        f"INSERT INTO {table} ({names}) VALUES ({marks})", values
                    )
            self.conn.commit()
        except Exception as exc:
            message = f"Não foi possível ler {JSON_PATH.name}: {exc}"
            raise RuntimeError(message) from exc

    def migrate_legacy_database(self):
        legacy = sqlite3.connect(LEGACY_DB_PATH)
        legacy.row_factory = sqlite3.Row
        try:
            available = {row[0] for row in legacy.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            for table, columns in self.TABLES.items():
                if table not in available:
                    continue
                rows = legacy.execute(f"SELECT * FROM {table}").fetchall()
                for row in rows:
                    values = [row[column] for column in columns if column in row.keys()]
                    names = [column for column in columns if column in row.keys()]
                    if not names:
                        continue
                    marks = ",".join("?" for _ in names)
                    self.conn.execute(
                        f"INSERT OR IGNORE INTO {table} ({','.join(names)}) VALUES ({marks})", values
                    )
            self.conn.commit()
        finally:
            legacy.close()

    def create_demo_image(self, filename, title, kind):
        path = EVIDENCE_DIR / filename
        if path.exists():
            return path
        try:
            from PIL import Image as PILImage, ImageDraw
            image = PILImage.new("RGB", (900, 560), (232, 242, 232))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((35, 35, 865, 525), radius=28, fill=(250, 252, 248), outline=(40, 105, 65), width=5)
            draw.text((75, 75), "ECOALERTA | EVIDENCIA DEMONSTRATIVA", fill=(25, 85, 52))
            if kind == "floresta":
                draw.rectangle((70, 350, 830, 470), fill=(174, 139, 94))
                for x, y in [(180, 270), (330, 235), (520, 280), (700, 230)]:
                    draw.rectangle((x-12, y+25, x+12, 390), fill=(115, 78, 48))
                    draw.ellipse((x-65, y-55, x+65, y+75), fill=(54, 130, 73))
                draw.text((75, 480), "Registro ilustrativo de area de vegetacao", fill=(45, 70, 48))
            elif kind == "lixo":
                draw.rectangle((70, 365, 830, 465), fill=(190, 178, 145))
                for x, color in [(220, (80, 150, 190)), (370, (210, 175, 80)), (540, (95, 145, 90)), (690, (180, 110, 90))]:
                    draw.rounded_rectangle((x-45, 250, x+45, 390), radius=12, fill=color)
                draw.text((75, 480), "Registro ilustrativo de descarte irregular", fill=(65, 65, 55))
            else:
                draw.rectangle((70, 365, 830, 465), fill=(120, 145, 100))
                for x, y in [(250, 330), (410, 290), (580, 340)]:
                    draw.ellipse((x-50, y-95, x+50, y+55), fill=(224, 110, 45))
                    draw.ellipse((x-28, y-65, x+28, y+25), fill=(245, 190, 75))
                draw.text((75, 480), "Registro ilustrativo de foco de queimada", fill=(65, 65, 55))
            image.save(path, format="PNG")
        except Exception:
            # PNG mínimo válido como alternativa se Pillow não estiver instalado.
            import base64
            tiny_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK2kAAAAASUVORK5CYII=")
            path.write_bytes(tiny_png)
        return path

    def ensure_demo_images(self):
        for filename, title, kind in [
            ("demo_floresta.png", "Área de vegetação", "floresta"),
            ("demo_lixo.png", "Descarte irregular", "lixo"),
            ("demo_queimada.png", "Queimada", "fogo"),
        ]:
            self.create_demo_image(filename, title, kind)

    def seed_demo_data(self):
        coordinator = self.conn.execute(
            "SELECT id FROM users WHERE email=?", ("coordenador@ecoalerta.local",)
        ).fetchone()
        if not coordinator:
            cur = self.conn.execute(
                "INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                ("Coordenador EcoAlerta", "coordenador@ecoalerta.local", password_hash("EcoAlerta@123"), "coordenador", now())
            )
            coordinator_id = cur.lastrowid
        else:
            coordinator_id = coordinator["id"]

        technician = self.conn.execute(
            "SELECT id FROM users WHERE email=?", ("tecnico@ecoalerta.local",)
        ).fetchone()
        if not technician:
            cur = self.conn.execute(
                "INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                ("Técnico Demonstrativo", "tecnico@ecoalerta.local", password_hash("Tecnico@123"), "tecnico", now())
            )
            technician_id = cur.lastrowid
        else:
            technician_id = technician["id"]

        if self.conn.execute("SELECT COUNT(*) n FROM occurrences").fetchone()["n"] == 0:
            samples = [
                ("Desmatamento em área verde", "Desmatamento", "Registro demonstrativo de retirada irregular de vegetação.", "Parque Municipal - Setor Norte", "10/11/2026", "Em análise", "demo_floresta.png", "evidencia_desmatamento.png"),
                ("Descarte irregular de resíduos", "Descarte irregular de lixo", "Resíduos descartados em local não autorizado.", "Rua das Palmeiras, 120", "12/11/2026", "Aberta", "demo_lixo.png", "evidencia_descarte.png"),
                ("Foco de queimada", "Queimada", "Pequeno foco de queimada registrado para fins de demonstração.", "Área rural - Estrada do Lago", "14/11/2026", "Resolvida", "demo_queimada.png", "evidencia_queimada.png"),
            ]
            self.ensure_demo_images()
            for title, category, description, location, date, status, filename, original_name in samples:
                cur = self.conn.execute(
                    "INSERT INTO occurrences(title,category,description,location,occurrence_date,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (title, category, description, location, date, status, technician_id, now())
                )
                raw = (EVIDENCE_DIR / filename).read_bytes()
                self.conn.execute(
                    "INSERT INTO evidences(occurrence_id,stored_name,original_name,sha256,encrypted,added_at) VALUES(?,?,?,?,?,?)",
                    (cur.lastrowid, filename, original_name, sha256_bytes(raw), 0, now())
                )
        self.conn.commit()

    def reset_demo_data(self):
        self.conn.execute("DELETE FROM evidences")
        self.conn.execute("DELETE FROM occurrences")
        self.conn.execute("DELETE FROM audit")
        self.conn.execute("DELETE FROM users")
        self.conn.execute("DELETE FROM sqlite_sequence")
        self.conn.commit()
        for file in EVIDENCE_DIR.iterdir():
            if file.is_file():
                file.unlink(missing_ok=True)
        if KEY_PATH.exists():
            KEY_PATH.unlink()
        self.seed_demo_data()

    def log(self, user_id, action, details=""):
        self.conn.execute(
            "INSERT INTO audit(user_id,action,details,created_at) VALUES(?,?,?,?)",
            (user_id, action, details, now())
        )
        self.conn.commit()

    def close(self):
        self.conn.commit()
        self.conn.close()


class EcoAlertaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EcoAlerta | Monitoramento Ambiental")
        self.root.geometry("1050x680")
        self.root.minsize(900, 600)
        self.root.configure(bg="#f3f6f3")
        self.db = Database()
        self.current_user = None
        self.recovery_codes = {}
        self.setup_style()
        self.show_login()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=28, font=("Arial", 10))
        style.configure("Treeview.Heading", font=("Arial", 10, "bold"))
        style.configure("TButton", font=("Arial", 10), padding=7)
        style.configure("Accent.TButton", background="#247a4b", foreground="white")
        style.map("Accent.TButton", background=[("active", "#1b603a")])

    def clear(self):
        for child in self.root.winfo_children():
            child.destroy()

    def heading(self, parent, title, subtitle=None):
        tk.Label(parent, text=title, bg="#f3f6f3", fg="#174b32",
                 font=("Arial", 21, "bold")).pack(anchor="w", pady=(0, 4))
        if subtitle:
            tk.Label(parent, text=subtitle, bg="#f3f6f3", fg="#52665a",
                     font=("Arial", 10)).pack(anchor="w", pady=(0, 16))

    def show_login(self):
        self.current_user = None
        self.clear()
        outer = tk.Frame(self.root, bg="#e7f1e9")
        outer.pack(fill="both", expand=True)
        card = tk.Frame(outer, bg="white", padx=42, pady=35,
                        highlightthickness=1, highlightbackground="#d5e2d8")
        card.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(card, text="🌱 ECOALERTA", bg="white", fg="#17633b",
                 font=("Arial", 25, "bold")).pack(pady=(0, 5))
        tk.Label(card, text="Sistema de Monitoramento Ambiental", bg="white",
                 fg="#637568", font=("Arial", 10)).pack(pady=(0, 22))
        tk.Label(card, text="E-mail", bg="white", anchor="w").pack(fill="x")
        email = ttk.Entry(card, width=38)
        email.pack(pady=(4, 12), ipady=5)
        tk.Label(card, text="Senha", bg="white", anchor="w").pack(fill="x")
        password = ttk.Entry(card, width=38, show="•")
        password.pack(pady=(4, 18), ipady=5)

        def login(event=None):
            e = email.get().strip().lower()
            p = password.get()
            user = self.db.conn.execute("SELECT * FROM users WHERE email=?", (e,)).fetchone()
            if user and password_matches(p, user["password_hash"]):
                self.current_user = dict(user)
                self.db.log(user["id"], "LOGIN", "Acesso ao sistema")
                self.show_dashboard()
            else:
                messagebox.showerror("Acesso não autorizado", "E-mail ou senha inválidos.")

        ttk.Button(card, text="Entrar", command=login, style="Accent.TButton").pack(fill="x")
        links = tk.Frame(card, bg="white")
        links.pack(fill="x", pady=(12, 0))
        ttk.Button(links, text="Criar conta", command=self.show_register).pack(side="left")
        ttk.Button(links, text="Esqueci minha senha", command=self.show_recovery).pack(side="right")
        password.bind("<Return>", login)

    def show_register(self):
        self.clear()
        frame = tk.Frame(self.root, bg="#f3f6f3", padx=35, pady=28)
        frame.pack(fill="both", expand=True)
        self.heading(frame, "Criar conta", "Escolha o perfil de acesso para o novo usuário.")
        fields = {}
        for label, key, show in [
            ("Nome completo", "name", ""),
            ("E-mail", "email", ""),
            ("Senha (mínimo 8 caracteres)", "password", "•"),
            ("Confirmar senha", "confirm", "•")
        ]:
            tk.Label(frame, text=label, bg="#f3f6f3").pack(anchor="w")
            entry = ttk.Entry(frame, width=48, show=show)
            entry.pack(anchor="w", pady=(3, 12), ipady=4)
            fields[key] = entry

        tk.Label(frame, text="Tipo de usuário", bg="#f3f6f3").pack(anchor="w")
        role_var = tk.StringVar(value="Técnico")
        role_combo = ttk.Combobox(frame, textvariable=role_var, values=["Técnico", "Coordenador"],
                                  state="readonly", width=45)
        role_combo.pack(anchor="w", pady=(3, 8), ipady=3)
        authorization = {"ok": False}

        def authorize_coordinator(event=None):
            authorization["ok"] = False
            if role_var.get() != "Coordenador":
                return
            popup = tk.Toplevel(self.root)
            popup.title("Autorização de coordenador")
            popup.transient(self.root)
            popup.grab_set()
            popup.resizable(False, False)
            box = tk.Frame(popup, padx=22, pady=18)
            box.pack(fill="both", expand=True)
            tk.Label(box, text="Criação de conta de coordenador", font=("Arial", 12, "bold")).pack(anchor="w")
            tk.Label(box, text=("Por segurança, informe a senha de um coordenador já cadastrado.\n"
                                "Essa confirmação autoriza a criação do novo perfil de coordenador."),
                     justify="left", wraplength=360).pack(anchor="w", pady=(8, 12))
            tk.Label(box, text="Senha do coordenador:").pack(anchor="w")
            auth_entry = ttk.Entry(box, width=42, show="•")
            auth_entry.pack(fill="x", pady=(4, 12))

            def confirm_authorization():
                entered = auth_entry.get()
                coordinators = self.db.conn.execute(
                    "SELECT password_hash FROM users WHERE role='coordenador'"
                ).fetchall()
                valid = any(password_matches(entered, item["password_hash"]) for item in coordinators)
                if not valid:
                    messagebox.showerror("Autorização negada", "A senha informada não corresponde a um coordenador cadastrado.", parent=popup)
                    return
                authorization["ok"] = True
                popup.destroy()

            def cancel_authorization():
                role_var.set("Técnico")
                authorization["ok"] = False
                popup.destroy()

            actions = tk.Frame(box)
            actions.pack(anchor="e")
            ttk.Button(actions, text="Cancelar", command=cancel_authorization).pack(side="left", padx=(0, 8))
            ttk.Button(actions, text="Autorizar", command=confirm_authorization, style="Accent.TButton").pack(side="left")
            auth_entry.bind("<Return>", lambda event: confirm_authorization())
            auth_entry.focus_set()

        role_combo.bind("<<ComboboxSelected>>", authorize_coordinator)

        def save():
            name = fields["name"].get().strip()
            email = fields["email"].get().strip().lower()
            pw = fields["password"].get()
            confirm = fields["confirm"].get()
            selected_role = "coordenador" if role_var.get() == "Coordenador" else "tecnico"
            if not name or not email or not pw:
                messagebox.showwarning("Atenção", "Preencha todos os campos.")
                return
            if selected_role == "coordenador" and not authorization["ok"]:
                messagebox.showwarning("Autorização necessária", "É preciso validar a senha de um coordenador cadastrado.")
                return
            if "@" not in email or "." not in email:
                messagebox.showwarning("E-mail inválido", "Informe um e-mail válido.")
                return
            if len(pw) < 8:
                messagebox.showwarning("Senha fraca", "A senha deve ter pelo menos 8 caracteres.")
                return
            if pw != confirm:
                messagebox.showwarning("Senhas diferentes", "As senhas não conferem.")
                return
            try:
                cur = self.db.conn.execute(
                    "INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                    (name, email, password_hash(pw), selected_role, now())
                )
                self.db.conn.commit()
                self.db.log(cur.lastrowid, "CADASTRO_USUARIO", f"Conta criada com perfil {selected_role}")
                messagebox.showinfo("Sucesso", "Conta criada! Faça login.")
                self.show_login()
            except sqlite3.IntegrityError:
                messagebox.showerror("Cadastro", "Este e-mail já está cadastrado.")

        ttk.Button(frame, text="Cadastrar", command=save, style="Accent.TButton").pack(anchor="w", pady=8)
        ttk.Button(frame, text="Voltar ao login", command=self.show_login).pack(anchor="w")

    def show_recovery(self):
        self.clear()
        frame = tk.Frame(self.root, bg="#f3f6f3", padx=35, pady=28)
        frame.pack(fill="both", expand=True)
        self.heading(frame, "Recuperar senha", "Demonstração acadêmica de recuperação por código.")
        tk.Label(frame, text="Informe o e-mail cadastrado:", bg="#f3f6f3").pack(anchor="w")
        email_entry = ttk.Entry(frame, width=48)
        email_entry.pack(anchor="w", pady=(4, 12), ipady=4)

        def generate():
            email = email_entry.get().strip().lower()
            user = self.db.conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not user:
                messagebox.showerror("Recuperação", "E-mail não encontrado.")
                return
            code = f"{secrets.randbelow(1_000_000):06d}"
            self.recovery_codes[email] = (code, user["id"])
            messagebox.showinfo(
                "Código de demonstração",
                f"Seu código temporário é: {code}\n\nEm uma versão real, ele seria enviado por e-mail."
            )
            self.db.log(user["id"], "SOLICITOU_RECUPERACAO", "Código temporário gerado")

        ttk.Button(frame, text="Gerar código", command=generate).pack(anchor="w", pady=(0, 15))
        tk.Label(frame, text="Código recebido:", bg="#f3f6f3").pack(anchor="w")
        code_entry = ttk.Entry(frame, width=48)
        code_entry.pack(anchor="w", pady=(4, 12), ipady=4)
        tk.Label(frame, text="Nova senha:", bg="#f3f6f3").pack(anchor="w")
        pw_entry = ttk.Entry(frame, width=48, show="•")
        pw_entry.pack(anchor="w", pady=(4, 12), ipady=4)

        def reset():
            email = email_entry.get().strip().lower()
            saved = self.recovery_codes.get(email)
            if not saved or not hmac.compare_digest(saved[0], code_entry.get().strip()):
                messagebox.showerror("Código inválido", "Gere ou informe corretamente o código.")
                return
            pw = pw_entry.get()
            if len(pw) < 8:
                messagebox.showwarning("Senha fraca", "Use pelo menos 8 caracteres.")
                return
            self.db.conn.execute("UPDATE users SET password_hash=? WHERE email=?",
                                 (password_hash(pw), email))
            self.db.conn.commit()
            self.db.log(saved[1], "REDEFINIU_SENHA", "Senha redefinida por código")
            del self.recovery_codes[email]
            messagebox.showinfo("Sucesso", "Senha alterada. Faça login.")
            self.show_login()

        ttk.Button(frame, text="Redefinir senha", command=reset, style="Accent.TButton").pack(anchor="w")
        ttk.Button(frame, text="Voltar", command=self.show_login).pack(anchor="w", pady=8)

    def shell(self, title, subtitle=""):
        self.clear()
        top = tk.Frame(self.root, bg="#17633b", padx=22, pady=14)
        top.pack(fill="x")
        tk.Label(top, text="🌱 ECOALERTA", bg="#17633b", fg="white",
                 font=("Arial", 17, "bold")).pack(side="left")
        user_text = f'{self.current_user["name"]} | {self.current_user["role"].title()}'
        tk.Label(top, text=user_text, bg="#17633b", fg="white",
                 font=("Arial", 9)).pack(side="right")
        body = tk.Frame(self.root, bg="#f3f6f3", padx=25, pady=22)
        body.pack(fill="both", expand=True)
        self.heading(body, title, subtitle)
        return body

    def show_dashboard(self):
        body = self.shell("Painel principal", "Acompanhe e gerencie as ocorrências ambientais.")
        user_id = self.current_user["id"]
        role = self.current_user["role"]
        if role == "coordenador":
            total = self.db.conn.execute("SELECT COUNT(*) n FROM occurrences").fetchone()["n"]
            open_count = self.db.conn.execute("SELECT COUNT(*) n FROM occurrences WHERE status='Aberta'").fetchone()["n"]
            users = self.db.conn.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        else:
            total = self.db.conn.execute("SELECT COUNT(*) n FROM occurrences WHERE created_by=?", (user_id,)).fetchone()["n"]
            open_count = self.db.conn.execute("SELECT COUNT(*) n FROM occurrences WHERE created_by=? AND status='Aberta'", (user_id,)).fetchone()["n"]
            users = None

        stats = tk.Frame(body, bg="#f3f6f3")
        stats.pack(fill="x", pady=(0, 18))
        self.stat_card(stats, "Ocorrências cadastradas", total)
        self.stat_card(stats, "Ocorrências abertas", open_count)
        if users is not None:
            self.stat_card(stats, "Usuários cadastrados", users)

        actions = tk.Frame(body, bg="#f3f6f3")
        actions.pack(anchor="w", fill="x")
        ttk.Button(actions, text="＋ Nova ocorrência", command=self.show_occurrence_form,
                   style="Accent.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Consultar ocorrências", command=self.show_occurrences).pack(side="left", padx=8)
        ttk.Button(actions, text="Meu histórico", command=self.show_audit).pack(side="left", padx=8)
        if role == "coordenador":
            ttk.Button(actions, text="Importar / Exportar", command=self.backup_screen).pack(side="left", padx=8)
            ttk.Button(actions, text="Verificar evidências", command=self.verify_evidence).pack(side="left", padx=8)
        ttk.Button(actions, text="Sair", command=self.logout).pack(side="right")

        tk.Label(body, text="Últimas ocorrências", bg="#f3f6f3", fg="#174b32",
                 font=("Arial", 13, "bold")).pack(anchor="w", pady=(28, 8))
        self.make_occurrence_tree(body, limit=6)

    def stat_card(self, parent, title, value):
        card = tk.Frame(parent, bg="white", padx=18, pady=15,
                        highlightthickness=1, highlightbackground="#dce7de")
        card.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(card, text=str(value), bg="white", fg="#17633b",
                 font=("Arial", 23, "bold")).pack(anchor="w")
        tk.Label(card, text=title, bg="white", fg="#617267",
                 font=("Arial", 9)).pack(anchor="w")

    def visible_occurrences_query(self):
        if self.current_user["role"] == "coordenador":
            return """SELECT o.*, u.name creator FROM occurrences o
                      JOIN users u ON u.id=o.created_by ORDER BY o.id DESC"""
        return """SELECT o.*, u.name creator FROM occurrences o
                  JOIN users u ON u.id=o.created_by
                  WHERE o.created_by=? ORDER BY o.id DESC"""

    def make_occurrence_tree(self, parent, limit=None, search=None, category=None):
        cols = ("id", "title", "category", "location", "status", "creator")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=8)
        headings = {"id": "ID", "title": "Título", "category": "Categoria",
                    "location": "Local", "status": "Status", "creator": "Responsável"}
        widths = {"id": 45, "title": 210, "category": 135, "location": 190, "status": 90, "creator": 150}
        for col in cols:
            tree.heading(col, text=headings[col])
            tree.column(col, width=widths[col], anchor="w")
        query = self.visible_occurrences_query()
        params = ()
        if self.current_user["role"] != "coordenador":
            params = (self.current_user["id"],)
        rows = self.db.conn.execute(query, params).fetchall()
        for row in rows:
            if search and search.lower() not in (row["title"] + " " + row["location"] + " " + row["description"]).lower():
                continue
            if category and category != "Todas" and row["category"] != category:
                continue
            tree.insert("", "end", values=(row["id"], row["title"], row["category"],
                                           row["location"], row["status"], row["creator"]))
            if limit and len(tree.get_children()) >= limit:
                break
        tree.pack(fill="both", expand=True)
        return tree

    def show_occurrences(self):
        body = self.shell("Ocorrências ambientais", "Pesquise, filtre e selecione um registro para visualizar ou editar.")
        filters = tk.Frame(body, bg="#f3f6f3")
        filters.pack(fill="x", pady=(0, 10))
        search_var = tk.StringVar()
        category_var = tk.StringVar(value="Todas")
        tk.Label(filters, text="Buscar:", bg="#f3f6f3").pack(side="left")
        search_entry = ttk.Entry(filters, textvariable=search_var, width=28)
        search_entry.pack(side="left", padx=6)
        ttk.Label(filters, text="Categoria:").pack(side="left", padx=(12, 3))
        ttk.Combobox(filters, textvariable=category_var, state="readonly",
                     values=["Todas", "Desmatamento", "Descarte irregular de lixo", "Queimada", "Outra"],
                     width=27).pack(side="left")
        holder = tk.Frame(body, bg="#f3f6f3")
        holder.pack(fill="both", expand=True)

        def refresh():
            for child in holder.winfo_children():
                child.destroy()
            tree = self.make_occurrence_tree(holder, search=search_var.get(), category=category_var.get())
            self.occurrence_tree = tree

        ttk.Button(filters, text="Filtrar", command=refresh).pack(side="left", padx=8)
        refresh()
        buttons = tk.Frame(body, bg="#f3f6f3")
        buttons.pack(anchor="w", pady=12)

        def selected_id():
            sel = self.occurrence_tree.selection()
            if not sel:
                messagebox.showwarning("Seleção", "Selecione uma ocorrência.")
                return None
            return int(self.occurrence_tree.item(sel[0], "values")[0])

        ttk.Button(buttons, text="Nova ocorrência", command=self.show_occurrence_form).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Visualizar / editar", command=lambda: self.edit_occurrence(selected_id())).pack(side="left", padx=8)
        ttk.Button(buttons, text="Excluir", command=lambda: self.delete_occurrence(selected_id())).pack(side="left", padx=8)
        ttk.Button(buttons, text="Voltar ao painel", command=self.show_dashboard).pack(side="left", padx=8)

    def show_occurrence_form(self, occurrence_id=None):
        existing = None
        if occurrence_id:
            existing = self.db.conn.execute("SELECT * FROM occurrences WHERE id=?", (occurrence_id,)).fetchone()
            if not existing:
                messagebox.showerror("Erro", "Ocorrência não encontrada.")
                return
            if self.current_user["role"] != "coordenador" and existing["created_by"] != self.current_user["id"]:
                messagebox.showerror("Permissão", "Você não pode editar este registro.")
                return

        body = self.shell("Editar ocorrência" if existing else "Nova ocorrência",
                          "Preencha os dados da ocorrência ambiental.")
        fields = {}
        form = tk.Frame(body, bg="#f3f6f3")
        form.pack(fill="x")
        labels = [
            ("Título", "title"), ("Localização", "location"),
            ("Data (DD/MM/AAAA)", "occurrence_date")
        ]
        for label, key in labels:
            tk.Label(form, text=label, bg="#f3f6f3").pack(anchor="w")
            ent = ttk.Entry(form, width=70)
            ent.pack(anchor="w", pady=(3, 10), ipady=4)
            fields[key] = ent
        tk.Label(form, text="Categoria", bg="#f3f6f3").pack(anchor="w")
        category = ttk.Combobox(form, state="readonly",
                                values=["Desmatamento", "Descarte irregular de lixo", "Queimada", "Outra"],
                                width=45)
        category.pack(anchor="w", pady=(3, 10))
        fields["category"] = category
        tk.Label(form, text="Descrição", bg="#f3f6f3").pack(anchor="w")
        description = tk.Text(form, width=78, height=5, font=("Arial", 10))
        description.pack(anchor="w", pady=(3, 10))
        fields["description"] = description
        tk.Label(form, text="Status", bg="#f3f6f3").pack(anchor="w")
        status = ttk.Combobox(form, state="readonly", values=["Aberta", "Em análise", "Resolvida"], width=25)
        status.pack(anchor="w", pady=(3, 10))
        fields["status"] = status

        if existing:
            for key in ("title", "location", "occurrence_date"):
                fields[key].insert(0, existing[key])
            category.set(existing["category"])
            description.insert("1.0", existing["description"])
            status.set(existing["status"])
        else:
            fields["occurrence_date"].insert(0, datetime.now().strftime("%d/%m/%Y"))
            category.set("Desmatamento")
            status.set("Aberta")

        def save():
            target_occurrence_id = occurrence_id
            title = fields["title"].get().strip()
            location = fields["location"].get().strip()
            date = fields["occurrence_date"].get().strip()
            cat = category.get()
            desc = description.get("1.0", "end").strip()
            stat = status.get()
            if not all([title, location, date, cat, desc, stat]):
                messagebox.showwarning("Campos obrigatórios", "Preencha todos os campos.")
                return
            try:
                datetime.strptime(date, "%d/%m/%Y")
            except ValueError:
                messagebox.showwarning("Data inválida", "Use o formato DD/MM/AAAA.")
                return
            if existing:
                self.db.conn.execute(
                    """UPDATE occurrences SET title=?,category=?,description=?,location=?,
                       occurrence_date=?,status=? WHERE id=?""",
                    (title, cat, desc, location, date, stat, occurrence_id)
                )
                self.db.conn.commit()
                self.db.log(self.current_user["id"], "EDITOU_OCORRENCIA", f"ID {occurrence_id}")
            else:
                cur = self.db.conn.execute(
                    """INSERT INTO occurrences(title,category,description,location,occurrence_date,
                       status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                    (title, cat, desc, location, date, stat, self.current_user["id"], now())
                )
                self.db.conn.commit()
                self.db.log(self.current_user["id"], "CADASTROU_OCORRENCIA", f"ID {cur.lastrowid}")
                target_occurrence_id = cur.lastrowid
            messagebox.showinfo("Sucesso", "Ocorrência salva.")
            self.show_evidence_prompt(target_occurrence_id)

        ttk.Button(body, text="Salvar ocorrência", command=save, style="Accent.TButton").pack(anchor="w", pady=5)
        ttk.Button(body, text="Voltar", command=self.show_occurrences).pack(anchor="w")

    def show_evidence_prompt(self, occurrence_id):
        if messagebox.askyesno("Evidências", "Deseja anexar uma imagem JPG ou PNG a esta ocorrência?"):
            self.add_evidence(occurrence_id)
        else:
            self.show_occurrences()

    def edit_occurrence(self, occurrence_id):
        if occurrence_id is not None:
            self.show_occurrence_form(occurrence_id)

    def delete_occurrence(self, occurrence_id):
        if occurrence_id is None:
            return
        row = self.db.conn.execute("SELECT * FROM occurrences WHERE id=?", (occurrence_id,)).fetchone()
        if not row:
            return
        if self.current_user["role"] != "coordenador" and row["created_by"] != self.current_user["id"]:
            messagebox.showerror("Permissão", "Você não pode excluir este registro.")
            return
        if messagebox.askyesno("Confirmar exclusão", f"Excluir a ocorrência #{occurrence_id}?"):
            evidence_rows = self.db.conn.execute("SELECT stored_name FROM evidences WHERE occurrence_id=?", (occurrence_id,)).fetchall()
            for item in evidence_rows:
                try:
                    (EVIDENCE_DIR / item["stored_name"]).unlink(missing_ok=True)
                except OSError:
                    pass
            self.db.conn.execute("DELETE FROM occurrences WHERE id=?", (occurrence_id,))
            self.db.conn.commit()
            self.db.log(self.current_user["id"], "EXCLUIU_OCORRENCIA", f"ID {occurrence_id}")
            messagebox.showinfo("Sucesso", "Ocorrência excluída.")
            self.show_occurrences()

    def get_fernet(self, create=False):
        if Fernet is None:
            return None
        if not KEY_PATH.exists() and create:
            KEY_PATH.write_bytes(Fernet.generate_key())
        if not KEY_PATH.exists():
            return None
        try:
            return Fernet(KEY_PATH.read_bytes())
        except Exception:
            return None

    def add_evidence(self, occurrence_id):
        path = filedialog.askopenfilename(
            title="Selecione uma evidência",
            filetypes=[("Imagens JPG/PNG", "*.jpg *.jpeg *.png")]
        )
        if not path:
            self.show_occurrences()
            return
        source = Path(path)
        if source.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            messagebox.showerror("Formato inválido", "Selecione um arquivo JPG ou PNG.")
            return
        try:
            raw = source.read_bytes()
            if Image is not None:
                with Image.open(source) as img:
                    img.verify()
            else:
                # Verificação básica de assinatura quando Pillow não está instalado.
                valid_jpeg = raw.startswith(b"\\xff\\xd8\\xff")
                valid_png = raw.startswith(b"\\x89PNG\\r\\n\\x1a\\n")
                if not (valid_jpeg or valid_png):
                    raise ValueError("O arquivo não parece ser uma imagem JPG/PNG válida.")
        except Exception as exc:
            messagebox.showerror("Imagem inválida", f"Não foi possível validar a imagem:\n{exc}")
            return

        fernet = self.get_fernet(create=True)
        encrypted = 0
        stored_bytes = raw
        extension = source.suffix.lower()
        if fernet:
            stored_bytes = fernet.encrypt(raw)
            encrypted = 1
            extension += ".enc"
        stored_name = f"ocorrencia_{occurrence_id}_{secrets.token_hex(6)}{extension}"
        target = EVIDENCE_DIR / stored_name
        target.write_bytes(stored_bytes)
        digest = sha256_bytes(raw)
        self.db.conn.execute(
            """INSERT INTO evidences(occurrence_id,stored_name,original_name,sha256,encrypted,added_at)
               VALUES(?,?,?,?,?,?)""",
            (occurrence_id, stored_name, source.name, digest, encrypted, now())
        )
        self.db.conn.commit()
        self.db.log(self.current_user["id"], "ANEXOU_EVIDENCIA",
                    f"Ocorrência {occurrence_id}; arquivo {source.name}")
        if Fernet is None:
            messagebox.showwarning(
                "Evidência salva sem criptografia",
                "A imagem foi armazenada e teve seu hash calculado, mas cryptography não está instalado.\n"
                "Instale com: python -m pip install cryptography"
            )
        else:
            messagebox.showinfo("Sucesso", "Evidência validada, armazenada e criptografada.")
        self.show_occurrences()

    def verify_evidence(self):
        if self.current_user["role"] != "coordenador":
            messagebox.showerror("Permissão", "Somente o coordenador pode verificar evidências.")
            return
        rows = self.db.conn.execute("SELECT * FROM evidences ORDER BY id DESC").fetchall()
        if not rows:
            messagebox.showinfo("Integridade", "Ainda não existem evidências cadastradas.")
            return
        fernet = self.get_fernet()
        if any(r["encrypted"] for r in rows) and fernet is None:
            messagebox.showwarning(
                "Chave de criptografia ausente",
                "Não foi possível localizar a chave Fernet.\n"
                f"Verifique o arquivo: {KEY_PATH}\n"
                "Não gere outra chave por cima da original: isso impediria a leitura das evidências."
            )
            self.db.log(self.current_user["id"], "ALERTA_CHAVE_AUSENTE", "Verificação interrompida")
            return

        window = tk.Toplevel(self.root)
        window.title("Verificar evidências")
        window.geometry("900x520")
        window.minsize(820, 460)
        window.transient(self.root)
        window.configure(bg="#f3f6f3")
        tk.Label(window, text="Resultado da verificação de integridade", bg="#f3f6f3",
                 fg="#174b32", font=("Arial", 16, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(window, text="Selecione uma evidência e clique em 'Visualizar evidência' para abrir a imagem.",
                 bg="#f3f6f3").pack(anchor="w", padx=18, pady=(0, 12))
        table_frame = tk.Frame(window, bg="#f3f6f3")
        table_frame.pack(fill="both", expand=True, padx=18, pady=4)
        columns = ("evidence", "occurrence", "file", "status")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=11)
        for col, title, width in [("evidence", "Evidência", 80), ("occurrence", "Ocorrência", 90),
                                  ("file", "Arquivo", 300), ("status", "Integridade", 170)]:
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        evidence_by_id = {}
        for row in rows:
            file_path = EVIDENCE_DIR / row["stored_name"]
            try:
                stored = file_path.read_bytes()
                original = fernet.decrypt(stored) if row["encrypted"] else stored
                actual = sha256_bytes(original)
                status = "ÍNTEGRA" if hmac.compare_digest(actual, row["sha256"]) else "ALTERADA"
            except Exception:
                status = "ERRO / CHAVE INVÁLIDA"
            evidence_by_id[str(row["id"])] = (row, status)
            tree.insert("", "end", iid=str(row["id"]), values=(row["id"], row["occurrence_id"],
                        row["original_name"], status))

        def view_selected():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("Seleção necessária", "Selecione uma evidência na lista.", parent=window)
                return
            row, status = evidence_by_id[selected[0]]
            if status != "ÍNTEGRA":
                if not messagebox.askyesno("Atenção", f"Esta evidência consta como {status}. Deseja tentar visualizá-la mesmo assim?", parent=window):
                    return
            if Image is None:
                messagebox.showerror("Biblioteca necessária", "Para visualizar imagens dentro do EcoAlerta, instale Pillow com:\npython -m pip install Pillow", parent=window)
                return
            try:
                stored = (EVIDENCE_DIR / row["stored_name"]).read_bytes()
                original = fernet.decrypt(stored) if row["encrypted"] else stored
                import io
                from PIL import ImageTk
                image = Image.open(io.BytesIO(original))
                image.thumbnail((850, 650))
                photo = ImageTk.PhotoImage(image.copy())
                preview = tk.Toplevel(window)
                preview.title(f"Evidência: {row['original_name']}")
                preview.transient(window)
                tk.Label(preview, text=f"{row['original_name']} — Integridade: {status}",
                         font=("Arial", 10, "bold")).pack(padx=10, pady=8)
                image_label = tk.Label(preview, image=photo)
                image_label.image = photo
                image_label.pack(padx=10, pady=10)
                self.db.log(self.current_user["id"], "VISUALIZOU_EVIDENCIA", f"Evidência {row['id']}")
            except Exception as exc:
                messagebox.showerror("Visualização", f"Não foi possível abrir a evidência:\n{exc}", parent=window)

        buttons = tk.Frame(window, bg="#f3f6f3")
        buttons.pack(fill="x", padx=18, pady=14)
        ttk.Button(buttons, text="ABRIR / VISUALIZAR IMAGEM", command=view_selected,
                   style="Accent.TButton").pack(side="left")
        tree.bind("<Double-1>", lambda event: view_selected())
        ttk.Button(buttons, text="Fechar", command=window.destroy).pack(side="right")
        self.db.log(self.current_user["id"], "VERIFICOU_EVIDENCIAS", f"{len(rows)} evidência(s)")

    def backup_screen(self):
        if self.current_user["role"] != "coordenador":
            messagebox.showerror("Permissão", "Somente o coordenador pode importar/exportar.")
            return
        body = self.shell("Importação e exportação", "Compartilhe um pacote JSON com os dados e as evidências entre os integrantes.")
        tk.Label(body, text="Exportar: cria um arquivo ZIP com os dados JSON e as evidências.",
                 bg="#f3f6f3").pack(anchor="w", pady=(0, 10))

        def export_data():
            target = filedialog.asksaveasfilename(
                defaultextension=".zip", filetypes=[("Pacote ZIP", "*.zip")],
                initialfile="ecoalerta_backup.zip"
            )
            if not target:
                return
            self.db.conn.commit()
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(JSON_PATH, "ecoalerta_dados.json")
                if EVIDENCE_DIR.exists():
                    for file in EVIDENCE_DIR.iterdir():
                        if file.is_file():
                            zf.write(file, f"evidencias/{file.name}")
                if KEY_PATH.exists():
                    zf.write(KEY_PATH, "chave_fernet.key")
            self.db.log(self.current_user["id"], "EXPORTOU_DADOS", target)
            messagebox.showinfo("Exportação", "Pacote exportado com sucesso.\nGuarde-o em local seguro.")

        ttk.Button(body, text="Exportar pacote ZIP", command=export_data,
                   style="Accent.TButton").pack(anchor="w", pady=(0, 22))
        tk.Label(body, text="Importar: substitui os dados locais pelo conteúdo do pacote selecionado.",
                 bg="#f3f6f3", fg="#9a4d22").pack(anchor="w", pady=(0, 10))

        def import_data():
            target = filedialog.askopenfilename(filetypes=[("Pacote ZIP", "*.zip")])
            if not target:
                return
            if not messagebox.askyesno(
                "Confirmar importação",
                "A importação substituirá os dados JSON e as evidências locais. Faça um backup antes.\nContinuar?"
            ):
                return
            temp = DATA_DIR / "import_temp"
            shutil.rmtree(temp, ignore_errors=True)
            temp.mkdir()
            try:
                with zipfile.ZipFile(target, "r") as zf:
                    names = zf.namelist()
                    if any(Path(n).is_absolute() or ".." in Path(n).parts for n in names):
                        raise ValueError("O pacote contém caminhos inválidos.")
                    if "ecoalerta_dados.json" not in names:
                        raise ValueError("Pacote sem ecoalerta_dados.json.")
                    zf.extractall(temp)
                self.db.close()
                shutil.copy2(temp / "ecoalerta_dados.json", JSON_PATH)
                shutil.rmtree(EVIDENCE_DIR, ignore_errors=True)
                EVIDENCE_DIR.mkdir(exist_ok=True)
                imported_evidence = temp / "evidencias"
                if imported_evidence.exists():
                    for f in imported_evidence.iterdir():
                        if f.is_file():
                            shutil.copy2(f, EVIDENCE_DIR / f.name)
                imported_key = temp / "chave_fernet.key"
                if imported_key.exists():
                    shutil.copy2(imported_key, KEY_PATH)
                self.db = Database()
                imported_user = self.db.conn.execute(
                    "SELECT * FROM users WHERE email=?", (self.current_user["email"],)
                ).fetchone()
                if imported_user is None:
                    imported_user = self.db.conn.execute(
                        "SELECT * FROM users WHERE role='coordenador' ORDER BY id LIMIT 1"
                    ).fetchone()
                if imported_user is None:
                    raise ValueError("O pacote não contém uma conta de coordenador.")
                self.current_user = dict(imported_user)
                self.db.log(self.current_user["id"], "IMPORTOU_DADOS", Path(target).name)
                messagebox.showinfo("Importação", "Pacote importado com sucesso.")
                self.show_dashboard()
            except Exception as exc:
                messagebox.showerror("Falha na importação", f"Não foi possível importar:\n{exc}")
                if self.db.conn is None:
                    self.db = Database()
            finally:
                shutil.rmtree(temp, ignore_errors=True)

        ttk.Button(body, text="Importar pacote ZIP", command=import_data).pack(anchor="w")

        def restore_demo():
            if not messagebox.askyesno(
                "Restaurar demonstração",
                "Isso apagará os cadastros e alterações feitos neste computador e restaurará os dados demonstrativos originais. Deseja continuar?"
            ):
                return
            try:
                self.db.reset_demo_data()
                self.current_user = dict(self.db.conn.execute(
                    "SELECT * FROM users WHERE email=?", ("coordenador@ecoalerta.local",)
                ).fetchone())
                self.db.log(self.current_user["id"], "RESTAURou_DEMONSTRACAO", "Dados demonstrativos restaurados")
                messagebox.showinfo("EcoAlerta", "Dados demonstrativos restaurados com sucesso.")
                self.show_dashboard()
            except Exception as exc:
                messagebox.showerror("Restauração", f"Não foi possível restaurar os dados:\n{exc}")

        ttk.Button(body, text="Restaurar dados demonstrativos", command=restore_demo).pack(anchor="w", pady=(12, 0))
        ttk.Button(body, text="Voltar ao painel", command=self.show_dashboard).pack(anchor="w", pady=15)

    def show_audit(self):
        body = self.shell("Histórico de atividades", "Registro de acessos e ações realizadas no sistema.")
        if self.current_user["role"] == "coordenador":
            rows = self.db.conn.execute(
                """SELECT a.*, u.name FROM audit a LEFT JOIN users u ON u.id=a.user_id
                   ORDER BY a.id DESC LIMIT 200"""
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """SELECT a.*, u.name FROM audit a LEFT JOIN users u ON u.id=a.user_id
                   WHERE a.user_id=? ORDER BY a.id DESC LIMIT 100""",
                (self.current_user["id"],)
            ).fetchall()
        tree = ttk.Treeview(body, columns=("date", "user", "action", "details"),
                            show="headings", height=15)
        for col, label, width in [
            ("date", "Data/hora", 150), ("user", "Usuário", 180),
            ("action", "Ação", 190), ("details", "Detalhes", 400)
        ]:
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="w")
        for row in rows:
            tree.insert("", "end", values=(row["created_at"], row["name"] or "—",
                                           row["action"], row["details"] or ""))
        tree.pack(fill="both", expand=True)
        ttk.Button(body, text="Voltar ao painel", command=self.show_dashboard).pack(anchor="w", pady=12)

    def logout(self):
        if self.current_user:
            self.db.log(self.current_user["id"], "LOGOUT", "Saída do sistema")
        self.show_login()

    def on_close(self):
        try:
            if self.current_user:
                self.db.log(self.current_user["id"], "ENCERROU_APLICACAO", "Janela fechada")
            self.db.close()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = EcoAlertaApp(root)
    root.mainloop()
