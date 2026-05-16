"""
procesador_salud.py

Recibe datos del simulador Arduino, evalúa alertas médicas y levanta una web.

Rutas disponibles:
- /estado  -> JSON con estado actual
- /qr      -> página con código QR
- /led     -> pantalla LED para abrir desde el celular
"""

import argparse
import html
import json
import os
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PORTADORES = {
    "001": "Carlos Mendoza",
    "002": "Ana Torres",
    "003": "Miguel Soto",
    "004": "Persona Sana",
}


ultimo_estado = {
    "estado": "sin_datos",
    "nivel": "NORMAL",
    "nivel_valor": 0,
    "portador": "Esperando datos",
    "resumen": "Esperando datos del brazalete...",
    "alertas": [],
    "datos_raw": {},
}


def obtener_ip_lan():
    """
    Intenta obtener la IP local del computador en la red Wi-Fi/LAN.
    Esa IP es la que debería abrir el celular.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def evaluar_datos(datos):
    sensores = datos.get("sensores", {})
    id_portador = datos.get("id_portador", "001")
    portador = PORTADORES.get(id_portador, "Portador desconocido")

    alertas = []
    nivel_global = 0

    def agregar_alerta(parametro, valor, nivel, mensaje):
        nonlocal nivel_global
        nivel_global = max(nivel_global, nivel)
        alertas.append({
            "parametro": parametro,
            "valor": valor,
            "nivel": ["NORMAL", "PRECAUCION", "ALERTA", "CRITICO"][nivel],
            "mensaje": mensaje,
        })

    pulso = sensores.get("pulso_bpm")
    temp = sensores.get("temperatura_c")
    sist = sensores.get("presion_sistolica")
    diast = sensores.get("presion_diastolica")
    spo2 = sensores.get("spo2_porcentaje")
    glucosa = sensores.get("glucosa_mgdl")

    if pulso is not None:
        if pulso >= 140 or pulso <= 45:
            agregar_alerta("pulso_bpm", pulso, 3, f"🔴 Pulso crítico: {pulso} bpm")
        elif pulso >= 120 or pulso <= 55:
            agregar_alerta("pulso_bpm", pulso, 2, f"🔶 Pulso en alerta: {pulso} bpm")
        elif pulso >= 100 or pulso <= 60:
            agregar_alerta("pulso_bpm", pulso, 1, f"⚠ Pulso fuera de rango ideal: {pulso} bpm")

    if temp is not None:
        if temp >= 39.0 or temp <= 35.0:
            agregar_alerta("temperatura_c", temp, 3, f"🔴 Temperatura crítica: {temp} °C")
        elif temp >= 38.0:
            agregar_alerta("temperatura_c", temp, 2, f"🔶 Fiebre: {temp} °C")
        elif temp >= 37.5:
            agregar_alerta("temperatura_c", temp, 1, f"⚠ Temperatura elevada: {temp} °C")

    if sist is not None:
        if sist >= 180:
            agregar_alerta("presion_sistolica", sist, 3, f"🔴 Presión sistólica crítica: {sist} mmHg")
        elif sist >= 160:
            agregar_alerta("presion_sistolica", sist, 2, f"🔶 Presión sistólica alta: {sist} mmHg")
        elif sist >= 140:
            agregar_alerta("presion_sistolica", sist, 1, f"⚠ Presión sistólica elevada: {sist} mmHg")

    if diast is not None:
        if diast >= 115:
            agregar_alerta("presion_diastolica", diast, 3, f"🔴 Presión diastólica crítica: {diast} mmHg")
        elif diast >= 100:
            agregar_alerta("presion_diastolica", diast, 2, f"🔶 Presión diastólica alta: {diast} mmHg")
        elif diast >= 90:
            agregar_alerta("presion_diastolica", diast, 1, f"⚠ Presión diastólica elevada: {diast} mmHg")

    if spo2 is not None:
        if spo2 <= 88:
            agregar_alerta("spo2_porcentaje", spo2, 3, f"🔴 Saturación crítica: {spo2}%")
        elif spo2 <= 92:
            agregar_alerta("spo2_porcentaje", spo2, 2, f"🔶 Saturación baja: {spo2}%")
        elif spo2 <= 95:
            agregar_alerta("spo2_porcentaje", spo2, 1, f"⚠ Saturación en observación: {spo2}%")

    if glucosa is not None:
        if glucosa >= 250 or glucosa <= 55:
            agregar_alerta("glucosa_mgdl", glucosa, 3, f"🔴 Glucosa crítica: {glucosa} mg/dL")
        elif glucosa >= 180:
            agregar_alerta("glucosa_mgdl", glucosa, 2, f"🔶 Glucosa alta: {glucosa} mg/dL")
        elif glucosa >= 140 or glucosa <= 70:
            agregar_alerta("glucosa_mgdl", glucosa, 1, f"⚠ Glucosa fuera de rango ideal: {glucosa} mg/dL")

    niveles = ["NORMAL", "PRECAUCION", "ALERTA", "CRITICO"]

    if nivel_global == 0:
        resumen = f"✅ {portador}: parámetros normales."
    elif nivel_global == 1:
        resumen = f"⚠ {portador}: revisar parámetros."
    elif nivel_global == 2:
        resumen = f"🔶 {portador}: alerta médica."
    else:
        resumen = f"🔴 {portador}: emergencia médica."

    return {
        "estado": "activo",
        "nivel": niveles[nivel_global],
        "nivel_valor": nivel_global,
        "portador": portador,
        "resumen": resumen,
        "alertas": alertas,
        "timestamp": time.time(),
        "datos_raw": datos,
    }


class ReceptorArduino:
    def __init__(self, host="127.0.0.1", port=9000):
        self.host = host
        self.port = port
        self.running = False

    def iniciar(self):
        self.running = True
        hilo = threading.Thread(target=self.loop_recepcion, daemon=True)
        hilo.start()

    def loop_recepcion(self):
        global ultimo_estado

        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((self.host, self.port))
                print(f"[PROCESADOR] Conectado al simulador en {self.host}:{self.port}")

                buffer = ""

                while self.running:
                    chunk = sock.recv(4096).decode("utf-8")
                    if not chunk:
                        break

                    buffer += chunk

                    while "\n" in buffer:
                        linea, buffer = buffer.split("\n", 1)
                        linea = linea.strip()

                        if linea:
                            datos = json.loads(linea)
                            ultimo_estado = evaluar_datos(datos)
                            print(f"[PROCESADOR] {ultimo_estado['resumen']}")

            except ConnectionRefusedError:
                print("[PROCESADOR] Esperando al simulador Arduino...")
                time.sleep(2)

            except Exception as error:
                print(f"[PROCESADOR] Error: {error}")
                time.sleep(2)


def enviar_comando(host, port, comando):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    sock.sendall(json.dumps(comando).encode("utf-8"))
    respuesta = sock.recv(4096).decode("utf-8")
    sock.close()
    return json.loads(respuesta)


def html_led():
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Panel LED — Alertas Médicas</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background: #050709;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      font-family: 'Courier New', monospace;
    }

    #screen {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      transition: background 0.6s;
      position: relative;
      padding: 40px 24px;
    }

    #standby {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 14px;
      transition: opacity 0.4s;
    }

    #standby-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #1a2a1a;
      animation: standby-blink 4s ease-in-out infinite;
    }

    @keyframes standby-blink {
      0%,100% { opacity: 0.3; }
      50% { opacity: 1; }
    }

    #standby-txt {
      font-size: 11px;
      letter-spacing: 0.2em;
      color: #1c2e1c;
      text-transform: uppercase;
    }

    #alerta-content {
      display: none;
      flex-direction: column;
      align-items: center;
      gap: 28px;
      width: 100%;
      max-width: 640px;
    }

    #nivel-banner {
      font-size: 56px;
      font-weight: bold;
      letter-spacing: 0.24em;
      text-transform: uppercase;
      text-align: center;
    }

    #portador-bloque {
      text-align: center;
    }

    #portador-nombre {
      font-size: 18px;
      letter-spacing: 0.1em;
    }

    #portador-cond {
      font-size: 12px;
      letter-spacing: 0.06em;
      margin-top: 5px;
      opacity: 0.5;
    }

    .div-line {
      height: 1px;
      width: 100px;
      opacity: 0.2;
    }

    #params-lista {
      display: flex;
      flex-direction: column;
      gap: 8px;
      width: 100%;
    }

    .param-row {
      display: grid;
      grid-template-columns: 180px 80px 1fr;
      align-items: center;
      gap: 14px;
      padding: 12px 16px;
      border-radius: 5px;
      border-left: 3px solid transparent;
    }

    .param-row.p1 {
      border-left-color: #b8860b;
      background: rgba(184,134,11,0.07);
    }

    .param-row.p2 {
      border-left-color: #c0531a;
      background: rgba(192,83,26,0.08);
    }

    .param-row.p3 {
      border-left-color: #b81c1c;
      background: rgba(184,28,28,0.1);
    }

    .p-nombre {
      font-size: 12px;
      letter-spacing: 0.08em;
      opacity: 0.65;
      text-transform: uppercase;
    }

    .p-valor {
      font-size: 22px;
      font-weight: bold;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }

    .p-unit {
      font-size: 11px;
      opacity: 0.45;
      font-weight: normal;
      margin-left: 2px;
    }

    .p-desc {
      font-size: 12px;
      opacity: 0.6;
      letter-spacing: 0.03em;
    }

    .col-1 { color: #f0c040; }
    .col-2 { color: #f07040; }
    .col-3 { color: #f03030; }

    #ts {
      font-size: 11px;
      letter-spacing: 0.14em;
      opacity: 0.25;
      text-transform: uppercase;
    }

    .anim-precaucion {
      animation: blink-slow 2.5s ease-in-out infinite;
    }

    .anim-alerta {
      animation: blink-mid 1s ease-in-out infinite;
    }

    .anim-critico {
      animation: blink-fast 0.45s ease-in-out infinite;
    }

    @keyframes blink-slow {
      0%,100% { opacity: 1; }
      50% { opacity: 0.5; }
    }

    @keyframes blink-mid {
      0%,100% { opacity: 1; }
      50% { opacity: 0.3; }
    }

    @keyframes blink-fast {
      0%,100% { opacity: 1; }
      50% { opacity: 0.1; }
    }

    #ctrl-modo {
      position: absolute;
      bottom: 16px;
      right: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      align-items: flex-end;
    }

    #ctrl-portador {
      position: absolute;
      bottom: 16px;
      left: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .ctrl-label {
      font-size: 9px;
      color: #1e3a1e;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    .btn-row {
      display: flex;
      gap: 4px;
    }

    .cb {
      padding: 4px 10px;
      border: 1px solid #1a281a;
      border-radius: 4px;
      background: transparent;
      color: #1e3a1e;
      font-family: 'Courier New', monospace;
      font-size: 10px;
      letter-spacing: 0.06em;
      cursor: pointer;
      transition: all 0.15s;
    }

    .cb:hover {
      border-color: #2a4a2a;
      color: #2a5a2a;
    }

    .cb.sel-n {
      border-color: #22c55e;
      color: #22c55e;
    }

    .cb.sel-a {
      border-color: #f97316;
      color: #f97316;
    }

    .cb.sel-c {
      border-color: #ef4444;
      color: #ef4444;
    }

    .cb.sel-p {
      border-color: #818cf8;
      color: #818cf8;
    }

    #conexion {
      position: absolute;
      top: 16px;
      right: 16px;
      font-size: 10px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #1e3a1e;
    }

    @media (max-width: 640px) {
      #screen {
        padding: 32px 14px 86px;
      }

      #nivel-banner {
        font-size: 38px;
        letter-spacing: 0.16em;
      }

      .param-row {
        grid-template-columns: 1fr 82px;
        gap: 6px 10px;
      }

      .p-desc {
        grid-column: 1 / -1;
      }

      #ctrl-modo {
        right: 12px;
        bottom: 12px;
      }

      #ctrl-portador {
        left: 12px;
        bottom: 12px;
      }

      .cb {
        padding: 5px 8px;
        font-size: 9px;
      }
    }
  </style>
</head>

<body>
<div id="screen">

  <div id="conexion">Conectando...</div>

  <div id="standby">
    <div id="standby-dot"></div>
    <div id="standby-txt">Sistema activo — sin alertas</div>
  </div>

  <div id="alerta-content">
    <div id="nivel-banner"></div>
    <div id="portador-bloque">
      <div id="portador-nombre"></div>
      <div id="portador-cond"></div>
    </div>
    <div class="div-line" id="divider"></div>
    <div id="params-lista"></div>
    <div id="ts"></div>
  </div>

  <div id="ctrl-modo">
    <div class="ctrl-label">Simular señal</div>
    <div class="btn-row">
      <button class="cb sel-n" id="mb-n" onclick="setModo('normal')">Normal</button>
      <button class="cb" id="mb-a" onclick="setModo('alerta')">Alerta</button>
      <button class="cb" id="mb-c" onclick="setModo('critico')">Crítico</button>
    </div>
  </div>

  <div id="ctrl-portador">
    <div class="ctrl-label">Portador</div>
    <div class="btn-row">
      <button class="cb sel-p" id="pb-001" onclick="selPortador('001')">001</button>
      <button class="cb" id="pb-002" onclick="selPortador('002')">002</button>
      <button class="cb" id="pb-003" onclick="selPortador('003')">003</button>
      <button class="cb" id="pb-004" onclick="selPortador('004')">004</button>
    </div>
  </div>

</div>

<script>
const API_BASE = window.location.origin;

const PORTADORES = {
  "001": { nombre:"Carlos Mendoza", cond:"Hipertensión · Diabetes tipo 2" },
  "002": { nombre:"Ana Torres",     cond:"Asma" },
  "003": { nombre:"Miguel Soto",    cond:"Arritmia · Hipertensión" },
  "004": { nombre:"Roberto López",  cond:"Sin condiciones crónicas" }
};

const PLABELS = {
  pulso_bpm:           { label:"Pulso cardíaco",       unit:"bpm" },
  temperatura_c:       { label:"Temperatura",          unit:"°C" },
  presion_sistolica:   { label:"Presión sistólica",    unit:"mmHg" },
  presion_diastolica:  { label:"Presión diastólica",   unit:"mmHg" },
  spo2_porcentaje:     { label:"Saturación O₂",        unit:"%" },
  glucosa_mgdl:        { label:"Glucosa",              unit:"mg/dL" },
  riesgo_acv:          { label:"Riesgo ACV",           unit:"score" },
  riesgo_paro_cardiaco:{ label:"Riesgo paro cardíaco", unit:"score" }
};

let portadorActivo = "001";
let modoLocal = {
  "001": "normal",
  "002": "normal",
  "003": "normal",
  "004": "normal"
};
let ultimosDatosReales = null;

function generarDatos(id) {
  const r = (a,b) => a + Math.random() * (b - a);
  const modo = modoLocal[id];

  if (id === "002") {
    let spo2, pulso, temp, sist, diast, glucosa;

    if (modo === "normal") {
      spo2 = r(96,99); pulso = r(70,90); temp = r(36.2,37.0);
      sist = r(108,122); diast = r(68,80); glucosa = r(85,110);
    } else if (modo === "alerta") {
      spo2 = r(91,94); pulso = r(95,115); temp = r(37.2,38.2);
      sist = r(118,135); diast = r(75,90); glucosa = r(90,120);
    } else {
      spo2 = r(85,90); pulso = r(120,145); temp = r(38.5,39.8);
      sist = r(135,155); diast = r(88,100); glucosa = r(95,130);
    }

    const nivel = spo2 < 90 ? "CRITICO" : spo2 < 93 ? "ALERTA" : spo2 < 95 ? "PRECAUCION" : "NORMAL";
    const alertas = [];

    if (spo2 < 90) {
      alertas.push({p:"spo2_porcentaje", v:spo2, n:3, desc:"Hipoxemia severa — riesgo respiratorio inmediato"});
    } else if (spo2 < 93) {
      alertas.push({p:"spo2_porcentaje", v:spo2, n:2, desc:"Hipoxemia moderada"});
    } else if (spo2 < 95) {
      alertas.push({p:"spo2_porcentaje", v:spo2, n:1, desc:"Por debajo del umbral seguro para asma"});
    }

    if (pulso > 120) {
      alertas.push({p:"pulso_bpm", v:pulso, n:2, desc:"Taquicardia compensatoria"});
    }

    if (temp > 38.5) {
      alertas.push({p:"temperatura_c", v:temp, n:2, desc:"Fiebre — posible crisis asmática"});
    }

    return { nivel, alertas };
  }

  if (id === "003") {
    let sist, diast, pulso, temp, spo2, glucosa;

    if (modo === "normal") {
      sist = r(128,142); diast = r(82,92); pulso = r(68,88);
      temp = r(36.0,36.9); spo2 = r(95,98); glucosa = r(90,115);
    } else if (modo === "alerta") {
      sist = r(155,170); diast = r(98,110); pulso = r(110,130);
      temp = r(36.5,37.5); spo2 = r(93,96); glucosa = r(100,130);
    } else {
      sist = r(175,200); diast = r(112,130); pulso = r(140,165);
      temp = r(37.0,38.5); spo2 = r(89,93); glucosa = r(110,150);
    }

    const ord = ["NORMAL","PRECAUCION","ALERTA","CRITICO"];
    const nPA = sist > 175 ? "CRITICO" : sist > 155 ? "ALERTA" : sist > 135 ? "PRECAUCION" : "NORMAL";
    const nP  = pulso > 140 ? "CRITICO" : pulso > 110 ? "ALERTA" : pulso > 90 ? "PRECAUCION" : "NORMAL";
    const nivel = ord[Math.max(ord.indexOf(nPA), ord.indexOf(nP))];

    const alertas = [];

    if (sist > 175) {
      alertas.push({p:"presion_sistolica", v:sist, n:3, desc:"Crisis hipertensiva — riesgo de ACV"});
    } else if (sist > 155) {
      alertas.push({p:"presion_sistolica", v:sist, n:2, desc:"Hipertensión severa"});
    } else if (sist > 135) {
      alertas.push({p:"presion_sistolica", v:sist, n:1, desc:"Elevada para perfil de arritmia"});
    }

    if (diast > 110) {
      alertas.push({p:"presion_diastolica", v:diast, n:3, desc:"Diastólica crítica"});
    }

    if (pulso > 140) {
      alertas.push({p:"pulso_bpm", v:pulso, n:3, desc:"Arritmia severa — riesgo de paro"});
    } else if (pulso > 110) {
      alertas.push({p:"pulso_bpm", v:pulso, n:2, desc:"Taquiarritmia activa"});
    } else if (pulso > 90) {
      alertas.push({p:"pulso_bpm", v:pulso, n:1, desc:"Elevado para perfil de arritmia"});
    }

    if (spo2 < 90) {
      alertas.push({p:"spo2_porcentaje", v:spo2, n:3, desc:"Hipoxemia severa"});
    }

    return { nivel, alertas };
  }

  if (id === "004") {
    let pulso, temp, sist, diast, spo2, glucosa, nivel, alertas = [];

    if (modo === "normal") {
      pulso = r(62,80); temp = r(36.2,36.8); sist = r(108,120);
      diast = r(68,78); spo2 = r(97,99); glucosa = r(82,100);
      nivel = "NORMAL";
    } else if (modo === "alerta") {
      pulso = r(105,125); temp = r(37.9,38.8); sist = r(148,162);
      diast = r(94,106); spo2 = r(92,95); glucosa = r(60,68);
      nivel = "ALERTA";

      alertas = [
        {p:"pulso_bpm", v:pulso, n:2, desc:"Taquicardia"},
        {p:"temperatura_c", v:temp, n:2, desc:"Fiebre moderada"},
        {p:"glucosa_mgdl", v:glucosa, n:2, desc:"Hipoglucemia moderada"}
      ];
    } else {
      pulso = r(148,170); temp = r(39.8,41.0); sist = r(172,195);
      diast = r(110,128); spo2 = r(84,89); glucosa = r(48,56);
      nivel = "CRITICO";

      alertas = [
        {p:"pulso_bpm", v:pulso, n:3, desc:"Taquicardia severa"},
        {p:"temperatura_c", v:temp, n:3, desc:"Fiebre severa — hipertermia"},
        {p:"spo2_porcentaje", v:spo2, n:3, desc:"Hipoxemia severa"},
        {p:"glucosa_mgdl", v:glucosa, n:3, desc:"Hipoglucemia severa — emergencia"}
      ];
    }

    return { nivel, alertas };
  }

  return { nivel:"NORMAL", alertas:[] };
}

function normalizarNivel(nivel) {
  if (nivel === "CRITICO") return "CRITICO";
  if (nivel === "ALERTA") return "ALERTA";
  if (nivel === "PRECAUCION") return "PRECAUCION";
  return "NORMAL";
}

function render(nivel, alertas, portadorId) {
  nivel = normalizarNivel(nivel);

  const screen  = document.getElementById("screen");
  const standby = document.getElementById("standby");
  const content = document.getElementById("alerta-content");
  const p = PORTADORES[portadorId] || PORTADORES["001"];

  if (nivel === "NORMAL" || !alertas || alertas.length === 0) {
    screen.style.background = "#050709";
    standby.style.display = "flex";
    content.style.display = "none";
    return;
  }

  standby.style.display = "none";
  content.style.display = "flex";

  const cfg = {
    PRECAUCION: {
      bg: "#110e00",
      color: "#f0c040",
      anim: "anim-precaucion",
      label: "PRECAUCIÓN"
    },
    ALERTA: {
      bg: "#110500",
      color: "#f07040",
      anim: "anim-alerta",
      label: "ALERTA"
    },
    CRITICO: {
      bg: "#0f0000",
      color: "#f03030",
      anim: "anim-critico",
      label: "EMERGENCIA"
    }
  }[nivel] || {
    bg: "#050709",
    color: "#aaa",
    anim: "",
    label: nivel
  };

  screen.style.background = cfg.bg;

  const banner = document.getElementById("nivel-banner");
  banner.className = cfg.anim;
  banner.textContent = cfg.label;
  banner.style.color = cfg.color;

  document.getElementById("portador-nombre").textContent = p.nombre;
  document.getElementById("portador-nombre").style.color = cfg.color;
  document.getElementById("portador-cond").textContent = p.cond;
  document.getElementById("portador-cond").style.color = cfg.color;
  document.getElementById("divider").style.background = cfg.color;

  document.getElementById("params-lista").innerHTML = alertas.map(a => {
    const meta = PLABELS[a.p] || { label:a.p, unit:"" };
    const v = parseFloat(a.v);
    const vs = Number.isNaN(v)
      ? a.v
      : meta.unit === "°C"
        ? v.toFixed(1)
        : Math.round(v);

    return `
      <div class="param-row p${a.n}">
        <div class="p-nombre col-${a.n}">${meta.label}</div>
        <div class="p-valor col-${a.n}">
          ${vs}<span class="p-unit">${meta.unit}</span>
        </div>
        <div class="p-desc col-${a.n}">${a.desc}</div>
      </div>
    `;
  }).join("");

  const ts = document.getElementById("ts");
  ts.style.color = cfg.color;
  ts.textContent = new Date().toLocaleTimeString("es-CL");
}

async function pollPython() {
  try {
    const res = await fetch(`${API_BASE}/estado`);
    const data = await res.json();

    if (data && data.estado !== "sin_datos") {
      ultimosDatosReales = data;

      if (portadorActivo !== "001") {
        return;
      }

      const alertasConv = (data.alertas || []).map(a => {
        const n = {
          CRITICO: 3,
          ALERTA: 2,
          PRECAUCION: 1
        }[a.nivel] || 1;

        const desc = (a.mensaje || "")
          .replace(/^[^\\w]*(CRÍTICO|CRITICO|ALERTA|PRECAUCIÓN|PRECAUCION)?:?\\s*[^—]*—\\s*/i, "")
          .trim();

        return {
          p: a.parametro,
          v: a.valor,
          n,
          desc: desc || a.mensaje || "Requiere atención"
        };
      });

      render(data.nivel, alertasConv, "001");
    }
  } catch (error) {
    document.getElementById("conexion").textContent = "Sin conexión";
    document.getElementById("conexion").style.color = "#ef4444";
  }
}

function cicloLocal() {
  if (portadorActivo === "001") {
    return;
  }

  const datos = generarDatos(portadorActivo);
  if (datos) {
    render(datos.nivel, datos.alertas, portadorActivo);
  }
}

setInterval(cicloLocal, 4000);
setInterval(pollPython, 2000);

function setModo(modo) {
  modoLocal[portadorActivo] = modo;

  document.getElementById("mb-n").className = "cb" + (modo === "normal" ? " sel-n" : "");
  document.getElementById("mb-a").className = "cb" + (modo === "alerta" ? " sel-a" : "");
  document.getElementById("mb-c").className = "cb" + (modo === "critico" ? " sel-c" : "");

  if (portadorActivo === "001") {
    fetch(`${API_BASE}/cambiar_modo`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ modo })
    }).catch(() => {});
  } else {
    const datos = generarDatos(portadorActivo);
    if (datos) {
      render(datos.nivel, datos.alertas, portadorActivo);
    }
  }
}

function selPortador(id) {
  portadorActivo = id;

  ["001","002","003","004"].forEach(i => {
    document.getElementById(`pb-${i}`).className = "cb" + (i === id ? " sel-p" : "");
  });

  const modo = modoLocal[id];

  document.getElementById("mb-n").className = "cb" + (modo === "normal" ? " sel-n" : "");
  document.getElementById("mb-a").className = "cb" + (modo === "alerta" ? " sel-a" : "");
  document.getElementById("mb-c").className = "cb" + (modo === "critico" ? " sel-c" : "");

  if (id === "001" && ultimosDatosReales) {
    const alertasConv = (ultimosDatosReales.alertas || []).map(a => {
      const n = {
        CRITICO: 3,
        ALERTA: 2,
        PRECAUCION: 1
      }[a.nivel] || 1;

      const desc = (a.mensaje || "")
        .replace(/^[^\\w]*(CRÍTICO|CRITICO|ALERTA|PRECAUCIÓN|PRECAUCION)?:?\\s*[^—]*—\\s*/i, "")
        .trim();

      return {
        p: a.parametro,
        v: a.valor,
        n,
        desc: desc || a.mensaje || "Requiere atención"
      };
    });

    render(ultimosDatosReales.nivel, alertasConv, "001");
  } else {
    const datos = generarDatos(id);
    if (datos) {
      render(datos.nivel, datos.alertas, id);
    }
  }
}

pollPython();
cicloLocal();
</script>
</body>
</html>"""


def html_qr(base_url):
    led_url = f"{base_url}/led"
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data=" + urllib.parse.quote(led_url)

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>QR Pantalla LED SAVE</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #07111f;
      color: white;
      font-family: Arial, sans-serif;
      text-align: center;
    }}

    main {{
      width: min(92vw, 560px);
      padding: 28px;
      background: #0f172a;
      border-radius: 22px;
      box-shadow: 0 20px 60px rgba(0,0,0,.55);
    }}

    img {{
      width: 320px;
      max-width: 90%;
      background: white;
      padding: 12px;
      border-radius: 18px;
    }}

    a {{
      color: #67e8f9;
      word-break: break-all;
    }}

    .url {{
      margin-top: 18px;
      background: rgba(255,255,255,.08);
      padding: 12px;
      border-radius: 12px;
    }}

    .nota {{
      color: #cbd5e1;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <main>
    <h1>QR para pantalla LED</h1>
    <p class="nota">Escanea este código con el celular conectado a la misma red Wi-Fi que este computador.</p>

    <img src="{html.escape(qr_url)}" alt="QR pantalla LED">

    <div class="url">
      <strong>URL LED:</strong><br>
      <a href="{html.escape(led_url)}">{html.escape(led_url)}</a>
    </div>

    <p class="nota">Si el QR no abre, escribe manualmente la URL en el navegador del celular.</p>
  </main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    command_host = "127.0.0.1"
    command_port = 9001
    base_url = "http://127.0.0.1:8080"

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/qr":
            self.responder_html(html_qr(self.base_url))

        elif path == "/led":
            self.responder_html(html_led())

        elif path == "/estado":
            self.responder_json(ultimo_estado)

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/cambiar_modo":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                modo = body.get("modo", "normal")

                respuesta = enviar_comando(
                    self.command_host,
                    self.command_port,
                    {"comando": "set_modo", "modo": modo},
                )

                self.responder_json(respuesta)

            except Exception as error:
                self.responder_json({"ok": False, "error": str(error)})

        else:
            self.send_response(404)
            self.end_headers()

    def responder_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def responder_html(self, content):
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Procesador SAVE con pantalla LED y QR")
    parser.add_argument("--arduino-host", default="127.0.0.1")
    parser.add_argument("--arduino-port", type=int, default=9000)
    parser.add_argument("--command-host", default="127.0.0.1")
    parser.add_argument("--command-port", type=int, default=9001)
    parser.add_argument("--api-host", default="0.0.0.0")
    parser.add_argument("--api-port", type=int, default=8080)
    args = parser.parse_args()

    receptor = ReceptorArduino(args.arduino_host, args.arduino_port)
    receptor.iniciar()

    ip_lan = os.environ.get("SAVE_PUBLIC_HOST", obtener_ip_lan())
    base_url = f"http://{ip_lan}:{args.api_port}"

    Handler.command_host = args.command_host
    Handler.command_port = args.command_port
    Handler.base_url = base_url

    server = ThreadingHTTPServer((args.api_host, args.api_port), Handler)

    print("=" * 60)
    print("PROCESADOR SAVE")
    print("=" * 60)
    print(f"Abre en este computador: http://localhost:{args.api_port}/qr")
    print(f"Abre en celular / QR    : {base_url}/qr")
    print(f"Pantalla LED directa    : {base_url}/led")
    print("=" * 60)
    print("Deja esta ventana abierta.")
    print("Presiona Ctrl+C para detener.")
    print("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[PROCESADOR] Detenido.")