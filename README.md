# Brazalete de Monitoreo Médico — Prototipo

Sistema de monitoreo de salud en tiempo real con detección de anomalías personalizada según condición médica del portador.

## Arquitectura del sistema

```
[Arduino / Sensores]  →  [Python Procesador]  →  [Interfaz Web de Alertas]
  puerto serial/USB       evalúa parámetros        LED + mensajes contextuales
  (simulado en Python)    según perfil portador     según gravedad
```

## Archivos del proyecto

| Archivo | Descripción |
|---|---|
| `arduino_simulator.py` | Simula el Arduino enviando datos por socket TCP |
| `procesador_salud.py` | Recibe datos, evalúa parámetros y expone API HTTP |
| `interfaz_alertas.html` | Dashboard web con LED de alerta y mensajes |

## Cómo ejecutar

### Opción A — Sistema completo (Arduino + Python + Web)

**Terminal 1 — Iniciar simulador Arduino:**
```bash
# Modo normal (portador 001, modo normal)
python arduino_simulator.py 001 normal

# Simular situación de alerta
python arduino_simulator.py 001 alerta

# Simular emergencia crítica
python arduino_simulator.py 003 critico
```

**Terminal 2 — Iniciar procesador Python:**
```bash
python procesador_salud.py
```

Luego abrir `http://localhost:8080/estado` para ver el JSON de estado.

### Opción B — Solo la interfaz simulada (standalone)
Abrir `interfaz_alertas.html` directamente en el navegador.
La interfaz genera sus propios datos simulados sin necesidad de Arduino ni Python.

## Portadores disponibles

| ID | Nombre | Condiciones | Umbrales especiales |
|---|---|---|---|
| 001 | Carlos Mendoza (58 años) | Hipertensión + Diabetes Tipo 2 | PA ≥140 = precaución, glucosa ≥130 = precaución |
| 002 | Ana Torres (34 años) | Asma | SpO₂ <95% = precaución (más estricto) |
| 003 | Miguel Soto (72 años) | Arritmia + Hipertensión | Pulso ≥90 = precaución |

## Niveles de alerta

| Color LED | Nivel | Acción |
|---|---|---|
| 🟢 Verde | Normal | Monitoreo continuo |
| 🟡 Amarillo | Precaución | Vigilar, revisar medicación |
| 🟠 Naranja | Alerta | Contactar médico tratante |
| 🔴 Rojo parpadeante | Crítico | EMERGENCIA — llamar urgencias |

## Parámetros monitoreados

- **Pulso cardíaco** — bpm (taquicardia/bradicardia)
- **Temperatura corporal** — °C (fiebre/hipotermia)
- **Presión arterial** — sistólica/diastólica mmHg
- **Saturación de oxígeno (SpO₂)** — % (hipoxemia)
- **Glucosa en sangre** — mg/dL (hipo/hiperglucemia)
- **Acelerómetro** — detección de caídas/movimiento inusual

## Hardware real (para implementación física)

```
Arduino Nano/Uno
├── MAX30102 — Pulso y SpO₂ (I2C: SDA/SCL)
├── DS18B20  — Temperatura corporal (pin 4)
├── MPU6050  — Acelerómetro/giroscopio (I2C)
├── LED RGB  — Indicador visual (pines 9,10,11)
├── Buzzer   — Alarma sonora (pin 12)
└── HC-05   — Bluetooth para comunicación inalámbrica
```

## API del procesador Python

| Endpoint | Método | Descripción |
|---|---|---|
| `/estado` | GET | Estado actual del portador |
| `/historial` | GET | Últimas 20 lecturas |
| `/portadores` | GET | Perfiles disponibles |
| `/simular` | POST | Simular datos directamente (body JSON) |

### Ejemplo de respuesta `/estado`:
```json
{
  "nivel": "ALERTA",
  "nivel_valor": 2,
  "portador": "Carlos Mendoza",
  "resumen": "🔶 Carlos Mendoza: ALERTA MÉDICA — contactar médico tratante.",
  "alertas": [
    {
      "parametro": "presion_sistolica",
      "valor": 162.3,
      "nivel": "ALERTA",
      "mensaje": "🔶 ALERTA: Presión 162 mmHg — Hipertensión en zona de riesgo. Tomar medicación."
    }
  ]
}
```
