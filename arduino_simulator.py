"""
Arduino Simulator - Brazalete de Salud
Simula el envío de datos de sensores por puerto serial (o socket)
En un sistema real, este código correría en el Arduino y enviaría datos por USB/Serial
"""

import json
import time
import random
import socket
import threading
import math

# ─── Perfiles de portadores ───────────────────────────────────────────────────
PORTADORES = {
    "001": {
        "nombre": "Carlos Mendoza",
        "edad": 58,
        "condiciones": ["hipertension", "diabetes"],
        "medicamentos": ["metformina", "losartan"],
        "contacto_emergencia": "+56912345678"
    },
    "002": {
        "nombre": "Ana Torres",
        "edad": 34,
        "condiciones": ["asma"],
        "medicamentos": ["salbutamol"],
        "contacto_emergencia": "+56987654321"
    },
    "003": {
        "nombre": "Miguel Soto",
        "edad": 72,
        "condiciones": ["arritmia", "hipertension"],
        "medicamentos": ["amiodarona", "enalapril"],
        "contacto_emergencia": "+56911223344"
    }
}

# ─── Generador de datos de sensores ───────────────────────────────────────────
class ArduinoSensor:
    def __init__(self, portador_id="001", modo="normal"):
        self.portador_id = portador_id
        self.modo = modo  # normal, alerta, critico
        self.tiempo = 0
        
        # Valores base del portador
        self.base_pulso = 72
        self.base_temp = 36.6
        self.base_sist = 120
        self.base_diast = 80
        self.base_spo2 = 98
        self.base_glucosa = 100
        
    def _noise(self, valor, magnitud=1.0):
        """Añade ruido natural a la señal"""
        return valor + random.gauss(0, magnitud)
    
    def _onda_sinusoidal(self, amplitud, periodo):
        """Simula variaciones cíclicas naturales"""
        return amplitud * math.sin(2 * math.pi * self.tiempo / periodo)
    
    def generar_lectura(self):
        self.tiempo += 1
        
        if self.modo == "normal":
            pulso = self._noise(self.base_pulso + self._onda_sinusoidal(5, 30), 2)
            temperatura = self._noise(self.base_temp + self._onda_sinusoidal(0.3, 120), 0.1)
            sistolica = self._noise(self.base_sist + self._onda_sinusoidal(8, 60), 3)
            diastolica = self._noise(self.base_diast + self._onda_sinusoidal(5, 60), 2)
            spo2 = min(100, self._noise(self.base_spo2, 0.5))
            glucosa = self._noise(self.base_glucosa + self._onda_sinusoidal(10, 90), 3)
            
        elif self.modo == "alerta":
            pulso = self._noise(105 + self._onda_sinusoidal(15, 10), 5)
            temperatura = self._noise(37.8 + self._onda_sinusoidal(0.5, 30), 0.2)
            sistolica = self._noise(155 + self._onda_sinusoidal(10, 15), 5)
            diastolica = self._noise(100 + self._onda_sinusoidal(8, 15), 3)
            spo2 = min(100, self._noise(94, 1))
            glucosa = self._noise(180 + self._onda_sinusoidal(20, 20), 5)
            
        elif self.modo == "critico":
            pulso = self._noise(145 + self._onda_sinusoidal(30, 5), 8)
            temperatura = self._noise(39.5 + self._onda_sinusoidal(1, 10), 0.3)
            sistolica = self._noise(185 + self._onda_sinusoidal(15, 8), 8)
            diastolica = self._noise(120 + self._onda_sinusoidal(10, 8), 5)
            spo2 = min(100, self._noise(88, 2))
            glucosa = self._noise(280 + self._onda_sinusoidal(30, 10), 10)
        
        # Formato de datos que enviaría el Arduino
        datos = {
            "id_portador": self.portador_id,
            "timestamp": time.time(),
            "sensores": {
                "pulso_bpm": round(pulso, 1),
                "temperatura_c": round(temperatura, 2),
                "presion_sistolica": round(sistolica, 1),
                "presion_diastolica": round(diastolica, 1),
                "spo2_porcentaje": round(spo2, 1),
                "glucosa_mgdl": round(glucosa, 1)
            },
            "acelerometro": {
                "x": round(random.gauss(0, 0.1 if self.modo == "normal" else 0.8), 3),
                "y": round(random.gauss(0, 0.1 if self.modo == "normal" else 0.8), 3),
                "z": round(random.gauss(9.8, 0.1), 3)
            },
            "bateria_porcentaje": max(10, 95 - (self.tiempo * 0.01)),
            "modo_debug": self.modo
        }
        return datos


# ─── Servidor Socket (simula el Arduino transmitiendo) ───────────────────────
class ArduinoServer:
    def __init__(self, host="localhost", port=9000):
        self.host = host
        self.port = port
        self.running = False
        self.sensor = ArduinoSensor()
        self.intervalo = 2.0  # segundos entre lecturas
        
    def set_portador(self, portador_id):
        self.sensor.portador_id = portador_id
        
    def set_modo(self, modo):
        self.sensor.modo = modo
        
    def start(self):
        self.running = True
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(1)
        print(f"[ARDUINO] Servidor iniciado en {self.host}:{self.port}")
        print(f"[ARDUINO] Portador: {PORTADORES[self.sensor.portador_id]['nombre']}")
        
        while self.running:
            try:
                self.server.settimeout(1.0)
                conn, addr = self.server.accept()
                print(f"[ARDUINO] Conexión establecida con {addr}")
                self._handle_client(conn)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[ARDUINO] Error: {e}")
                    
    def _handle_client(self, conn):
        try:
            while self.running:
                datos = self.sensor.generar_lectura()
                mensaje = json.dumps(datos) + "\n"
                conn.sendall(mensaje.encode())
                print(f"[ARDUINO] Enviado → pulso:{datos['sensores']['pulso_bpm']} "
                      f"| temp:{datos['sensores']['temperatura_c']}°C "
                      f"| PA:{datos['sensores']['presion_sistolica']}/{datos['sensores']['presion_diastolica']}")
                time.sleep(self.intervalo)
        except Exception:
            print("[ARDUINO] Cliente desconectado")
            
    def stop(self):
        self.running = False


# ─── Código Arduino (C++) que iría en el dispositivo real ────────────────────
CODIGO_ARDUINO = """
/*
 * Brazalete de Salud - Código Arduino
 * Sensores: MAX30102 (pulso/SpO2), DS18B20 (temperatura),
 *           MPU6050 (acelerómetro), BMP280 (presión)
 * Comunicación: Serial USB / Bluetooth HC-05
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include "MAX30105.h"      // Sensor pulso y SpO2
#include "OneWire.h"       // Sensor temperatura
#include "DallasTemperature.h"

// ── Pines ──
#define PIN_TEMP     4
#define PIN_LED_R    9
#define PIN_LED_G    10
#define PIN_LED_B    11
#define PIN_BUZZER   12
#define ID_PORTADOR  "001"

// ── Objetos ──
MAX30105 particleSensor;
OneWire oneWire(PIN_TEMP);
DallasTemperature sensors(&oneWire);

// ── Variables globales ──
float pulso_bpm = 0;
float temperatura_c = 0;
float spo2 = 0;
unsigned long ultima_lectura = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin();
  sensors.begin();
  
  // Inicializar MAX30102
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("ERROR: Sensor MAX30102 no encontrado");
    while (1);
  }
  
  particleSensor.setup();
  particleSensor.setPulseAmplitudeRed(0x0A);
  particleSensor.setPulseAmplitudeGreen(0);
  
  // Pines LED y Buzzer
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  
  Serial.println("BRAZALETE_INIT");
}

void loop() {
  if (millis() - ultima_lectura >= 2000) {
    ultima_lectura = millis();
    
    // Leer temperatura
    sensors.requestTemperatures();
    temperatura_c = sensors.getTempCByIndex(0);
    
    // Leer pulso y SpO2 (simplificado)
    long irValue = particleSensor.getIR();
    if (irValue > 50000) {
      pulso_bpm = calcularBPM();
      spo2 = calcularSpO2();
    }
    
    // Construir JSON
    StaticJsonDocument<256> doc;
    doc["id_portador"] = ID_PORTADOR;
    doc["timestamp"] = millis();
    
    JsonObject sensores = doc.createNestedObject("sensores");
    sensores["pulso_bpm"] = pulso_bpm;
    sensores["temperatura_c"] = temperatura_c;
    sensores["spo2_porcentaje"] = spo2;
    
    // Enviar por Serial
    serializeJson(doc, Serial);
    Serial.println();
  }
}
"""
 # ─── Servidor de comandos para recibir cambios de modo ───────────────────────
class ComandoServer:
    def __init__(self, arduino_server, host="localhost", port=9001):
        self.arduino_server = arduino_server
        self.host = host
        self.port = port
        self.running = False
        
    def start(self):
        self.running = True
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(1)
        print(f"[COMANDOS] Servidor iniciado en {self.host}:{self.port}")
        
        while self.running:
            try:
                self.server.settimeout(1.0)
                conn, addr = self.server.accept()
                self._handle_comando(conn)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[COMANDOS] Error: {e}")
    
    def _handle_comando(self, conn):
        try:
            datos = conn.recv(1024).decode()
            if datos:
                comando = json.loads(datos)
                if comando.get("comando") == "set_modo":
                    modo = comando.get("modo", "normal")
                    print(f"[COMANDOS] Cambiando modo a: {modo}")
                    self.arduino_server.set_modo(modo)
                    conn.send(json.dumps({"ok": True, "modo": modo}).encode())
                elif comando.get("comando") == "set_portador":
                    portador = comando.get("portador", "001")
                    print(f"[COMANDOS] Cambiando portador a: {portador}")
                    self.arduino_server.set_portador(portador)
                    conn.send(json.dumps({"ok": True, "portador": portador}).encode())
        except Exception as e:
            print(f"[COMANDOS] Error procesando comando: {e}")
        finally:
            conn.close()
    
    def stop(self):
        self.running = False

if __name__ == "__main__":
    import sys
    import threading
    
    portador_id = sys.argv[1] if len(sys.argv) > 1 else "001"
    modo_inicial = sys.argv[2] if len(sys.argv) > 2 else "normal"
    
    server = ArduinoServer()
    server.set_portador(portador_id)
    server.set_modo(modo_inicial)
    
    # Cambiar modos automáticamente cada 10 segundos (mismo portador)
    def cambiar_modos_auto():
        modos = ["normal", "alerta", "critico", "normal", "alerta", "critico"]
        idx = 0
        while True:
            time.sleep(20)
            nuevo_modo = modos[idx % len(modos)]
            server.set_modo(nuevo_modo)
            print(f"\n[ARDUINO] >>> PACIENTE {portador_id} CAMBIA A MODO: {nuevo_modo.upper()} <<<\n")
            idx += 1
    
    # Iniciar cambios automáticos
    hilo_auto = threading.Thread(target=cambiar_modos_auto, daemon=True)
    hilo_auto.start()
    
    print("="*50)
    print(f"  SIMULADOR ARDUINO - PULSERA PACIENTE {portador_id}")
    print("="*50)
    print(f"  Puerto datos: 9000")
    print(f"  Modo actual: {modo_inicial.upper()}")
    print("  Cambia automático: normal → alerta → crítico (cada 10s)")
    print("="*50)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[SIMULADOR] Detenido")
        server.stop()
       
