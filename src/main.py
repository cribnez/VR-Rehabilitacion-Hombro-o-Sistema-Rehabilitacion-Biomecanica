import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel, ttk
import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageTk
import threading
import datetime
import sqlite3
import time
import os
from collections import defaultdict
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import white, black, red, grey
from io import BytesIO


# ======================= Base de datos =======================
def init_db():
    conn = sqlite3.connect("pacientes.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pasajeros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        edad INTEGER,
        sexo TEXT,
        diagnostico TEXT,
        fecha TEXT
    )
    """)
    # tabla correcta (compatibilidad con tus datos previos)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pacientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        edad INTEGER,
        sexo TEXT,
        diagnostico TEXT,
        fecha TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()


# ======================= Utilidades =======================
def angle_from_vertical_deg(p_shoulder_xy, p_elbow_xy) -> float:
    """
    Ángulo del brazo respecto a la vertical hacia abajo (eje +Y de imagen):
    - Brazo colgando: 0°
    - Horizontal: ~90°
    - Arriba: ~180°
    """
    sx, sy = p_shoulder_xy
    ex, ey = p_elbow_xy
    v = np.array([ex - sx, ey - sy], dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-9:
        return 0.0
    v /= n
    down = np.array([0.0, 1.0], dtype=float)  # +Y apunta hacia abajo en imagen
    cosang = float(np.clip(np.dot(v, down), -1.0, 1.0))
    ang = float(np.degrees(np.arccos(cosang)))
    return float(np.clip(ang, 0.0, 180.0))


def near_targets(angle: float, targets=(90.0, 180.0), tol=10.0) -> bool:
    """True si angle está dentro de ±tol de CUALQUIERA de los objetivos."""
    for t in targets:
        if (t - tol) <= angle <= (t + tol):
            return True
    return False


# ================== CONFIG PDF (EDITABLE) ==================
OFFSET_X = 0
OFFSET_Y = 0
SHOW_GUIDES = False
GRID_STEP = 40

COORDS = {
    # Cabecera
    "paciente":  (200, 730),
    "edad":      (200, 710),
    "fecha":     (470, 730),

    # Datos
    "ejercicio": (200, 690),
    "peso":      (200, 670),

    # Referencias
    "ref_flex":  (200, 640),
    "ref_abd":   (200, 620),

    # Resultados medidos
    "res_flex":  (400, 640),
    "res_abd":   (400, 620),

    "reps":      (200, 570),
    "series":    (200, 550),
}

ERASE_BOXES = [
    (195, 724, 250, 18),
    (195, 704, 100, 18),
    (465, 724, 180, 18),

    (195, 684, 320, 18),
    (195, 664, 120, 18),

    (195, 636, 140, 16),
    (195, 616, 140, 16),

    (395, 636, 120, 16),
    (395, 616, 120, 16),

    (195, 566, 120, 16),
    (195, 546, 120, 16),
]


# ======================= App =======================
class ProyectoUniApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Analisis postural")
        self.geometry("600x450")
        self.configure(bg="#121212")
        self.resizable(False, False)

        # ---- NUEVO: modo de evaluación por ejercicio ----
        # Flexión: hombro en plano sagital; Abducción: plano frontal.
        self.EXERCISE_MODE = {
            "Shoulder flexion with stick": "Flexión",
            "Half squat with shoulder press": "Flexión",
            "Press Arnold": "Flexión",
            "Dumbbell rear delt fly": "Abducción",
            "Standing wall pull-ups": "Abducción",
            # Los que falten quedarán por defecto en Flexión
        }
        self.modo = "Flexión"
        # -------------------------------------------------

        # Estado
        self.paciente_var = tk.StringVar()
        self.edad_var = tk.StringVar()
        self.sexo_var = tk.StringVar()
        self.diagnostico_var = tk.StringVar()

        self.ultimo_reporte = {
            "paciente": None,
            "fecha": "",
            "ejercicio": None,
            "video_referencia": None,
            "comparacion": {},          # ángulos medidos en tiempo real
            "repeticiones": "",
            "series": "",
            "peso": ""
        }

        # metas fijas: 90° y 180° (solo display)
        self.meta_texto = "90° / 180°"

        # UI base
        self.color_fondo = "#121212"
        self.color_btn = "#1F2937"
        self.color_btn_hover = "#3B82F6"
        self.color_texto = "white"
        self.color_texto_btn = "white"

        self.crear_ui_principal()

    # ---------------- Menú principal ----------------
    def crear_ui_principal(self):
        tk.Label(self, text="Bienvenido", font=("Segoe UI", 20, "bold"),
                 fg=self.color_texto, bg=self.color_fondo).pack(pady=(40, 30))

        HoverButton(self, text="Registrar Paciente", font=("Segoe UI", 14, "bold"),
                    bg=self.color_btn, fg=self.color_texto_btn, activebackground=self.color_btn_hover,
                    relief="flat", cursor="hand2", command=self.abrir_registro_paciente)\
            .pack(fill="x", padx=80, pady=7)

        HoverButton(self, text="Ver Historial", font=("Segoe UI", 14, "bold"),
                    bg=self.color_btn, fg=self.color_texto_btn, activebackground=self.color_btn_hover,
                    relief="flat", cursor="hand2", command=self.abrir_historial)\
            .pack(fill="x", padx=80, pady=7)

        HoverButton(self, text="Iniciar Comparación", font=("Segoe UI", 14, "bold"),
                    bg=self.color_btn, fg=self.color_texto_btn, activebackground=self.color_btn_hover,
                    relief="flat", cursor="hand2", command=self.ventana_ejercicios)\
            .pack(fill="x", padx=80, pady=7)

        HoverButton(self, text="Exportar Reporte PDF", font=("Segoe UI", 14, "bold"),
                    bg=self.color_btn, fg=self.color_texto_btn, activebackground=self.color_btn_hover,
                    relief="flat", cursor="hand2", command=self.exportar_pdf)\
            .pack(fill="x", padx=80, pady=7)

        HoverButton(self, text="Salir", font=("Segoe UI", 14, "bold"),
                    bg="#B91C1C", fg="white", activebackground="#EF4444",
                    relief="flat", cursor="hand2", command=self.destroy)\
            .pack(fill="x", padx=80, pady=20)

    # ---------------- Registro ----------------
    def abrir_registro_paciente(self):
        w = Toplevel(self)
        w.title("Registrar Paciente")
        w.geometry("700x500")
        w.configure(bg=self.color_fondo)
        w.resizable(False, False)

        tk.Label(w, text="Registrar Paciente", font=("Segoe UI", 18, "bold"),
                 fg=self.color_texto, bg=self.color_fondo).pack(pady=20)

        self.nombre_entry = self.crear_label_entry(w, "Nombre:", self.paciente_var)
        self.edad_entry = self.crear_label_entry(w, "Edad:", self.edad_var)

        sexo_frame = tk.Frame(w, bg=self.color_fondo)
        sexo_frame.pack(pady=10, fill="x", padx=30)
        tk.Label(sexo_frame, text="Sexo:", fg=self.color_texto, bg=self.color_fondo,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        for texto, valor in [("Masculino","Masculino"),("Femenino","Femenino"),("Otro","Otro")]:
            tk.Radiobutton(sexo_frame, text=texto, variable=self.sexo_var, value=valor,
                           font=("Segoe UI", 11), bg=self.color_fondo, fg=self.color_texto,
                           selectcolor=self.color_btn_hover).pack(side="left", padx=10)

        self.diagnostico_entry = self.crear_label_entry(w, "Diagnóstico:", self.diagnostico_var)

        HoverButton(w, text="Guardar Paciente", font=("Segoe UI", 14, "bold"),
                    bg="#10B981", fg="white", activebackground="#34D399",
                    relief="flat", cursor="hand2", command=self.guardar_paciente).pack(pady=20, ipadx=10)

    def crear_label_entry(self, contenedor, texto, variable):
        f = tk.Frame(contenedor, bg=self.color_fondo)
        f.pack(pady=5, padx=30, fill="x")
        tk.Label(f, text=texto, font=("Segoe UI", 12, "bold"),
                 fg=self.color_texto, bg=self.color_fondo).pack(anchor="w")
        ent = tk.Entry(f, textvariable=variable, font=("Segoe UI", 12))
        ent.pack(fill="x", pady=3)
        return ent

    def guardar_paciente(self):
        nombre = self.paciente_var.get().strip()
        edad = self.edad_var.get().strip()
        sexo = self.sexo_var.get()
        diagnostico = self.diagnostico_var.get().strip()
        fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not nombre:
            messagebox.showwarning("Datos incompletos", "Ingresa el nombre del paciente.")
            return
        if not edad.isdigit():
            messagebox.showwarning("Datos incompletos", "Edad inválida.")
            return
        if sexo not in ["Masculino","Femenino","Otro"]:
            messagebox.showwarning("Datos incompletos", "Selecciona un sexo válido.")
            return
        if not diagnostico:
            messagebox.showwarning("Datos incompletos", "Ingresa un diagnóstico.")
            return

        try:
            conn = sqlite3.connect("pacientes.db")
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO pacientes (nombre, edad, sexo, diagnostico, fecha)
                VALUES (?, ?, ?, ?, ?)
            """, (nombre, int(edad), sexo, diagnostico, fecha))
            conn.commit()
            conn.close()
            messagebox.showinfo("Éxito", "Paciente guardado.")
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo guardar:\n{e}")

    # ---------------- Historial ----------------
    def abrir_historial(self):
        w = Toplevel(self)
        w.title("Historial de Pacientes")
        w.geometry("700x450")
        w.configure(bg=self.color_fondo)
        w.resizable(False, False)

        lst = tk.Listbox(w, font=("Segoe UI", 12), bg="#1E293B", fg="white")
        lst.pack(fill="both", expand=True, padx=10, pady=10)

        try:
            conn = sqlite3.connect("pacientes.db")
            cur = conn.cursor()
            cur.execute("SELECT nombre, edad, sexo, diagnostico, fecha FROM pacientes ORDER BY fecha DESC")
            for p in cur.fetchall():
                lst.insert(tk.END, f"{p[0]} | Edad: {p[1]} | Sexo: {p[2]} | Dx: {p[3]} | Fecha: {p[4]}")
            conn.close()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar:\n{e}")

    # ---------------- Selección Ejercicio ----------------
    def ventana_ejercicios(self):
        self.ejercicios_lista = [
            "Shoulder flexion with stick",
            "Figure 8 arms lying down",
            "Seated two arm dumbbell triceps extension",
            "Dumbbell rear delt fly",
            "Half squat with shoulder press",
            "Press Arnold",
            "Standing wall pull-ups",
            "Openings and shoulder rotations with bottles"
        ]

        self.vent_ejercicios = Toplevel(self)
        self.vent_ejercicios.title("Seleccionar Ejercicio")
        self.vent_ejercicios.geometry("520x300")
        self.vent_ejercicios.configure(bg=self.color_fondo)
        self.vent_ejercicios.resizable(False, False)

        tk.Label(self.vent_ejercicios, text="Selecciona el ejercicio",
                 font=("Segoe UI", 16, "bold"), fg=self.color_texto, bg=self.color_fondo).pack(pady=20)

        self.combo_ejercicios = ttk.Combobox(self.vent_ejercicios, values=self.ejercicios_lista,
                                             font=("Segoe UI", 14), state="readonly")
        self.combo_ejercicios.pack(pady=15, padx=50, fill="x")
        self.combo_ejercicios.current(0)

        HoverButton(self.vent_ejercicios, text="Siguiente", font=("Segoe UI", 14, "bold"),
                    bg=self.color_btn, fg=self.color_texto_btn, activebackground=self.color_btn_hover,
                    relief="flat", cursor="hand2", command=self.ventana_parametros)\
            .pack(pady=30, ipadx=10)

    # ---------------- Parámetros (solo PDF y carga de ref) ----------------
    def ventana_parametros(self):
        self.ejercicio_seleccionado = self.combo_ejercicios.get()
        # ---- NUEVO: fija modo según el ejercicio seleccionado ----
        self.modo = self.EXERCISE_MODE.get(self.ejercicio_seleccionado, "Flexión")
        # ----------------------------------------------------------
        self.vent_ejercicios.destroy()

        w = Toplevel(self)
        w.title("Parámetros y referencia")
        w.geometry("800x700")
        w.configure(bg=self.color_fondo)
        w.resizable(False, False)

        tk.Label(w, text=f"Parámetros para:\n{self.ejercicio_seleccionado}",
                 font=("Segoe UI", 16, "bold"), fg=self.color_texto, bg=self.color_fondo).pack(pady=20)

        # Campos PDF
        self.repeticiones_var = tk.StringVar()
        self.series_var = tk.StringVar()
        self.peso_var = tk.StringVar()

        self.crear_label_entry(w, "Repeticiones:", self.repeticiones_var)
        self.crear_label_entry(w, "Series:", self.series_var)
        self.crear_label_entry(w, "Peso o resistencia:", self.peso_var)

        # Ayuda: metas fijas
        tk.Label(w, text="Metas de evaluación para ambos ángulos: 90° y 180° (±10°).",
                 font=("Segoe UI", 11), fg="#A3E635", bg=self.color_fondo).pack(pady=10)

        tk.Label(w, text="Carga un video o imagen de referencia:",
                 font=("Segoe UI", 12, "bold"), fg=self.color_texto, bg=self.color_fondo).pack(pady=(20,5))

        self.ruta_archivo_ref = ""
        HoverButton(w, text="Cargar Archivo", font=("Segoe UI", 14, "bold"),
                    bg=self.color_btn, fg=self.color_texto_btn, activebackground=self.color_btn_hover,
                    relief="flat", cursor="hand2", command=self.cargar_archivo_referencia)\
            .pack(pady=10, ipadx=10)

        self.btn_iniciar = HoverButton(w, text="Iniciar Comparación", font=("Segoe UI", 14, "bold"),
                                       bg="#10B981", fg="white", activebackground="#34D399",
                                       relief="flat", cursor="hand2", state="disabled",
                                       command=lambda: (w.destroy(), self.abrir_ventana_comparacion()))
        self.btn_iniciar.pack(pady=10, ipadx=10)

    def cargar_archivo_referencia(self):
        path = filedialog.askopenfilename(
            title="Selecciona video o imagen de referencia",
            filetypes=[("Video/Imagen", "*.mp4 *.avi *.mov *.jpg *.jpeg *.png")]
        )
        if path:
            self.ruta_archivo_ref = path
            self.btn_iniciar.config(state="normal")
            messagebox.showinfo("Archivo cargado", os.path.basename(path))

    # ---------------- Comparación en tiempo real ----------------
    def abrir_ventana_comparacion(self):
        self.vent_comparacion = Toplevel(self)
        self.vent_comparacion.title(f"Comparación en tiempo real - {self.ejercicio_seleccionado}")
        self.vent_comparacion.geometry("1366x768")
        self.vent_comparacion.configure(bg=self.color_fondo)
        self.vent_comparacion.resizable(False, False)

        self.frame_videos = tk.Frame(self.vent_comparacion, bg=self.color_fondo)
        self.frame_videos.pack(pady=15)

        self.label_video_ref = tk.Label(self.frame_videos, bg=self.color_fondo)
        self.label_video_ref.grid(row=0, column=0, padx=10)

        self.label_video_cam = tk.Label(self.frame_videos, bg=self.color_fondo)
        self.label_video_cam.grid(row=0, column=1, padx=10)

        self.frame_info = tk.Frame(self.vent_comparacion, bg=self.color_fondo)
        self.frame_info.pack(pady=10, fill="x")

        self.text_info = tk.Text(self.frame_info, width=60, height=12, font=("Consolas", 14),
                                 bg="#1E293B", fg="white", state="disabled")
        self.text_info.pack(side="left", padx=20)

        self.btn_grabar = HoverButton(self.frame_info, text="Grabar Video", font=("Segoe UI", 14, "bold"),
                                      bg="#EF4444", fg="white", activebackground="#F87171",
                                      relief="flat", cursor="hand2", command=self.toggle_grabacion)
        self.btn_grabar.pack(side="left", padx=40)

        self.btn_terminar = HoverButton(self.frame_info, text="Terminar Comparación", font=("Segoe UI", 14, "bold"),
                                        bg="#6B7280", fg="white", activebackground="#9CA3AF",
                                        relief="flat", cursor="hand2", command=self.cerrar_ventana_comparacion)
        self.btn_terminar.pack(side="left", padx=20)

        # Video
        self.cap_cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.cap_ref = None
        self.imagen_ref_static = None

        if self.ruta_archivo_ref and self.ruta_archivo_ref.lower().endswith(('.mp4','.avi','.mov')):
            self.cap_ref = cv2.VideoCapture(self.ruta_archivo_ref)
        elif self.ruta_archivo_ref:
            img = cv2.imread(self.ruta_archivo_ref)
            if img is None:
                messagebox.showerror("Error", "No se pudo abrir la imagen de referencia.")
                self.vent_comparacion.destroy()
                return
            self.imagen_ref_static = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        self.grabando = False
        self.writer = None

        # Mediapipe
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(static_image_mode=False,
                                      model_complexity=1,
                                      enable_segmentation=False,
                                      min_detection_confidence=0.5,
                                      min_tracking_confidence=0.5)
        self.buffer_angulos = defaultdict(list)  # suavizado

        self.last_update = 0
        self.hilo_video = threading.Thread(target=self.actualizar_videos, daemon=True)
        self.hilo_video.start()
        self.vent_comparacion.protocol("WM_DELETE_WINDOW", self.cerrar_ventana_comparacion)

    def toggle_grabacion(self):
        if not self.grabando:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            nombre = f"grabacion_{now}.mp4"
            w = int(self.cap_cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self.cap_cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w == 0 or h == 0:
                messagebox.showerror("Error", "Cámara sin dimensiones válidas.")
                return
            vw = cv2.VideoWriter(nombre, fourcc, 20.0, (w, h))
            if not vw.isOpened():
                fourcc = cv2.VideoWriter_fourcc(*"XVID")
                nombre = f"grabacion_{now}.avi"
                vw = cv2.VideoWriter(nombre, fourcc, 20.0, (w, h))
                if not vw.isOpened():
                    messagebox.showerror("Error", "No se pudo iniciar grabación.")
                    return
            self.writer = vw
            self.grabando = True
            self.btn_grabar.config(text="Detener Grabación", bg="#059669", activebackground="#10B981")
            messagebox.showinfo("Grabación", f"Grabando: {nombre}")
        else:
            self.grabando = False
            if self.writer:
                self.writer.release()
                self.writer = None
            self.btn_grabar.config(text="Grabar Video", bg="#EF4444", activebackground="#F87171")
            messagebox.showinfo("Grabación", "Video guardado.")

    def actualizar_videos(self):
        # Umbral para considerar movimiento lateral "válido" (reduce falsos en abducción)
        PLANE_RATIO_THRESH = 1.2  # |Δx| / (|Δz|+eps)

        while True:
            ok_cam, frame_cam = self.cap_cam.read()
            if not ok_cam:
                break

            rgb = cv2.cvtColor(frame_cam, cv2.COLOR_BGR2RGB)
            res = self.pose.process(rgb)

            ang_flex, ang_abd, abd_valida = 0.0, 0.0, False

            if res.pose_landmarks:
                lm = res.pose_landmarks.landmark
                # Lado derecho (12 hombro, 14 codo)
                shoulder = (lm[12].x, lm[12].y, lm[12].z)
                elbow    = (lm[14].x, lm[14].y, lm[14].z)

                ang_flex = angle_from_vertical_deg((shoulder[0], shoulder[1]),
                                                   (elbow[0], elbow[1]))

                # filtro de plano para Abducción
                dx = elbow[0] - shoulder[0]
                dz = elbow[2] - shoulder[2]
                ratio = abs(dx) / (abs(dz) + 1e-6)
                abd_valida = ratio >= PLANE_RATIO_THRESH
                if abd_valida:
                    ang_abd = angle_from_vertical_deg((shoulder[0], shoulder[1]),
                                                      (elbow[0], elbow[1]))
                else:
                    ang_abd = None

            # Suavizado
            self.buffer_angulos["Flexión"].append(ang_flex)
            if len(self.buffer_angulos["Flexión"]) > 5:
                self.buffer_angulos["Flexión"].pop(0)
            s_flex = float(np.mean(self.buffer_angulos["Flexión"]))

            if ang_abd is not None:
                self.buffer_angulos["Abducción"].append(ang_abd)
                if len(self.buffer_angulos["Abducción"]) > 5:
                    self.buffer_angulos["Abducción"].pop(0)
                s_abd = float(np.mean(self.buffer_angulos["Abducción"]))
            else:
                s_abd = None

            # Estados (verde si cerca de 90° O de 180°)
            estado_flex_ok = near_targets(s_flex, targets=(90.0, 180.0), tol=10.0)
            if s_abd is None:
                estado_abd = "-"
            else:
                estado_abd = "✓" if near_targets(s_abd, targets=(90.0, 180.0), tol=10.0) else "✗"

            # Guardar para PDF (si abducción inválida, guardo 0.0)
            self.ultimo_reporte.update({
                "paciente": self.paciente_var.get(),
                "fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ejercicio": self.ejercicio_seleccionado,
                "comparacion": {
                    "Flexión": round(s_flex, 1),
                    "Abducción": 0.0 if s_abd is None else round(s_abd, 1)
                }
            })

            # Dibujar
            frame_land = frame_cam.copy()
            if res.pose_landmarks:
                mp.solutions.drawing_utils.draw_landmarks(
                    frame_land, res.pose_landmarks, self.mp_pose.POSE_CONNECTIONS,
                    mp.solutions.drawing_styles.get_default_pose_landmarks_style())

            overlay = frame_land.copy()
            cv2.rectangle(overlay, (5, 5), (520, 230), (0, 0, 0), -1)
            frame_land = cv2.addWeighted(overlay, 0.5, frame_land, 0.5, 0)

            nombre = self.paciente_var.get()
            fecha_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.putText(frame_land, f"Paciente: {nombre}", (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
            cv2.putText(frame_land, f"Ejercicio: {self.ejercicio_seleccionado}", (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)
            # ---- NUEVO: mostrar modo activo ----
            cv2.putText(frame_land, f"Modo evaluado: {self.modo}", (15, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,255,200), 1)
            # ------------------------------------
            cv2.putText(frame_land, fecha_str, (15, 94), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)

            y0 = 120
            # Colores según modo: solo el ángulo del modo se pinta verde/rojo; el otro, gris informativo.
            if self.modo == "Flexión":
                col_f = (0,255,0) if estado_flex_ok else (0,0,255)
                col_a = (200,200,200)  # informativo
            else:  # Abducción
                col_a = (0,255,0) if (estado_abd == "✓") else (0,0,255)
                col_f = (200,200,200)  # informativo

            txt_f = f"Flexión: {round(s_flex,1)}° / Metas: {self.meta_texto}"
            cv2.putText(frame_land, txt_f, (15, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.65, col_f, 2)

            y0 += 28
            if s_abd is None:
                txt_a = f"Abducción: — / Metas: {self.meta_texto}"
            else:
                txt_a = f"Abducción: {round(s_abd,1)}° / Metas: {self.meta_texto}"
            cv2.putText(frame_land, txt_a, (15, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.65, col_a, 2)

            # Referencia (video/imagen)
            if self.cap_ref is not None:
                ok_ref, frame_ref = self.cap_ref.read()
                if not ok_ref:
                    self.cap_ref.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok_ref, frame_ref = self.cap_ref.read()
                frame_ref = cv2.resize(frame_ref, (560, 420))
                frame_ref = cv2.cvtColor(frame_ref, cv2.COLOR_BGR2RGB)
            else:
                frame_ref = cv2.resize(self.imagen_ref_static, (560, 420)) if self.imagen_ref_static is not None else np.zeros((420,560,3), dtype=np.uint8)

            # A Tk
            cam_disp = cv2.resize(frame_land, (560, 420))
            img_cam = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(cam_disp, cv2.COLOR_BGR2RGB)))
            img_ref = ImageTk.PhotoImage(image=Image.fromarray(frame_ref))

            self.label_video_cam.imgtk = img_cam
            self.label_video_cam.configure(image=img_cam)
            self.label_video_ref.imgtk = img_ref
            self.label_video_ref.configure(image=img_ref)

            # Panel texto
            if time.time() - self.last_update > 0.5:
                self.text_info.config(state="normal")
                self.text_info.delete("1.0", tk.END)
                self.text_info.insert(tk.END, f"Ejercicio: {self.ejercicio_seleccionado}\n")
                self.text_info.insert(tk.END, f"Modo evaluado: {self.modo}\n\n")
                self.text_info.insert(tk.END, "Ángulos en tiempo real (verde si cerca de 90° o 180°):\n")
                self.text_info.insert(tk.END, f"Flexión:   {round(s_flex,1)}°   Metas: {self.meta_texto}   [{'✓' if estado_flex_ok else '✗'}]\n")
                if s_abd is None:
                    self.text_info.insert(tk.END, f"Abducción: —         Metas: {self.meta_texto}   [-]\n")
                else:
                    self.text_info.insert(tk.END, f"Abducción: {round(s_abd,1)}°   Metas: {self.meta_texto}   [{'✓' if estado_abd=='✓' else '✗'}]\n")
                self.text_info.config(state="disabled")
                self.last_update = time.time()

            if self.grabando and self.writer:
                self.writer.write(frame_land)

            time.sleep(0.02)

        # liberar
        self.cap_cam.release()
        if self.cap_ref:
            self.cap_ref.release()
        if self.writer:
            self.writer.release()

    def cerrar_ventana_comparacion(self):
        if not self.ultimo_reporte.get("paciente"):
            self.ultimo_reporte.update({
                "paciente": self.paciente_var.get(),
                "fecha": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ejercicio": self.ejercicio_seleccionado,
                "comparacion": {"Flexión": 0.0, "Abducción": 0.0}
            })
        try:
            if hasattr(self, "cap_cam") and self.cap_cam:
                self.cap_cam.release()
            if hasattr(self, "cap_ref") and self.cap_ref:
                self.cap_ref.release()
            if hasattr(self, "writer") and self.writer:
                self.writer.release()
        finally:
            if hasattr(self, "vent_comparacion") and self.vent_comparacion:
                self.vent_comparacion.destroy()

    # ---------------- Exportar PDF ----------------
    def exportar_pdf(self):
        plantilla_path = "Plantilla.pdf"

        if not self.ultimo_reporte.get("paciente"):
            messagebox.showwarning("No hay datos", "Primero realiza una comparación.")
            return
        if not os.path.exists(plantilla_path):
            messagebox.showerror("Error", f"No se encontró la plantilla:\n{os.path.abspath(plantilla_path)}")
            return

        archivo_salida = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF","*.pdf")], initialfile="RESULTADOS"
        )
        if not archivo_salida:
            return

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        c.setFont("Helvetica", 11)

        def _xy(p): return (p[0] + OFFSET_X, p[1] + OFFSET_Y)
        def _draw_grid(step=GRID_STEP):
            w, h = letter
            c.saveState(); c.setFont("Helvetica", 6); c.setFillColor(grey); c.setStrokeColor(grey)
            for x in range(0, int(w)+1, step):
                c.line(x, 0, x, h); c.drawString(x+2, 4, str(x))
            for y in range(0, int(h)+1, step):
                c.line(0, y, w, y); c.drawString(2, y+2, str(y))
            c.restoreState()
        def _cross(x, y, s=6):
            c.saveState(); c.setFillColor(red); c.setStrokeColor(red)
            c.line(x-s, y, x+s, y); c.line(x, y-s, x, y+s); c.restoreState()
        def draw_left(xy, text, show_cross=SHOW_GUIDES):
            if text is None or str(text).strip() == "": return
            x, y = _xy(xy); 
            if show_cross: _cross(x, y); 
            c.drawString(x, y, str(text))
        def draw_right(xy, text, show_cross=SHOW_GUIDES):
            if text is None or str(text).strip() == "": return
            s = str(text); x, y = _xy(xy); w = c.stringWidth(s, "Helvetica", 11)
            if show_cross: _cross(x, y); 
            c.drawString(x - w, y, s)
        def draw_wrapped(xy, text, width=320):
            if text is None or str(text).strip() == "": return
            x, y = _xy(xy); words = str(text).split(); line=""; lines=[]
            for w in words:
                t=(line+" "+w).strip()
                if c.stringWidth(t,"Helvetica",11)<=width: line=t
                else: lines.append(line); line=w
            if line: lines.append(line)
            for i, ln in enumerate(lines): c.drawString(x, y-14*i, ln)
            if SHOW_GUIDES: _cross(x, y)

        if SHOW_GUIDES: _draw_grid()
        c.setFillColor(white)
        for (x,y,w,h) in ERASE_BOXES:
            xx, yy = _xy((x,y)); c.rect(xx, yy, w, h, fill=1, stroke=0)
        c.setFillColor(black)

        nombre = self.ultimo_reporte.get("paciente","")
        edad = self.edad_var.get()
        fecha = self.ultimo_reporte.get("fecha","")
        ejercicio = self.ultimo_reporte.get("ejercicio","")
        ang_res = self.ultimo_reporte.get("comparacion",{})
        rep = self.ultimo_reporte.get("repeticiones","")
        ser = self.ultimo_reporte.get("series","")
        peso = self.ultimo_reporte.get("peso","")

        draw_left(COORDS["paciente"], nombre)
        draw_right((COORDS["edad"][0]+80, COORDS["edad"][1]), edad)
        draw_left(COORDS["fecha"], fecha)

        draw_wrapped(COORDS["ejercicio"], ejercicio, width=320)
        draw_left(COORDS["peso"], peso)

        # Mostrar "90° / 180°" como referencia
        draw_right((COORDS["ref_flex"][0]+40, COORDS["ref_flex"][1]), self.meta_texto)
        draw_right((COORDS["ref_abd"][0]+40,  COORDS["ref_abd"][1]),  self.meta_texto)

        draw_right((COORDS["res_flex"][0]+40, COORDS["res_flex"][1]),
                   f"{ang_res.get('Flexión','')}°" if ang_res.get('Flexión') not in ("",None) else "")
        draw_right((COORDS["res_abd"][0]+40,  COORDS["res_abd"][1]),
                   f"{ang_res.get('Abducción','')}°" if ang_res.get('Abducción') not in ("",None) else "")

        draw_left(COORDS["reps"], rep)
        draw_left(COORDS["series"], ser)

        c.save(); buffer.seek(0)
        new_pdf = PdfReader(buffer)
        plantilla = PdfReader(plantilla_path)
        out = PdfWriter()
        page = plantilla.pages[0]
        page.merge_page(new_pdf.pages[0])
        out.add_page(page)
        with open(archivo_salida, "wb") as f:
            out.write(f)
        messagebox.showinfo("Éxito", "Reporte exportado correctamente.")


# ---------------- HoverButton ----------------
class HoverButton(tk.Button):
    def __init__(self, master=None, **kw):
        super().__init__(master=master, **kw)


# ---------------- Main ----------------
if __name__ == "__main__":
    app = ProyectoUniApp()
    app.mainloop()

