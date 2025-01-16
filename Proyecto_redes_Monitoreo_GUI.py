import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, font
import telnetlib
import os
import time
import sys
import threading
from functools import partial  # Importar functools.partial

# ==================
#  Variables globales
# ==================

ventana = None
canvas_frame = None
lienzo = None

routers = []      # Routers para verificación (Telnet)
devices = []      # Todos los dispositivos (routers, switches, PCs, VM)
lineas_dict = {}  # Guarda { "line_R1-R2": line_id, ... }
line_colors = {}  # Guarda { "line_R1-R2": "green", ... }

# Imágenes
imagen_router = None
imagen_switch = None
imagen_pc = None
imagen_vm = None

# Barra de progreso y etiqueta
barra_progreso = None
etiqueta_progreso = None

# Bounding box de la topología (usada para escalarla y centrarla)
min_x = float('inf')
max_x = float('-inf')
min_y = float('inf')
max_y = float('-inf')

# Mapeo de routers a sus dispositivos conectados
router_to_devices = {
    "R1": ["Switch1"],
    "R2": ["PC12", "PC11", "PC10"],
    "R3": ["PC9", "PC8", "PC7"],
    "R4": ["PC1", "PC2", "PC3"],
    "R5": ["PC4", "PC5", "PC6"],
    "Switch1": ["Ubuntu20.04VM-1"],  # Agregado
}

# Mapeo de switches a sus routers asociados
switch_to_router = {
    "Switch1": "R1",
}

# Definir todas las conexiones a evaluar (hardcodeadas)
conexiones = [
    ("R1", "Switch1", "192.168.100.0/24"),
    ("Switch1", "Ubuntu20.04VM-1", "192.168.100.0/24"),
    ("R1", "R2", "172.16.1.19/24"),
    ("R2", "R3", "180.16.1.0/24"),
    ("R2", "R4", "180.16.2.0/24"),
    ("R3", "R5", "180.16.4.0/24"),
    ("R4", "R5", "180.16.3.0/24"),
    ("R2", "PC12", ""),
    ("R2", "PC11", ""),
    ("R2", "PC10", ""),
    ("R3", "PC9", ""),
    ("R3", "PC8", ""),
    ("R3", "PC7", ""),
    ("R4", "PC1", ""),
    ("R4", "PC2", ""),
    ("R4", "PC3", ""),
    ("R5", "PC4", ""),
    ("R5", "PC5", ""),
    ("R5", "PC6", ""),
]

# ==================
#   Funciones Auxiliares
# ==================

def find_device(nombre):
    """
    Encuentra un dispositivo por su nombre.
    """
    for device in devices:
        if device["nombre"] == nombre:
            return device
    return None

def find_connected_switch(pc_nombre):
    """
    Encuentra el switch al que está conectada una PC o VM.
    """
    for switch, pcs in router_to_devices.items():
        if switch.startswith("Switch") and pc_nombre in pcs:
            return switch
    return None

def find_connected_router(pc_nombre, accessible_routers):
    """
    Encuentra el router al que está conectada una PC o VM, directamente o vía un switch,
    y verifica si el router es accesible.
    """
    # Verificar conexiones directas a routers
    for router, pcs in router_to_devices.items():
        if router.startswith("R") and (pc_nombre in pcs) and (router in accessible_routers):
            return router
    
    # Verificar conexiones a través de switches
    for switch, pcs in router_to_devices.items():
        if switch.startswith("Switch") and pc_nombre in pcs:
            # Retorna el router asociado al switch si es accesible
            router_associated = switch_to_router.get(switch)
            if router_associated and router_associated in accessible_routers:
                return router_associated
    return None

def CenterWindowToDisplay(screen, width: int, height: int, scale_factor: float = 1.0):
    """Centers the window to the main display/monitor."""
    screen_width = screen.winfo_screenwidth()
    screen_height = screen.winfo_screenheight()

    # Calcular la posición central
    x = int(((screen_width / 2) - (width / 2)) * scale_factor)
    y = int(((screen_height / 2) - (height / 2)) * scale_factor)

    return f"{width}x{height}+{x}+{y}"

# ==================
#   Funciones Telnet
# ==================

def conectar_telnet(router_ip, username, password, comandos, resultados_callback):
    """
    Conecta al router vía Telnet, ejecuta comandos y devuelve los resultados.
    En caso de fallo, llama al callback con un diccionario vacío.
    """
    try:
        port = 23
        tn = telnetlib.Telnet(router_ip, port, timeout=10)

        # Leer y enviar credenciales
        tn.read_until(b"Username:", timeout=5)
        tn.write(username.encode("utf-8") + b"\n")
        tn.read_until(b"Password:", timeout=5)
        tn.write(password.encode("utf-8") + b"\n")

        # Esperar el prompt (asumimos que es '>' o '#')
        index, obj, output = tn.expect([b">", b"#"], timeout=5)
        if index == -1:
            raise Exception("No se encontró el prompt del router.")

        resultados = {}

        for cmd_key, cmd in comandos.items():
            tn.write(cmd.encode("utf-8") + b"\n")
            salida = leer_comando_telnet(tn)
            resultados[cmd_key] = salida

        tn.write(b"exit\n")
        tn.close()

        resultados_callback(resultados)

    except Exception as e:
        # Log del error para depuración
        print(f"Error al conectar vía Telnet a {router_ip}: {e}")
        # Llamar al callback con un diccionario vacío para indicar falla
        resultados_callback({})

def leer_comando_telnet(tn):
    """
    Lee la salida de un comando Telnet hasta que no haya más paginación.
    """
    salida = ""
    while True:
        try:
            buffer = tn.read_until(b"--More--", timeout=3).decode("utf-8")
            salida += buffer.replace("--More--", "")
            if "--More--" in buffer:
                tn.write(b" ")  # Enviar espacio para continuar
            else:
                break
        except EOFError:
            break
        except Exception:
            break
    return salida

def verificar_router_telnet(ip, username, password, resultado_callback):
    """
    Verifica si el router está accesible vía Telnet.
    Ejecuta la conexión y llama al callback con el resultado.
    """
    try:
        tn = telnetlib.Telnet(ip, timeout=5)
        tn.close()
        resultado_callback(ip, True)
    except Exception:
        resultado_callback(ip, False)

# ==================
#   Funciones GUI
# ==================

def actualizar_linea_color(line_name, color):
    """
    Actualiza el color de una línea en la GUI de manera segura.
    """
    if line_name in lineas_dict:
        def _update():
            lienzo.itemconfig(lineas_dict[line_name], fill=color)
            print(f"Actualizando línea {line_name} a color {color}.")  # Añadido log para debug
        ventana.after(0, _update)
    else:
        print(f"Línea {line_name} no encontrada en lineas_dict.")  # Añadido log para debug


def actualizar_progreso(progreso, texto):
    """
    Actualiza la barra de progreso y la etiqueta de manera segura.
    """
    def _update():
        barra_progreso.set(progreso / 100)
        etiqueta_progreso.configure(text=texto)
    ventana.after(0, _update)

# ==================
#   Monitoreo
# ==================

def monitorear_routers(accessible_routers):
    """
    Verifica el estado de los routers y actualiza la topología.
    Además, si un router no es accesible, marca sus líneas a dispositivos conectados en rojo.
    """
    print("Verificando estado de los routers...")
    total_routers = len(routers)

    # Conectar a todos los routers en hilos separados
    threads = []
    for i, router in enumerate(routers, start=1):
        ip = router["ip"]
        username = router["username"]
        password = router["password"]
        nombre = router.get("nombre")

        # Usar functools.partial para pasar argumentos actuales al callback
        resultado_verificacion = partial(
            manejar_resultado_verificacion,
            nombre=nombre,
            accessible_routers=accessible_routers
        )

        comandos = {
            "running-config": "show running-config",
            "Interface": "show ip interface brief",
            "Ip route": "show ip route",
            "ACL": "show access-lists",
            "NAT": "show ip nat translations",
            "DHCP": "show ip dhcp pool",
        }

        # Utilizar partial para enlazar correctamente los argumentos
        t = threading.Thread(target=partial(conectar_telnet, ip, username, password, comandos, resultado_verificacion))
        t.start()
        threads.append(t)

        progreso = (i / total_routers) * 30  # 30% para routers
        actualizar_progreso(progreso, f"Verificando routers: {int(progreso)}%")
    
    # Esperar a que todas las verificaciones terminen
    for t in threads:
        t.join()

    print("Verificación de routers completada.")

def manejar_resultado_verificacion(resultados, nombre, accessible_routers):
    """
    Maneja el resultado de la verificación de un router.
    Actualiza las líneas conectadas según el resultado.
    """
    if resultados:
        accessible_routers.add(nombre)
        # Marcar líneas conectadas en negro o dejarlas en negro si son conexiones SSH
        connected_devices = router_to_devices.get(nombre, [])
        for device_nombre in connected_devices:
            device = find_device(device_nombre)
            if device:
                if device["tipo"] == "switch":
                    line_color = "green"
                elif device["tipo"] == "pc" or device["tipo"] == "vm":
                    # Conexión a PC o VM: dejar en negro, se actualizará con ping
                    line_color = "red"
                else:
                    # Otros tipos de dispositivos, por defecto negro
                    line_color = "red"
                line_name = f"line_{nombre}-{device_nombre}"
                actualizar_linea_color(line_name, line_color)
                line_colors[line_name] = line_color
                print(f"Marca la línea {line_name} en {line_color} porque {nombre} está accesible.")
    else:
        accessible_routers.discard(nombre)
        # Marcar líneas conectadas en rojo
        connected_devices = router_to_devices.get(nombre, [])
        for device_nombre in connected_devices:
            line_name = f"line_{nombre}-{device_nombre}"
            actualizar_linea_color(line_name, "red")
            line_colors[line_name] = "red"
            print(f"Marca la línea {line_name} en rojo porque {nombre} está inaccesible.")

def monitorear_conexiones_routers(accessible_routers):
    """
    Verifica el estado de las conexiones entre routers y actualiza la topología.
    Marca las líneas entre routers en verde si ambos routers son accesibles, de lo contrario en rojo.
    """
    print("Verificando conexiones entre routers...")
    # Filtrar solo las conexiones entre routers
    conexiones_entre_routers = [c for c in conexiones if c[0].startswith("R") and c[1].startswith("R")]
    total_conexiones = len(conexiones_entre_routers)

    contador = 0
    for conexion in conexiones_entre_routers:
        src, dst, ip_red = conexion
        # Verificar si ambos routers están accesibles
        if src in accessible_routers and dst in accessible_routers:
            # Asumimos que si ambos routers son accesibles, la conexión está activa
            color = "green"
        else:
            color = "red"
        line_name = f"line_{src}-{dst}"
        actualizar_linea_color(line_name, color)
        line_colors[line_name] = color
        print(f"Marca la línea {line_name} en {color} porque {'ambos routers son accesibles' if color == 'green' else 'al menos uno de los routers no es accesible'}.")
        contador += 1
        progreso = 30 + ((contador / total_conexiones) * 20)  # 30% routers + 20% conexiones
        actualizar_progreso(progreso, f"Verificando conexiones entre routers: {int(progreso)}%")

    print("Verificación de conexiones entre routers completada.")

def monitorear_pcs(accessible_routers):
    """
    Verifica el estado de las PCs y la VM de Ubuntu, y actualiza la topología.
    """
    print("Verificando estado de las PCs y VM de Ubuntu...")
    pcs = [device for device in devices if device["tipo"] in ["pc", "vm"]]
    total_pcs = len(pcs)

    for i, pc in enumerate(pcs, start=1):
        pc_nombre = pc["nombre"]
        pc_ip = pc["IP"]
        print(f"Procesando {pc_nombre} ({pc_ip})...")
        connected_router = find_connected_router(pc_nombre, accessible_routers)

        if connected_router is None:
            # No hay un router accesible conectado a esta PC o VM
            switch_connected = find_connected_switch(pc_nombre)
            line_name = f"line_{switch_connected}-{pc_nombre}" if switch_connected else None

            if line_name and line_name in lineas_dict:
                actualizar_linea_color(line_name, "red")
                line_colors[line_name] = "red"
                print(f"Marca la línea {line_name} en rojo porque no hay router accesible para {pc_nombre}.")
            progreso = 50 + ((i / total_pcs) * 30)  # 50% para routers + 20% conexiones + 30% PCs y VM
            actualizar_progreso(progreso, f"Verificando PCs y VM: {int(progreso)}%")
            continue

        # Caso especial: VM Ubuntu
        if pc["tipo"] == "vm":
            print(f"Verificando VM {pc_nombre} vía Telnet desde R1...")
            estado = verificar_vm_via_telnet("R1", pc_ip)

            # Actualizar líneas de conexión
            line_name_vm = f"line_Switch1-{pc_nombre}"
            line_name_switch = f"line_R1-Switch1"
            color = "green" if estado else "red"

            if line_name_vm in lineas_dict:
                actualizar_linea_color(line_name_vm, color)
                line_colors[line_name_vm] = color
                print(f"Marca la línea {line_name_vm} en {color} porque {pc_nombre} está {'alcanzable' if estado else 'inaccesible'}.")
            else:
                print(f"Línea {line_name_vm} no encontrada en lineas_dict.")

            if line_name_switch in lineas_dict:
                actualizar_linea_color(line_name_switch, color)
                line_colors[line_name_switch] = color
                print(f"Marca la línea {line_name_switch} en {color} porque el ping hacia {pc_nombre} {'fue exitoso' if estado else 'falló'}.")
            else:
                print(f"Línea {line_name_switch} no encontrada en lineas_dict.")
        else:
            print(f"Verificando PC {pc_nombre} localmente...")
            estado = verificar_pc_local(pc_ip)
            line_name = f"line_{connected_router}-{pc_nombre}"
            color = "green" if estado else "red"

            if line_name in lineas_dict:
                actualizar_linea_color(line_name, color)
                line_colors[line_name] = color
                print(f"Marca la línea {line_name} en {color} porque {pc_nombre} está {'alcanzable' if estado else 'inaccesible'}.")
            else:
                print(f"Línea {line_name} no encontrada en lineas_dict.")

        progreso = 50 + ((i / total_pcs) * 30)
        actualizar_progreso(progreso, f"Verificando PCs y VM: {int(progreso)}%")

def verificar_pc_local(pc_ip):
    """
    Verifica si la PC está activa haciendo ping a su IP con un timeout.
    """
    try:
        # Comando de ping según el sistema operativo
        if sys.platform.startswith('win'):
            ping_cmd = f'ping -n 1 {pc_ip}'
        else:
            ping_cmd = f'ping -c 1 {pc_ip}'

        # Ejecutar el comando de ping
        resultado = os.system(ping_cmd + " > /dev/null 2>&1")
        return resultado == 0
    except Exception as e:
        print(f"Error al verificar PC {pc_ip}: {e}")
        return False

def verificar_vm_via_telnet(router_nombre, vm_ip):
    """
    Verifica si la VM está activa haciendo ping desde el router especificado vía Telnet.
    Retorna True si el ping es exitoso, False de lo contrario.
    """
    router = next((r for r in routers if r["nombre"] == router_nombre), None)
    if not router:
        print(f"Router {router_nombre} no encontrado.")
        return False

    ip = router["ip"]
    username = router["username"]
    password = router["password"]

    try:
        print(f"Iniciando Telnet en {router_nombre} ({ip}) para hacer ping a {vm_ip}...")
        tn = telnetlib.Telnet(ip, 23, timeout=10)
        tn.read_until(b"Username:", timeout=5)
        tn.write(username.encode("utf-8") + b"\n")
        tn.read_until(b"Password:", timeout=5)
        tn.write(password.encode("utf-8") + b"\n")

        tn.expect([b">", b"#"], timeout=5)
        tn.write(f"ping {vm_ip}".encode("utf-8") + b"\n")
        salida = leer_comando_telnet(tn)
        tn.write(b"exit\n")
        tn.close()

        # Log detallado de salida del ping
        print(f"Salida del ping desde {router_nombre} hacia {vm_ip}:\n{salida}")

        # Determinar el estado basado en la salida del ping
        if "Success rate is 100 percent" in salida:
            print(f"Resultado del ping desde {router_nombre} hacia {vm_ip}: éxito.")
            return True
        else:
            print(f"Resultado del ping desde {router_nombre} hacia {vm_ip}: fracaso.")
            return False

    except Exception as e:
        print(f"Error al verificar VM vía Telnet desde {router_nombre}: {e}")
        return False

def run_monitoreo():
    """
    Ejecuta las tareas de monitoreo de routers, conexiones entre routers y PCs de manera sincrónica en un hilo separado.
    """
    try:
        accessible_routers = set()
        monitorear_routers(accessible_routers)
        monitorear_conexiones_routers(accessible_routers)
        monitorear_pcs(accessible_routers)
        # Finalizar la barra de progreso
        actualizar_progreso(100, "Completado: 100%")
        print("Monitoreo completo.")
    except Exception as e:
        messagebox.showerror("Error", f"Error durante el monitoreo: {e}")

def monitorear_routers_asincrono():
    """
    Inicia el monitoreo de routers, conexiones entre routers y PCs en un hilo separado para mantener la GUI responsiva.
    """
    inicio = time.time()

    # Resetear líneas a negro
    for line_name in lineas_dict:
        actualizar_linea_color(line_name, "black")

    # Resetear barras de progreso
    actualizar_progreso(0, "Verificando: 0%")

    # Iniciar monitoreo en un hilo separado
    hilo = threading.Thread(target=run_monitoreo)
    hilo.start()

    fin = time.time()
    print(f"Tiempo de monitoreo inicial: {fin - inicio:.2f} segundos")

# ======================
#  Manejo de clic e UI
# ======================

def clic_en_imagen(event):
    """
    Se llama cuando se hace clic en el canvas.
    Identifica si se clickeó un router/PC/VM y abre la ventana emergente.
    """
    x = event.x
    y = event.y

    for device in devices:
        # Coordenadas reales en pantalla
        ax, ay = device["actual_x"], device["actual_y"]

        if device["tipo"] in ["pc", "vm"]:
            ancho = imagen_pc.width()
            alto = imagen_pc.height()
        elif device["tipo"] == "switch":
            ancho = imagen_switch.width()
            alto = imagen_switch.height()
        else:
            ancho = imagen_router.width()
            alto = imagen_router.height()

        # Si clic dentro del bounding box de la imagen
        if (ax - ancho//2 <= x <= ax + ancho//2) and (ay - alto//2 <= y <= ay + alto//2):
            # Abrir ventana con toda la info del dispositivo
            abrir_ventana_device(device)
            break

def abrir_ventana_device(device_dict):
    """
    Ventana hija con detalles del dispositivo seleccionado.
    """
    device_ip = device_dict["IP"]
    username = "cisco"  # Valores por defecto
    password = "cisco"

    # Si es un router, obtener credenciales
    if device_dict["tipo"] == "router":
        for router in routers:
            if router["ip"] == device_ip:
                username = router["username"]
                password = router["password"]
                break

    ventana_hija = ctk.CTkToplevel(ventana)
    ventana_hija.title(f"Detalles - {device_dict['nombre']}")

    # Tamaño deseado
    w_ventana2 = 750
    h_ventana2 = 550

    # Centrar en la pantalla
    geometry_string = CenterWindowToDisplay(ventana_hija, w_ventana2, h_ventana2)
    ventana_hija.geometry(geometry_string)

    ventana_hija.transient(ventana)
    ventana_hija.lift()

    frame_main = ctk.CTkFrame(ventana_hija)
    frame_main.pack(fill="both", expand=True, padx=10, pady=10)

    # Información del dispositivo
    tipo_display = device_dict["tipo"].capitalize()
    lbl_info = ctk.CTkLabel(
        frame_main,
        text=f"Nombre: {device_dict['nombre']}\nIP: {device_ip}\nTipo: {tipo_display}",
        font=('Arial', 16)  # Define la fuente como una tupla
    )
    lbl_info.pack(pady=10)

    # Botón de Conectar si es un router
    if device_dict["tipo"] == "router":
        btn_connect = ctk.CTkButton(
            master=frame_main,
            text="Conectar vía Telnet",
            command=lambda: conectar_telnet_popup(device_dict, username, password)
        )
        btn_connect.pack(pady=10)

def conectar_telnet_popup(device_dict, username, password):
    """
    Abre una ventana para mostrar la información del router conectado vía Telnet.
    """
    def conexion_telnet():
        router_ip = device_dict["IP"]
        comandos = {
            "running-config": "show running-config",
            "Interface": "show ip interface brief",
            "Ip route": "show ip route",
            "ACL": "show access-lists",
            "NAT": "show ip nat translations",
            "DHCP": "show ip dhcp pool",
        }

        def resultado_callback(resultados):
            if resultados:
                def crear_ventana_resultados():
                    # Crear ventana hija para mostrar resultados
                    ventana_resultados = ctk.CTkToplevel(ventana)
                    ventana_resultados.title(f"Telnet - {device_dict['nombre']}")

                    # Tamaño deseado
                    w_resultados = 800
                    h_resultados = 600

                    # Centrar en la pantalla
                    geometry_string = CenterWindowToDisplay(ventana_resultados, w_resultados, h_resultados)
                    ventana_resultados.geometry(geometry_string)

                    ventana_resultados.transient(ventana)
                    ventana_resultados.lift()

                    frame_result = ctk.CTkFrame(ventana_resultados)
                    frame_result.pack(fill="both", expand=True, padx=10, pady=10)

                    # Crear Tabview para los resultados
                    notebook_result = ctk.CTkTabview(frame_result, width=760, height=550)
                    notebook_result.pack(fill="both", expand=True)

                    cuadros_texto = {}  # Definir cuadros_texto aquí
                    for pestaña, contenido in resultados.items():
                        notebook_result.add(pestaña)
                        tab = notebook_result.tab(pestaña)
                        text_box = tk.Text(tab, wrap="word")
                        text_box.pack(fill="both", expand=True, padx=5, pady=5)
                        text_box.insert("1.0", contenido)
                        cuadros_texto[pestaña] = text_box  # Guardar referencia

                ventana.after(0, crear_ventana_resultados)
            else:
                def mostrar_error():
                    messagebox.showerror("Error", f"No se pudo obtener resultados vía Telnet para {router_ip}.")
                ventana.after(0, mostrar_error)

        conectar_telnet(router_ip, username, password, comandos, resultado_callback)

    # Iniciar la conexión Telnet en un hilo separado para no bloquear la GUI
    hilo = threading.Thread(target=conexion_telnet)
    hilo.start()

# ==================
#   DIBUJADO + ESCALA
# ==================

def draw_topologia_escalada(canvas_w, canvas_h):
    """
    Dibuja la topología completa con conexiones entre routers, switches, PCs y VM Ubuntu en la disposición solicitada.
    """
    lienzo.delete("all")

    # Escalado y centrado
    topo_width = max_x - min_x
    topo_height = max_y - min_y
    if topo_width <= 0 or topo_height <= 0:
        return

    scale_w = (canvas_w * 0.8) / topo_width
    scale_h = (canvas_h * 0.8) / topo_height
    scale_factor = min(scale_w, scale_h)

    cx_canvas = canvas_w // 2
    cy_canvas = canvas_h // 2
    cx_topo = (min_x + max_x) / 2
    cy_topo = (min_y + max_y) / 2

    text_font = font.Font(size=14, weight="bold")

    def dibujar_texto_con_fondo(x, y, texto, fuente, color_texto="black", color_fondo="white"):
        text_id = lienzo.create_text(x, y, text=texto, font=fuente, fill=color_texto, tags=f"text_{texto}")
        x1, y1, x2, y2 = lienzo.bbox(text_id)
        pad = 3
        rect_id = lienzo.create_rectangle(x1 - pad, y1 - pad, x2 + pad, y2 + pad, fill=color_fondo, outline="")
        lienzo.tag_lower(rect_id, text_id)

    # Disposición de dispositivos
    for device in devices:
        ox, oy = device["orig_x"], device["orig_y"]
        dx = ox - cx_topo
        dy = oy - cy_topo
        sx = dx * scale_factor
        sy = dy * scale_factor
        ax = cx_canvas + sx
        ay = cy_canvas + sy
        device["actual_x"] = ax
        device["actual_y"] = ay

    # Dibujar conexiones (líneas)
    def dibujar_linea(r1, r2, ip_red, line_name):
        """
        Dibuja una línea en el canvas entre dos dispositivos y registra la línea en el diccionario.
        """
        x1, y1 = r1["actual_x"], r1["actual_y"]
        x2, y2 = r2["actual_x"], r2["actual_y"]
        color = line_colors.get(line_name, "black")
        lid = lienzo.create_line(x1, y1, x2, y2, fill=color, width=5)
        lineas_dict[line_name] = lid
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        if ip_red:
            dibujar_texto_con_fondo(mx, my, ip_red, text_font)
        print(f"Línea dibujada: {line_name}, Color inicial: {color}")

    # Dibujar conexiones
    for conexion in conexiones:
        src, dst, ip_red = conexion
        r1 = find_device(src)
        r2 = find_device(dst)
        if r1 and r2:
            dibujar_linea(r1, r2, ip_red, f"line_{src}-{dst}")
            print(f"Línea inicializada: line_{src}-{dst}")

    # Dibujar dispositivos
    for device in devices:
        ax, ay = device["actual_x"], device["actual_y"]
        img = imagen_router if device["tipo"] == "router" else (
            imagen_switch if device["tipo"] == "switch" else (
                imagen_pc if device["tipo"] == "pc" else imagen_vm
            )
        )
        imagen = img  # Evitar garbage collector
        tags = device["nombre"]
        lienzo.create_image(ax, ay, image=imagen, anchor="center", tags=tags)
        dibujar_texto_con_fondo(ax, ay + 30, device["nombre"], text_font)

    lienzo.bind("<Button-1>", clic_en_imagen)

# ==================
#      Main
# ==================

def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    global ventana, canvas_frame, lienzo
    ventana = ctk.CTk()
    ventana.title("Proyecto Final - Nullbytes - Feliciano Acatitlan Juan Antonio - Guzmán Cruz Andrés Miguel")

    # Centrar la ventana principal
    ventana.geometry(CenterWindowToDisplay(ventana, 1000, 600, 1.0))

    # Frame para el canvas
    canvas_frame = ctk.CTkFrame(ventana)
    canvas_frame.pack(fill="both", expand=True, padx=10, pady=10)

    # Canvas
    lienzo = tk.Canvas(canvas_frame, bg="white")
    lienzo.pack(fill="both", expand=True)
    lienzo.bind("<Configure>", lambda event: draw_topologia_escalada(event.width, event.height))

    # Frame inferior para botón y barra de progreso
    bottom_frame = ctk.CTkFrame(ventana)
    bottom_frame.pack(fill="x", expand=False)

    btn_monitorear = ctk.CTkButton(
        bottom_frame,
        text="Monitorear",
        command=monitorear_routers_asincrono
    )
    btn_monitorear.pack(side="left", padx=5, pady=5)

    global barra_progreso, etiqueta_progreso
    barra_progreso = ctk.CTkProgressBar(
        bottom_frame,
        orientation="horizontal",
        width=300
    )
    barra_progreso.set(0)
    barra_progreso.pack(side="left", padx=5, pady=5)

    etiqueta_progreso = ctk.CTkLabel(
        bottom_frame,
        text="Verificando: 0%"
    )
    etiqueta_progreso.pack(side="left", padx=5)

    # Frame aparte para "Conectado" / "Sin conexión"
    estado_frame = ctk.CTkFrame(ventana)
    estado_frame.pack(fill="x", expand=False, pady=(0, 10))

    si_label = ctk.CTkLabel(
        master=estado_frame,
        text="Conectado",
        fg_color="green",
        text_color="white",
        corner_radius=15
    )
    si_label.pack(side="left", padx=10, pady=5)

    no_label = ctk.CTkLabel(
        master=estado_frame,
        text="Sin conexión",
        fg_color="red",
        text_color="white",
        corner_radius=15
    )
    no_label.pack(side="left", padx=10, pady=5)

    # Definir routers para verificación (Telnet)
    global routers
    routers = [
        {"ip": "192.169.1.2", "username": "cisco", "password": "cisco", "nombre": "R2"},
        {"ip": "192.169.1.3", "username": "cisco", "password": "cisco", "nombre": "R3"},
        {"ip": "192.169.1.4", "username": "cisco", "password": "cisco", "nombre": "R4"},
        {"ip": "192.169.1.5", "username": "cisco", "password": "cisco", "nombre": "R5"},
        {"ip": "192.168.1.1", "username": "cisco", "password": "cisco", "nombre": "R1"},
    ]

    # Definir todos los dispositivos
    global devices
    devices = [
        # Routers
        {"nombre": "R1", "orig_x": 100, "orig_y": 200, "IP": "192.168.1.1", "tipo": "router"},
        {"nombre": "R2", "orig_x": 400, "orig_y": 200, "IP": "192.169.1.2", "tipo": "router"},
        {"nombre": "R3", "orig_x": 700, "orig_y": 200, "IP": "192.169.1.3", "tipo": "router"},
        {"nombre": "R4", "orig_x": 400, "orig_y": 400, "IP": "192.169.1.4", "tipo": "router"},
        {"nombre": "R5", "orig_x": 700, "orig_y": 400, "IP": "192.169.1.5", "tipo": "router"},
        
        # Switches
        {"nombre": "Switch1", "orig_x": 100, "orig_y": 300, "IP": "192.168.100.1", "tipo": "switch"},
        
        # PCs
        {"nombre": "PC12", "orig_x": 300, "orig_y": 100, "IP": "192.168.105.11", "tipo": "pc"},
        {"nombre": "PC11", "orig_x": 400, "orig_y": 100, "IP": "192.168.106.11", "tipo": "pc"},
        {"nombre": "PC10", "orig_x": 500, "orig_y": 100, "IP": "192.168.107.11", "tipo": "pc"},
        {"nombre": "PC9", "orig_x": 600, "orig_y": 100, "IP": "192.168.108.11", "tipo": "pc"},
        {"nombre": "PC8", "orig_x": 700, "orig_y": 100, "IP": "192.168.109.11", "tipo": "pc"},
        {"nombre": "PC7", "orig_x": 800, "orig_y": 100, "IP": "192.168.110.11", "tipo": "pc"},
        {"nombre": "PC1", "orig_x": 300, "orig_y": 500, "IP": "192.168.116.11", "tipo": "pc"},
        {"nombre": "PC2", "orig_x": 400, "orig_y": 500, "IP": "192.168.115.11", "tipo": "pc"},
        {"nombre": "PC3", "orig_x": 500, "orig_y": 500, "IP": "192.168.114.11", "tipo": "pc"},
        {"nombre": "PC4", "orig_x": 600, "orig_y": 500, "IP": "192.168.113.11", "tipo": "pc"},
        {"nombre": "PC5", "orig_x": 700, "orig_y": 500, "IP": "192.168.112.11", "tipo": "pc"},
        {"nombre": "PC6", "orig_x": 800, "orig_y": 500, "IP": "192.168.111.11", "tipo": "pc"},
        
        # VM Ubuntu
        {"nombre": "Ubuntu20.04VM-1", "orig_x": 100, "orig_y": 400, "IP": "192.168.100.11", "tipo": "vm"},
    ]

    # Cargar imágenes
    global imagen_router, imagen_switch, imagen_pc, imagen_vm

    try:
        imagen_router = tk.PhotoImage(file="enrutador.png").subsample(6)
        imagen_switch = tk.PhotoImage(file="switch.png").subsample(6)
        imagen_pc = tk.PhotoImage(file="computadora.png").subsample(5)
        imagen_vm = tk.PhotoImage(file="ubuntu.png").subsample(5)
    except Exception as e:
        messagebox.showerror("Error de carga de imágenes", f"No se pudieron cargar las imágenes: {e}")
        return

    # Definir la topología y calcular bounding box
    global min_x, max_x, min_y, max_y

    min_x = float('inf')
    max_x = float('-inf')
    min_y = float('inf')
    max_y = float('-inf')

    for device in devices:
        if device["tipo"] in ["pc", "vm"]:
            w_img = imagen_pc.width()
            h_img = imagen_pc.height()
        elif device["tipo"] == "switch":
            w_img = imagen_switch.width()
            h_img = imagen_switch.height()
        else:
            w_img = imagen_router.width()
            h_img = imagen_router.height()

        left = device["orig_x"] - w_img // 2
        right = device["orig_x"] + w_img // 2
        top = device["orig_y"] - h_img // 2
        bottom = device["orig_y"] + h_img // 2

        if left < min_x:
            min_x = left
        if right > max_x:
            max_x = right
        if top < min_y:
            min_y = top
        if bottom > max_y:
            max_y = bottom

    # Dibujar la topología inicialmente (usando after para asegurar que la ventana esté lista)
    def iniciar_dibujo():
        draw_topologia_escalada(lienzo.winfo_width(), lienzo.winfo_height())

    ventana.after(100, iniciar_dibujo)

    # Iniciar loop
    ventana.mainloop()

# ==================
#   Ejecutar la Aplicación
# ==================

if __name__ == "__main__":
    main()
