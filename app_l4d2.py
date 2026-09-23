import os
import shutil
import subprocess
import struct
import threading
import json
import customtkinter as ctk
from tkinter import filedialog
from PIL import Image

try:
    import vpk as vpk_lib
except ImportError:
    vpk_lib = None


class L4D2ModManagerUnificado:
    def __init__(self, l4d2_base, log_fn=print):
        self.log = log_fn
        self.l4d2_base = l4d2_base
        self.workshop_path = os.path.join(self.l4d2_base, "left4dead2", "addons", "workshop")
        self.addons_path = os.path.join(self.l4d2_base, "left4dead2", "addons")
        self.vpk_exe = os.path.join(self.l4d2_base, "bin", "vpk.exe")
        self.usermod_path = os.path.join(self.l4d2_base, "usermod")

        self.temp_root = os.path.join(self.l4d2_base, "_mod_merger_temp")
        self.extracted_root = os.path.join(self.temp_root, "extracted")
        self.merge_folder = os.path.join(self.temp_root, "merged")

        self.final_name = "mods_fusionados"
        self.final_vpk_path = os.path.join(self.addons_path, self.final_name + ".vpk")
        
        self.vpks_seleccionados = []

    def set_vpks(self, lista_vpks):
        self.vpks_seleccionados = lista_vpks

    def _leer_cstring(self, f):
        buf = bytearray()
        while True:
            b = f.read(1)
            if not b or b == b'\x00':
                break
            buf += b
        return buf.decode('utf-8', errors='replace')

    def extraer_vpk(self, vpk_path, destino):
        os.makedirs(destino, exist_ok=True)
        if vpk_lib is not None:
            try:
                pak = vpk_lib.open(vpk_path)
                cantidad = 0
                for filepath in pak:
                    entry = pak[filepath]
                    destino_archivo = os.path.join(destino, filepath)
                    os.makedirs(os.path.dirname(destino_archivo), exist_ok=True)
                    with open(destino_archivo, "wb") as f:
                        f.write(entry.read())
                    cantidad += 1
                return cantidad
            except Exception as e:
                self.log(f"Advertencia: Librería vpk falló, usando extracción manual. ({e})")

        try:
            return self._extraer_vpk_manual(vpk_path, destino)
        except Exception as e:
            self.log(f"Error crítico en parser manual: {e}")
            return 0

    def _extraer_vpk_manual(self, vpk_path, destino):
        os.makedirs(destino, exist_ok=True)
        cantidad = 0
        with open(vpk_path, 'rb') as f:
            signature, version, tree_size = struct.unpack('<III', f.read(12))
            if signature != 0x55AA1234:
                raise ValueError("Firma VPK inválida")
            if version == 2:
                f.read(16)
            tree_start = f.tell()
            data_start = tree_start + tree_size

            while True:
                ext = self._leer_cstring(f)
                if ext == '': break
                while True:
                    directorio = self._leer_cstring(f)
                    if directorio == '': break
                    while True:
                        nombre = self._leer_cstring(f)
                        if nombre == '': break

                        crc, preload_bytes, archive_index, entry_offset, entry_length, term = struct.unpack('<IHHIIH', f.read(18))
                        preload_data = f.read(preload_bytes) if preload_bytes else b''
                        
                        componentes = [ext, directorio, nombre]
                        if any('\ufffd' in c for c in componentes):
                            extension_segura = ext if (ext != ' ' and '\ufffd' not in ext) else 'dat'
                            rel_path = f"_nombres_corruptos/archivo_{crc:08x}.{extension_segura}"
                        else:
                            rel_path = '' if nombre == ' ' else nombre
                            if ext != ' ': rel_path += f'.{ext}'
                            if directorio != ' ': rel_path = f'{directorio}/{rel_path}'

                        destino_archivo = os.path.join(destino, rel_path)
                        os.makedirs(os.path.dirname(destino_archivo), exist_ok=True)

                        with open(destino_archivo, 'wb') as out:
                            out.write(preload_data)
                            if entry_length:
                                if archive_index == 0x7FFF:
                                    pos_actual = f.tell()
                                    f.seek(data_start + entry_offset)
                                    out.write(f.read(entry_length))
                                    f.seek(pos_actual)
                                else:
                                    archivo_externo = vpk_path.replace("_dir.vpk", f"_{archive_index:03d}.vpk")
                                    with open(archivo_externo, 'rb') as ext_f:
                                        ext_f.seek(entry_offset)
                                        out.write(ext_f.read(entry_length))
                        cantidad += 1
        return cantidad

    def verificar_entorno(self):
        if not self.l4d2_base or not os.path.exists(self.l4d2_base):
            self.log("Error: Directorio principal del juego no válido.")
            return False
        if not os.path.exists(self.workshop_path):
            self.log(f"Error: No existe la carpeta Workshop en:\n{self.workshop_path}")
            return False
        if not os.path.exists(self.vpk_exe):
            self.log(f"Error: No se encontró vpk.exe en:\n{self.vpk_exe}")
            return False
        if not self.vpks_seleccionados:
            self.log("Error: No se ha seleccionado ningún mod para procesar.")
            return False
            
        os.makedirs(self.addons_path, exist_ok=True)
        return True

    def preparar_temporales(self):
        if os.path.exists(self.temp_root):
            shutil.rmtree(self.temp_root)
        os.makedirs(self.extracted_root)
        os.makedirs(self.merge_folder)

    def fusionar_mods(self, agregar_existente=False, opcion_destino=1):
        self.log("\nExtrayendo mods seleccionados...")
        mods_data = []

        for vpk in self.vpks_seleccionados:
            nombre = os.path.splitext(vpk)[0]
            vpk_path = os.path.join(self.workshop_path, vpk)
            carpeta_destino = os.path.join(self.extracted_root, nombre)

            self.log(f"Procesando: {nombre}")
            cantidad = self.extraer_vpk(vpk_path, carpeta_destino)
            if cantidad > 0:
                mods_data.append({"nombre": nombre, "carpeta": carpeta_destino})

        if agregar_existente:
            ruta_base = self.final_vpk_path if opcion_destino == 1 else os.path.join(self.usermod_path, "pak01_dir.vpk")
            if os.path.exists(ruta_base):
                self.log(f"Desempaquetando estructura base existente: {os.path.basename(ruta_base)}")
                carpeta_base = os.path.join(self.extracted_root, "__base_fusion__")
                cantidad = self.extraer_vpk(ruta_base, carpeta_base)
                if cantidad > 0:
                    mods_data.append({"nombre": "Base_Existente", "carpeta": carpeta_base})
            else:
                self.log("Aviso: No se encontró una fusión previa. Se iniciará desde cero.")

        if not mods_data:
            self.log("Error: Ningún archivo pudo ser extraído.")
            return False

        self.log("Fusionando directorios y resolviendo conflictos...")
        mods_data.reverse()
        archivos_anteriores = {}
        conflictos = {}

        for mod in mods_data:
            carpeta = mod["carpeta"]
            nombre_mod = mod["nombre"]
            for raiz, _, archivos in os.walk(carpeta):
                for archivo in archivos:
                    origen = os.path.join(raiz, archivo)
                    rel_path = os.path.relpath(origen, carpeta)
                    destino = os.path.join(self.merge_folder, rel_path)

                    if rel_path in archivos_anteriores:
                        if rel_path not in conflictos:
                            conflictos[rel_path] = [archivos_anteriores[rel_path]]
                        conflictos[rel_path].append(nombre_mod)

                    os.makedirs(os.path.dirname(destino), exist_ok=True)
                    shutil.copy2(origen, destino)
                    archivos_anteriores[rel_path] = nombre_mod

        self.log(f"Fusión completada. Archivos reemplazados por prioridad: {len(conflictos)}")
        return True

    def empaquetar_fusion(self):
        self.log("Compilando nueva estructura VPK...")
        try:
            resultado = subprocess.run(
                [self.vpk_exe, os.path.abspath(self.merge_folder)],
                cwd=self.temp_root, capture_output=True, text=True, timeout=300
            )
            if resultado.returncode != 0:
                self.log("Error durante la ejecución del compilador vpk.exe.")
                return False
        except Exception as e:
            self.log(f"Error de subproceso (vpk.exe): {e}")
            return False

        vpk_generado = self.merge_folder.rstrip("/\\") + ".vpk"
        if not os.path.exists(vpk_generado):
            self.log("Error: Archivo compilado no encontrado.")
            return False

        if os.path.exists(self.final_vpk_path):
            os.remove(self.final_vpk_path)
        shutil.move(vpk_generado, self.final_vpk_path)
        self.log("Módulo VPK principal creado exitosamente.")
        return True
        
    def parchear_gameinfo(self):
        # Parchea de forma segura el gameinfo.txt basándose en la estructura del motor Source
        gameinfo_path = os.path.join(self.l4d2_base, "left4dead2", "gameinfo.txt")
        if not os.path.exists(gameinfo_path):
            self.log(f"Advertencia: Archivo gameinfo no encontrado en {gameinfo_path}")
            return False
            
        try:
            os.chmod(gameinfo_path, 0o666) # Asegurar permisos de escritura
            with open(gameinfo_path, 'r', encoding='utf-8') as f:
                lineas = f.readlines()
                
            tiene_usermod = any("usermod" in l.lower() for l in lineas)
            if tiene_usermod:
                self.log("El archivo gameinfo.txt ya está configurado para leer 'usermod'.")
                return True
                
            nuevas_lineas = []
            en_searchpaths = False
            inyectado = False
            
            for linea in lineas:
                nuevas_lineas.append(linea)
                if "SearchPaths" in linea:
                    en_searchpaths = True
                elif en_searchpaths and "{" in linea and not inyectado:
                    # Inyecta la línea exactamente como requiere el formato de Valve
                    nuevas_lineas.append("\t\t\tGame\t\t\t\tusermod\n")
                    inyectado = True
                    
            if inyectado:
                with open(gameinfo_path, 'w', encoding='utf-8') as f:
                    f.writelines(nuevas_lineas)
                self.log("Configuración del juego (gameinfo.txt) parcheada exitosamente.")
                return True
            else:
                self.log("Error estructural: No se pudo localizar el bloque 'SearchPaths' en gameinfo.txt.")
                return False
                
        except Exception as e:
            self.log(f"Error modificando gameinfo.txt: {e}")
            return False

    def instalar_en_usermod(self):
        self.log("\nIniciando inyección en el directorio raíz 'usermod'...")
        os.makedirs(self.usermod_path, exist_ok=True)
        destino_vpk = os.path.join(self.usermod_path, "pak01_dir.vpk")

        if os.path.exists(destino_vpk):
            self.log("Detectado pak01_dir.vpk anterior. Sobrescribiendo...")
            try:
                os.remove(destino_vpk)
            except Exception as e:
                self.log(f"Error de permisos. Cierre el juego antes de compilar. Detalles: {e}")
                return False

        try:
            shutil.move(self.final_vpk_path, destino_vpk)
            self.log(f"Operación finalizada. Archivo instalado en: {destino_vpk}")
            self.parchear_gameinfo()
            return True
        except Exception as e:
            self.log(f"Error moviendo el paquete compilado a usermod: {e}")
            return False

    def limpiar_temporales(self):
        if os.path.exists(self.temp_root):
            shutil.rmtree(self.temp_root)
            self.log("Directorio temporal purgado.")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.c_fondo = "#1a1a1a"
        self.c_panel = "#242424"
        self.c_rojo = "#8b0000"
        self.c_rojo_oscuro = "#4d0000"
        self.c_verde = "#2e4a21"
        self.c_verde_hover = "#1d3014"
        self.c_texto = "#e0e0e0"
        self.c_terminal = "#0d0d0d"
        self.c_texto_term = "#a3b899"

        self.title("L4D2 VPK Mod Manager")
        self.geometry("1050x650")
        self.minsize(900, 600)
        self.configure(fg_color=self.c_fondo)

        self.config_file = "l4d2_manager_config.json"
        self.l4d2_base = self.cargar_configuracion()
        self.mods_disponibles = [] 
        self.seleccionados = [] 
        self.botones_mods = {} 

        self.construir_interfaz()
        
        if not self.l4d2_base or not os.path.exists(self.l4d2_base):
            self.log("Aviso: Directorio del juego no configurado. Haga clic en 'Configurar Directorio'.")
        else:
            self.cargar_mods_desde_disco()

    def cargar_configuracion(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    return data.get("l4d2_path", "")
            except Exception:
                return ""
        return ""

    def guardar_configuracion(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump({"l4d2_path": self.l4d2_base}, f)
        except Exception as e:
            self.log(f"Error guardando configuración: {e}")

    def solicitar_directorio(self):
        ruta = filedialog.askdirectory(title="Seleccione la carpeta raíz de Left 4 Dead 2")
        if ruta:
            self.l4d2_base = os.path.normpath(ruta)
            self.guardar_configuracion()
            self.log(f"Directorio establecido: {self.l4d2_base}")
            self.cargar_mods_desde_disco()

    def construir_interfaz(self):
        font_titulo = ctk.CTkFont(family="Segoe UI", size=15, weight="bold")
        font_botones = ctk.CTkFont(family="Segoe UI", size=13, weight="normal")

        self.frame_izq = ctk.CTkFrame(self, fg_color=self.c_panel, corner_radius=8)
        self.frame_izq.pack(side="left", fill="both", expand=True, padx=15, pady=15)
        
        lbl_galeria = ctk.CTkLabel(self.frame_izq, text="Repositorio de Workshop", font=font_titulo)
        lbl_galeria.pack(pady=(15, 5))

        self.scroll_galeria = ctk.CTkScrollableFrame(self.frame_izq, fg_color=self.c_fondo, corner_radius=5)
        self.scroll_galeria.pack(fill="both", expand=True, padx=10, pady=(0,10))
        
        self.frame_der = ctk.CTkFrame(self, width=380, fg_color=self.c_panel, corner_radius=8)
        self.frame_der.pack(side="right", fill="both", padx=(0,15), pady=15)
        self.frame_der.pack_propagate(False)

        self.btn_dir = ctk.CTkButton(
            self.frame_der, text="Configurar Directorio L4D2", font=font_botones,
            fg_color="#3a3a3a", hover_color="#525252", command=self.solicitar_directorio
        )
        self.btn_dir.pack(fill="x", padx=15, pady=(15, 5))

        lbl_lista = ctk.CTkLabel(self.frame_der, text="Orden de Inyección", font=font_titulo)
        lbl_lista.pack(pady=(10, 5))
        
        self.caja_lista = ctk.CTkTextbox(
            self.frame_der, height=120, state="disabled", 
            fg_color=self.c_terminal, text_color=self.c_texto,
            border_color="#3a3a3a", border_width=1
        )
        self.caja_lista.pack(fill="x", padx=15, pady=5)

        self.var_agregar = ctk.BooleanVar(value=False)
        self.chk_agregar = ctk.CTkCheckBox(
            self.frame_der, text="Anexar a estructura existente",
            variable=self.var_agregar, font=font_botones,
            fg_color=self.c_rojo, hover_color=self.c_rojo_oscuro
        )
        self.chk_agregar.pack(pady=(5, 10), padx=15, anchor="w")

        self.btn_fusion = ctk.CTkButton(
            self.frame_der, text="Compilar en Directorio Addons", font=font_botones,
            fg_color="#333333", hover_color="#454545",
            command=lambda: self.lanzar_tarea(1)
        )
        self.btn_fusion.pack(fill="x", padx=20, pady=5)

        self.btn_usermod = ctk.CTkButton(
            self.frame_der, text="Inyectar en Directorio Usermod", font=font_botones,
            fg_color=self.c_verde, hover_color=self.c_verde_hover,
            command=lambda: self.lanzar_tarea(2)
        )
        self.btn_usermod.pack(fill="x", padx=20, pady=5)
        
        self.consola = ctk.CTkTextbox(
            self.frame_der, font=("Consolas", 11), 
            fg_color=self.c_terminal, text_color=self.c_texto_term,
            border_width=1, border_color="#1a1a1a"
        )
        self.consola.pack(fill="both", expand=True, padx=15, pady=(15,15))
        self.consola.insert("end", "Consola del gestor inicializada.\n")

    def cargar_mods_desde_disco(self):
        workshop_path = os.path.join(self.l4d2_base, "left4dead2", "addons", "workshop")
        if not os.path.exists(workshop_path):
            self.log(f"Error: Ruta de workshop inaccesible:\n{workshop_path}")
            return

        for widget in self.scroll_galeria.winfo_children():
            widget.destroy()
        self.botones_mods.clear()
        self.seleccionados.clear()
        self.actualizar_caja_lista()

        self.mods_disponibles = [f for f in os.listdir(workshop_path) if f.lower().endswith(".vpk")]
        columnas, fila, col = 3, 0, 0

        for vpk in self.mods_disponibles:
            nombre_base = os.path.splitext(vpk)[0]
            ruta_img = os.path.join(workshop_path, f"{nombre_base}.jpg")
            
            try:
                if os.path.exists(ruta_img):
                    img_pil = Image.open(ruta_img)
                    img_pil.thumbnail((110, 110)) 
                    img = ctk.CTkImage(light_image=img_pil, size=(110, 110))
                else:
                    img_pil = Image.new('RGB', (110, 110), color=(30, 30, 30))
                    img = ctk.CTkImage(light_image=img_pil, size=(110, 110))
            except Exception:
                img_pil = Image.new('RGB', (110, 110), color=(50, 20, 20))
                img = ctk.CTkImage(light_image=img_pil, size=(110, 110))

            btn = ctk.CTkButton(
                self.scroll_galeria, 
                image=img, 
                text=nombre_base[:15] + "...", 
                compound="top",
                fg_color="transparent",
                text_color=self.c_texto,
                hover_color="#2b2b2b",
                border_width=1,
                border_color="#333333",
                command=lambda v=vpk: self.toggle_seleccion(v)
            )
            btn.grid(row=fila, column=col, padx=5, pady=5)
            self.botones_mods[vpk] = btn

            col += 1
            if col >= columnas:
                col = 0
                fila += 1

    def toggle_seleccion(self, vpk):
        if vpk in self.seleccionados:
            self.seleccionados.remove(vpk)
            self.botones_mods[vpk].configure(border_color="#333333", fg_color="transparent")
        else:
            self.seleccionados.append(vpk)
            self.botones_mods[vpk].configure(border_color=self.c_rojo, fg_color=self.c_rojo_oscuro)
            
        self.actualizar_caja_lista()

    def actualizar_caja_lista(self):
        self.caja_lista.configure(state="normal")
        self.caja_lista.delete("1.0", "end")
        
        if not self.seleccionados:
            self.caja_lista.insert("end", "Ningún archivo seleccionado.")
        else:
            for i, vpk in enumerate(self.seleccionados):
                nombre = os.path.splitext(vpk)[0]
                self.caja_lista.insert("end", f"[{i+1}] {nombre}\n")
                
        self.caja_lista.configure(state="disabled")

    def log(self, mensaje):
        self.after(0, self._append_text, mensaje)

    def _append_text(self, texto):
        self.consola.insert("end", str(texto) + "\n")
        self.consola.see("end")

    def toggle_botones(self, estado):
        modo = "normal" if estado else "disabled"
        self.btn_fusion.configure(state=modo)
        self.btn_usermod.configure(state=modo)
        self.chk_agregar.configure(state=modo)
        self.btn_dir.configure(state=modo)

    def lanzar_tarea(self, opcion):
        if not self.l4d2_base:
            self.log("Error: Defina el directorio raíz primero.")
            return
        if not self.seleccionados:
            self.log("Error: La lista de procesamiento está vacía.")
            return
            
        self.toggle_botones(False)
        self.consola.delete("1.0", "end")
        self.log("Iniciando secuencia de compilación...")
        
        agregar = self.var_agregar.get()
        threading.Thread(target=self._ejecutar_manager, args=(opcion, agregar), daemon=True).start()

    def _ejecutar_manager(self, opcion, agregar_existente):
        mgr = L4D2ModManagerUnificado(l4d2_base=self.l4d2_base, log_fn=self.log)
        mgr.set_vpks(self.seleccionados)
        
        try:
            if not mgr.verificar_entorno():
                return

            mgr.preparar_temporales()

            if mgr.fusionar_mods(agregar_existente=agregar_existente, opcion_destino=opcion):
                if mgr.empaquetar_fusion():
                    if opcion == 2:
                        mgr.instalar_en_usermod()

            mgr.limpiar_temporales()
            self.log("\nEjecución completada.")
        except Exception as e:
            self.log(f"\nExcepción en hilo de ejecución: {e}")
        finally:
            self.after(0, lambda: self.toggle_botones(True))


if __name__ == "__main__":
    app = App()
    app.mainloop()
