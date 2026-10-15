# Arquitectura de FingerMelody

FingerMelody se organiza como una aplicación de escritorio modular. Cada módulo tiene una responsabilidad y se comunica con los demás mediante datos y eventos, no mediante acceso directo a sus detalles internos.

El diseño sigue este recorrido:

```
Cámara → Detección de manos → Identificación de dedos → Reconocimiento de pulsaciones → Asignación musical → Reproducción de audio
```

La interfaz gráfica no forma parte de esa cadena. Recibe los eventos y estados necesarios para mostrar la cámara, las notas activas y el piano virtual.

## Responsabilidad de cada módulo

| Módulo | Responsabilidad |
| --- | --- |
| `vision` | Abrir la cámara, leer fotogramas y ejecutar el modelo preentrenado de MediaPipe para localizar las manos. |
| `gestures` | Interpretar las posiciones de los dedos, detectar flexiones y pulsaciones, y mantener el estado de cada dedo. |
| `music` | Asignar pulsaciones a notas, representar canciones y distinguir la reproducción libre del modo guiado. |
| `audio` | Reproducir notas en tiempo real, controlar el volumen y permitir que varias notas suenen a la vez. |
| `interface` | Construir la interfaz con PySide6: vista de cámara, piano virtual, controles e indicadores. |
| `core` | Guardar la configuración y coordinar el arranque, el intercambio de datos y el cierre de los módulos. |
| `main` | Punto de entrada previsto. Todavía no integra ninguna funcionalidad. |

Los recursos previstos quedan fuera del código:

- `assets/models/` para el modelo preentrenado.
- `assets/sounds/` para las muestras de audio.
- `songs/` para las definiciones de canciones.
- `tests/` para las pruebas.
- `docs/` para la documentación técnica.

## Dependencias previstas

Las dependencias apuntan hacia la coordinación, no entre los extremos de la aplicación.

```
interface ──┐
vision ─────┤
gestures ───┼── datos y eventos ── core
music ──────┤
audio ──────┘
```

- `vision` produce observaciones de manos y dedos. No conoce notas, sonidos ni widgets.
- `gestures` consume esas observaciones y emite pulsaciones y estados. No abre la cámara ni reproduce audio.
- `music` consume pulsaciones y produce comandos musicales. No depende de MediaPipe ni de PySide6.
- `audio` consume comandos de nota. No consulta la cámara ni los componentes visuales.
- `interface` muestra estados y recoge acciones del usuario. No ejecuta el modelo ni el motor de audio.
- `core` es el único punto que conoce cómo se ensamblan los módulos.

## Cómo se evita el acoplamiento

- Cada módulo importa solo los contratos que necesita, no la implementación de los demás.
- Los datos que cruzan un límite son valores simples: fotograma, puntos de la mano, pulsación, nota o estado de reproducción.
- `core` crea los objetos y conecta sus entradas y salidas. Un módulo no instancia a otro para “pedir prestada” una función.
- La interfaz y el audio quedan en extremos opuestos: ningún widget llama al reproductor, y el reproductor no importa PySide6.
- Cambiar el modelo, el motor de sonido o la pantalla no obliga a reescribir el reconocimiento de pulsaciones ni la asignación musical.

## Cámara e interfaz en hilos distintos

El procesamiento de cámara no se ejecuta en el hilo principal de la interfaz.

1. `core` arranca un hilo de trabajo para la captura y la detección.
2. Ese hilo publica fotogramas y resultados de manos en una cola segura.
3. El hilo de la interfaz recoge esas copias y actualiza la imagen, las notas y el piano.
4. Las acciones de la interfaz (inicio, parada, volumen, modo libre o guiado) vuelven a `core` como comandos.
5. `core` entrega las pulsaciones a `music` y los comandos de nota a `audio`, fuera de los widgets.

Así la interfaz sigue respondiendo mientras se procesa el vídeo, y el audio reacciona a eventos musicales en lugar de a componentes gráficos.
