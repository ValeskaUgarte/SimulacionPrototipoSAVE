"""
Procesador de Salud - Brazalete de Monitoreo
Recibe datos del Arduino, evalúa parámetros según el perfil del portador
y determina el nivel de alerta correspondiente
"""

import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

class NivelAlerta(Enum):
    NORMAL = 0
    PRECAUCION = 1
    ALERTA = 2
    CRITICO = 3

# ─── Perfiles de portadores (incluyendo persona sana) ──────────────────────────
PERFILES_PORTADORES = {
    "001": {
        "nombre": "Carlos Mendoza",
        "edad": 58,
        "peso_kg": 85,
        "condiciones": ["hipertension", "diabetes_tipo2"],
        "medicamentos": ["metformina 850mg", "losartan 50mg"],
        "contacto_emergencia": "+56912345678",
        "umbrales_personalizados": {
            "presion_sistolica": {"precaucion": 140, "alerta": 160, "critico": 180},
            "presion_diastolica": {"precaucion": 90, "alerta": 100, "critico": 115},
            "glucosa_mgdl": {"precaucion": 130, "alerta": 180, "critico": 250},
        }
    },
    "002": {
        "nombre": "Ana Torres",
        "edad": 34,
        "peso_kg": 62,
        "condiciones": ["asma"],
        "medicamentos": ["salbutamol 100mcg"],
        "contacto_emergencia": "+56987654321",
        "umbrales_personalizados": {
            "spo2_porcentaje": {"precaucion": 95, "alerta": 92, "critico": 90},
        }
    },
    "003": {
        "nombre": "Miguel Soto",
        "edad": 72,
        "peso_kg": 78,
        "condiciones": ["arritmia", "hipertension"],
        "medicamentos": ["amiodarona 200mg", "enalapril 10mg"],
        "contacto_emergencia": "+56911223344",
        "umbrales_personalizados": {
            "pulso_bpm": {"precaucion": 90, "alerta": 110, "critico": 130},
            "presion_sistolica": {"precaucion": 135, "alerta": 155, "critico": 175},
        }
    },
    "004": {
        "nombre": "Persona Sana",
        "edad": 30,
        "peso_kg": 70,
        "condiciones": [],
        "medicamentos": [],
        "contacto_emergencia": "+56999999999",
        "umbrales_personalizados": {}
    }
}

# ─── Umbrales ESTÁNDAR (persona sana promedio) ───────────────────────────────
UMBRALES_STANDARD = {
    "pulso_bpm": {
        "min_critico": 40, "min_alerta": 50, "min_precaucion": 60,
        "max_precaucion": 100, "max_alerta": 120, "max_critico": 150
    },
    "temperatura_c": {
        "min_critico": 34.0, "min_alerta": 35.0, "min_precaucion": 36.0,
        "max_precaucion": 37.5, "max_alerta": 38.5, "max_critico": 40.0
    },
    "presion_sistolica": {
        "max_precaucion": 130, "max_alerta": 150, "max_critico": 170
    },
    "presion_diastolica": {
        "max_precaucion": 85, "max_alerta": 95, "max_critico": 110
    },
    "spo2_porcentaje": {
        "min_precaucion": 95, "min_alerta": 92, "min_critico": 88
    },
    "glucosa_mgdl": {
        "min_precaucion": 70, "min_critico": 55,
        "max_precaucion": 140, "max_alerta": 200, "max_critico": 300
    }
}

# ─── Mensajes de alerta ───────────────────────────────────────────────────────
def generar_mensaje_alerta(parametro, valor, nivel, perfil, condiciones):
    mensajes = {
        "pulso_bpm": {
            NivelAlerta.PRECAUCION: {"default": f"⚠ Pulso {valor:.0f} bpm — Levemente elevado."},
            NivelAlerta.ALERTA: {"default": f"🔶 ALERTA: Pulso {valor:.0f} bpm — Taquicardia moderada."},
            NivelAlerta.CRITICO: {"default": f"🔴 CRÍTICO: Pulso {valor:.0f} bpm — Taquicardia severa."}
        },
        "temperatura_c": {
            NivelAlerta.PRECAUCION: {"default": f"⚠ Temperatura {valor:.1f}°C — Temperatura elevada."},
            NivelAlerta.ALERTA: {"default": f"🔶 ALERTA: Temperatura {valor:.1f}°C — Fiebre."},
            NivelAlerta.CRITICO: {"default": f"🔴 CRÍTICO: Temperatura {valor:.1f}°C — Fiebre severa."}
        },
        "presion_sistolica": {
            NivelAlerta.PRECAUCION: {"default": f"⚠ Presión {valor:.0f} mmHg — Presión arterial alta."},
            NivelAlerta.ALERTA: {"default": f"🔶 ALERTA: Presión {valor:.0f} mmHg — Hipertensión significativa."},
            NivelAlerta.CRITICO: {"default": f"🔴 CRÍTICO: Presión {valor:.0f} mmHg — Crisis hipertensiva."}
        },
        "spo2_porcentaje": {
            NivelAlerta.PRECAUCION: {"default": f"⚠ SpO2 {valor:.0f}% — Saturación baja."},
            NivelAlerta.ALERTA: {"default": f"🔶 ALERTA: SpO2 {valor:.0f}% — Hipoxemia moderada."},
            NivelAlerta.CRITICO: {"default": f"🔴 CRÍTICO: SpO2 {valor:.0f}% — Hipoxemia severa."}
        },
        "glucosa_mgdl": {
            NivelAlerta.PRECAUCION: {"default": f"⚠ Glucosa {valor:.0f} mg/dL — Nivel elevado."},
            NivelAlerta.ALERTA: {"default": f"🔶 ALERTA: Glucosa {valor:.0f} mg/dL — Hiperglucemia."},
            NivelAlerta.CRITICO: {"default": f"🔴 CRÍTICO: Glucosa {valor:.0f} mg/dL — Nivel peligroso."}
        }
    }
    
    if parametro not in mensajes or nivel not in mensajes[parametro]:
        return f"{parametro}: {valor} — {nivel.name}"
    
    return mensajes[parametro][nivel].get("default", f"{parametro}: {valor}")


@dataclass
class ResultadoEvaluacion:
    nivel_global: NivelAlerta = NivelAlerta.NORMAL
    alertas: list = field(default_factory=list)
    resumen: str = ""
    timestamp: float = field(default_factory=time.time)
    datos_raw: dict = field(default_factory=dict)
    portador_nombre: str = ""
    
class EvaluadorSalud:
    def __init__(self):
        self.historial = []
        self.max_historial = 50
        
    def evaluar(self, datos: dict) -> ResultadoEvaluacion:
        portador_id = datos.get("id_portador", "001")
        sensores = datos.get("sensores", {})
        
        perfil = PERFILES_PORTADORES.get(portador_id, {})
        condiciones = perfil.get("condiciones", [])
        umbrales_personalizados = perfil.get("umbrales_personalizados", {})
        
        resultado = ResultadoEvaluacion()
        resultado.datos_raw = datos
        resultado.portador_nombre = perfil.get("nombre", "Portador desconocido")
        
        alertas_encontradas = []
        
        # Evaluar parámetros individuales
        for parametro, valor in sensores.items():
            nivel = self._evaluar_parametro(parametro, valor, umbrales_personalizados)
            if nivel != NivelAlerta.NORMAL:
                mensaje = generar_mensaje_alerta(parametro, valor, nivel, perfil, condiciones)
                alertas_encontradas.append({
                    "parametro": parametro,
                    "valor": valor,
                    "nivel": nivel,
                    "mensaje": mensaje
                })
        
        # Evaluar riesgos combinados (ACV y paro cardíaco)
        alertas_riesgo = self.evaluar_riesgo_combinado(sensores, condiciones)
        alertas_encontradas.extend(alertas_riesgo)
        
        if alertas_encontradas:
            nivel_max = max(a["nivel"].value for a in alertas_encontradas)
            resultado.nivel_global = NivelAlerta(nivel_max)
            resultado.alertas = sorted(alertas_encontradas, key=lambda x: x["nivel"].value, reverse=True)
        
        resultado.resumen = self._generar_resumen(resultado, perfil)
        
        self.historial.append(resultado)
        if len(self.historial) > self.max_historial:
            self.historial.pop(0)
            
        return resultado
    
    def _evaluar_parametro(self, parametro, valor, umbrales_custom):
        if parametro in umbrales_custom:
            u = umbrales_custom[parametro]
            if valor >= u.get("critico", float('inf')):
                return NivelAlerta.CRITICO
            elif valor >= u.get("alerta", float('inf')):
                return NivelAlerta.ALERTA
            elif valor >= u.get("precaucion", float('inf')):
                return NivelAlerta.PRECAUCION
            return NivelAlerta.NORMAL
        
        if parametro not in UMBRALES_STANDARD:
            return NivelAlerta.NORMAL
            
        u = UMBRALES_STANDARD[parametro]
        
        if "max_critico" in u and valor >= u["max_critico"]:
            return NivelAlerta.CRITICO
        if "max_alerta" in u and valor >= u["max_alerta"]:
            return NivelAlerta.ALERTA
        if "max_precaucion" in u and valor >= u["max_precaucion"]:
            return NivelAlerta.PRECAUCION
        if "min_critico" in u and valor <= u["min_critico"]:
            return NivelAlerta.CRITICO
        if "min_alerta" in u and valor <= u["min_alerta"]:
            return NivelAlerta.ALERTA
        if "min_precaucion" in u and valor <= u["min_precaucion"]:
            return NivelAlerta.PRECAUCION
            
        return NivelAlerta.NORMAL
    
    def evaluar_riesgo_combinado(self, sensores, condiciones):
        alertas_extra = []
        s = sensores
        
        # Riesgo ACV
        score_acv = 0
        if s.get("presion_sistolica", 0) >= 160: score_acv += 3
        elif s.get("presion_sistolica", 0) >= 140: score_acv += 1
        if s.get("presion_diastolica", 0) >= 100: score_acv += 2
        if s.get("pulso_bpm", 0) > 110: score_acv += 1
        if s.get("glucosa_mgdl", 0) > 180: score_acv += 1
        if "hipertension" in condiciones: score_acv += 1

        if score_acv >= 5:
            alertas_extra.append({
                "parametro": "riesgo_acv",
                "valor": score_acv,
                "nivel": NivelAlerta.CRITICO,
                "mensaje": f"🔴 CRÍTICO: Riesgo de ACV detectado (score {score_acv}). EMERGENCIA."
            })
        elif score_acv >= 3:
            alertas_extra.append({
                "parametro": "riesgo_acv",
                "valor": score_acv,
                "nivel": NivelAlerta.ALERTA,
                "mensaje": f"🔶 ALERTA: Riesgo de ACV elevado (score {score_acv}). Contactar médico."
            })

        # Riesgo paro cardíaco
        score_paro = 0
        pulso = s.get("pulso_bpm", 0)
        if pulso > 150 or pulso < 40: score_paro += 3
        elif pulso > 130 or pulso < 50: score_paro += 1
        spo2 = s.get("spo2_porcentaje", 100)
        if spo2 < 88: score_paro += 3
        elif spo2 < 92: score_paro += 1
        if s.get("presion_sistolica", 0) < 90: score_paro += 3
        if "arritmia" in condiciones and pulso > 120: score_paro += 2

        if score_paro >= 5:
            alertas_extra.append({
                "parametro": "riesgo_paro_cardiaco",
                "valor": score_paro,
                "nivel": NivelAlerta.CRITICO,
                "mensaje": f"🔴 CRÍTICO: Riesgo de paro cardíaco (score {score_paro}). EMERGENCIA."
            })
        elif score_paro >= 3:
            alertas_extra.append({
                "parametro": "riesgo_paro_cardiaco",
                "valor": score_paro,
                "nivel": NivelAlerta.ALERTA,
                "mensaje": f"🔶 ALERTA: Riesgo cardíaco elevado (score {score_paro}). Atención urgente."
            })

        return alertas_extra
    
    def _generar_resumen(self, resultado: ResultadoEvaluacion, perfil: dict):
        nombre = resultado.portador_nombre
        nivel = resultado.nivel_global
        
        if nivel == NivelAlerta.NORMAL:
            return f"✅ {nombre}: Todos los parámetros normales."
        elif nivel == NivelAlerta.PRECAUCION:
            return f"⚠ {nombre}: {len(resultado.alertas)} parámetro(s) requieren atención."
        elif nivel == NivelAlerta.ALERTA:
            return f"🔶 {nombre}: ALERTA MÉDICA — Contactar médico."
        else:
            return f"🔴 {nombre}: EMERGENCIA MÉDICA."


# ─── Receptor de datos del Arduino ───────────────────────────────────────────
class ReceptorArduino:
    def __init__(self, host="localhost", port=9000, callback=None):
        self.host = host
        self.port = port
        self.callback = callback
        self.running = False
        self.evaluador = EvaluadorSalud()
        self.ultimo_resultado: Optional[ResultadoEvaluacion] = None
        self.hilo = None
        
    def start(self):
        self.running = True
        self.hilo = threading.Thread(target=self._loop_conexion, daemon=True)
        self.hilo.start()
        
    def stop(self):
        self.running = False
        
    def _loop_conexion(self):
        while self.running:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((self.host, self.port))
                print(f"[PYTHON] Conectado al Arduino en {self.host}:{self.port}")
                self._recibir_datos(sock)
            except ConnectionRefusedError:
                print("[PYTHON] Esperando Arduino...")
                time.sleep(3)
            except Exception as e:
                print(f"[PYTHON] Error: {e}")
                time.sleep(2)
                
    def _recibir_datos(self, sock):
        buffer = ""
        while self.running:
            try:
                chunk = sock.recv(1024).decode()
                if not chunk:
                    break
                buffer += chunk
                while "\n" in buffer:
                    linea, buffer = buffer.split("\n", 1)
                    linea = linea.strip()
                    if linea:
                        try:
                            datos = json.loads(linea)
                            resultado = self.evaluador.evaluar(datos)
                            self.ultimo_resultado = resultado
                            if self.callback:
                                self.callback(resultado)
                        except json.JSONDecodeError as e:
                            print(f"[PYTHON] JSON inválido: {e}")
            except Exception as e:
                print(f"[PYTHON] Error: {e}")
                break


# ─── Servidor HTTP ───────────────────────────────────────────────────────────
import http.server
import urllib.parse

class APIHandler(http.server.BaseHTTPRequestHandler):
    receptor = None
    
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        
        if path == "/estado":
            self._responder_json(self._get_estado())
        elif path == "/historial":
            self._responder_json(self._get_historial())
        elif path == "/portadores":
            self._responder_json(PERFILES_PORTADORES)
        else:
            self.send_response(404)
            self.end_headers()
            
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        
        if path == "/simular":
            datos_sim = body
            if self.receptor and self.receptor.evaluador:
                resultado = self.receptor.evaluador.evaluar(datos_sim)
                self.receptor.ultimo_resultado = resultado
                if self.receptor.callback:
                    self.receptor.callback(resultado)
            self._responder_json({"ok": True})
        
        elif path == "/cambiar_modo":
            modo = body.get("modo", "normal")
            print(f"[API] Cambiando modo a: {modo}")
            
            # Reenviar comando al simulador
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(("localhost", 9001))
                sock.send(json.dumps({"comando": "set_modo", "modo": modo}).encode())
                respuesta = json.loads(sock.recv(1024).decode())
                sock.close()
                self._responder_json({"ok": True, "modo": modo, "simulador": respuesta})
                print(f"[API] Modo cambiado exitosamente en simulador")
            except ConnectionRefusedError:
                print(f"[API] Simulador no conectado en puerto 9001")
                self._responder_json({"ok": False, "error": "Simulador no conectado"})
            except Exception as e:
                print(f"[API] Error: {e}")
                self._responder_json({"ok": False, "error": str(e)})
        
        elif path == "/cambiar_portador":
            portador = body.get("portador", "001")
            print(f"[API] Cambiando portador a: {portador}")
            
            # Reenviar comando al simulador
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect(("localhost", 9001))
                sock.send(json.dumps({"comando": "set_portador", "portador": portador}).encode())
                respuesta = json.loads(sock.recv(1024).decode())
                sock.close()
                self._responder_json({"ok": True, "portador": portador, "simulador": respuesta})
            except ConnectionRefusedError:
                self._responder_json({"ok": False, "error": "Simulador no conectado"})
            except Exception as e:
                self._responder_json({"ok": False, "error": str(e)})
        
        else:
            self.send_response(404)
            self.end_headers()


    def _get_estado(self):
        if not self.receptor or not self.receptor.ultimo_resultado:
            return {"estado": "sin_datos", "nivel": "NORMAL", "alertas": []}
        
        r = self.receptor.ultimo_resultado
        return {
            "estado": "activo",
            "nivel": r.nivel_global.name,
            "nivel_valor": r.nivel_global.value,
            "portador": r.portador_nombre,
            "resumen": r.resumen,
            "timestamp": r.timestamp,
            "alertas": [
                {
                    "parametro": a["parametro"],
                    "valor": a["valor"],
                    "nivel": a["nivel"].name,
                    "mensaje": a["mensaje"]
                }
                for a in r.alertas
            ],
            "datos_raw": r.datos_raw
        }
    
    def _get_historial(self):
        if not self.receptor:
            return []
        
        return [
            {
                "timestamp": r.timestamp,
                "nivel": r.nivel_global.name,
                "nivel_valor": r.nivel_global.value,
                "n_alertas": len(r.alertas),
                "resumen": r.resumen
            }
            for r in self.receptor.evaluador.historial[-20:]
        ]
    
    def _responder_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)
        
    def log_message(self, format, *args):
        pass

def iniciar_api(receptor, puerto=8080):
    APIHandler.receptor = receptor
    servidor = http.server.HTTPServer(("localhost", puerto), APIHandler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    print(f"[API] http://localhost:{puerto}")
    return servidor

if __name__ == "__main__":
    def on_datos(resultado):
        icon = {0:"✅",1:"⚠",2:"🔶",3:"🔴"}[resultado.nivel_global.value]
        print(f"\n{icon} [{resultado.nivel_global.name}] {resultado.resumen}")
        for alerta in resultado.alertas:
            print(f"   → {alerta['mensaje']}")
    
    receptor = ReceptorArduino(callback=on_datos)
    receptor.start()
    
    api = iniciar_api(receptor, puerto=8080)
    
    print("="*50)
    print("  PROCESADOR PYTHON - BRAZALETE DE SALUD")
    print("="*50)
    print("  Escuchando datos del Arduino...")
    print("  API disponible en http://localhost:8080")
    print("  Presiona Ctrl+C para detener")
    print("="*50)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[PYTHON] Procesador detenido")