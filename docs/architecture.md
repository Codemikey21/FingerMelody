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
| `main` | Punto de entrada. Abre la ventana principal. |

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
- `interface` muestra estados y recoge acciones del usuario. No ejecuta MediaPipe. Los widgets del piano, la cámara y el panel no importan el motor de audio.
- `core` queda reservado para la configuración. Hoy la ventana principal es quien crea la cámara, el mapeo y el único `AudioEngine`.

## Cómo se evita el acoplamiento

- Cada módulo importa solo los contratos que necesita, no la implementación de los demás.
- Los datos que cruzan un límite son valores simples: fotograma, puntos de la mano, pulsación, nota o estado de reproducción.
- `core` crea los objetos y conecta sus entradas y salidas. Un módulo no instancia a otro para “pedir prestada” una función.
- La ventana traduce señales y pulsaciones a `play_note`. Pintar una tecla no reproduce sonido. `AudioEngine` no importa PySide6.
- Cambiar el modelo, el motor de sonido o la pantalla no obliga a reescribir el reconocimiento de pulsaciones ni la asignación musical.

## Cámara e interfaz en hilos distintos

El procesamiento de cámara no se ejecuta en el hilo principal de la interfaz.

1. `MainWindow` arranca `CameraWorker`, un `QThread` para la captura, el modelo, los dedos y los gestos.
2. Ese hilo publica solo el último fotograma, los FPS, el estado de las manos y los gestos. Las pulsaciones nuevas entran en una cola.
3. Una señal avisa a la ventana. El hilo de la interfaz vacía la cola una vez, traduce cada `FingerPressEvent` con `NoteMapper` y llama a `play_note`. El temporizador de la vista actualiza la imagen y la iluminación, sin volver a reproducir esa pulsación.
4. Iniciar, detener, volumen, silencio y reinicio del contador son acciones de la ventana. El contador de cada dedo se pone a cero en el hilo de captura, sin cambiar la fase del gesto.
5. Cerrar la ventana detiene el hilo y llama a `shutdown` del motor de audio.

Así la interfaz sigue respondiendo mientras se procesa el vídeo, y el audio reacciona al evento de pulsación. La actualización visual de la tecla es independiente.

## Reconocimiento de manos

`HandTracker` carga una sola vez el Hand Landmarker oficial en modo vídeo, con `num_hands=2`. Vive en el mismo hilo que la captura y no se comparte con la interfaz. El hilo conserva solo el último fotograma anotado.

La cámara entrega BGR sin espejar. El hilo de captura lo voltea una sola vez con `cv2.flip(frame, 1)`. Esa copia espejada entra en el modelo y es la que se dibuja, así que los 21 puntos quedan alineados con la vista. Hand Landmarker (Tasks) nombra la mano del usuario en una imagen sin espejo; en esta vista espejada esa etiqueta se intercambia una vez. `Left` y `Right` guardadas en el resultado son la mano anatómica, y la ventana las muestra como Izquierda y Derecha. El lado de la pantalla no decide la etiqueta: con los brazos cruzados, la mano izquierda puede verse a la derecha. Si la confianza no llega a 0,5, no se inventa una etiqueta.

Cada mano aporta 21 puntos: muñeca, cuatro del pulgar y cuatro de cada uno de los otros dedos. Esos puntos se convierten a píxeles para dibujar las conexiones. El modelo está en `assets/models/hand_landmarker.task`.

## Identificación de dedos

`FingerDetector` no carga un modelo. Recibe el `HandFrame` del mismo hilo de captura y reparte los puntos por su índice oficial: pulgar 1–4, índice 5–8, medio 9–12, anular 13–16 y meñique 17–20. El identificador (`LEFT_THUMB`, `RIGHT_INDEX`, …) une ese dedo con la mano anatómica ya corregida. El orden en que MediaPipe devuelve las manos y el lado de la pantalla no cambian el identificador.

Si una mano falta en el fotograma, sus dedos no se dibujan y el motor de gestos suspende esa mano. La otra conserva sus identificadores.

## Pulsaciones

`GestureEngine` recibe los dedos ya identificados, en el mismo hilo de captura. No vuelve a ejecutar MediaPipe. Para índice, medio, anular y meñique mide el ángulo en PIP y en DIP con tres landmarks, más la extensión de la punta respecto a la cadena de segmentos. El pulgar usa los landmarks 1–4 y, además, la oposición: distancia de la punta al MCP del índice dividida por el largo de la palma (muñeca al MCP del medio). Así una flexión hacia la palma cuenta aunque el ángulo del IP siga abierto. Un giro o una traslación de toda la mano no cambia esas medidas.

Cada dedo recorre READY, PRESSED, HELD y RELEASED. El evento `FingerPressEvent` (`finger_id`, `timestamp_ms`) sale solo al pasar de READY a PRESSED, cuando se cumplen los fotogramas mínimos y un tiempo monotónico (`press_ms`). Perder el seguimiento lleva a LOST y no cuenta como liberación; al reaparecer hace falta un reposo confirmado antes de otra pulsación. Mantener el dedo flexionado no repite el evento. Hay un cooldown por dedo. Los umbrales de partida están en `GestureConfig`. En Configuración se pueden guardar un reposo y una flexión; el motor usa el punto medio de esa persona y no borra esas referencias al reiniciar la cámara. El motor no conoce notas ni sonido.

El hilo de captura mide, con reloj monotónico, la lectura del fotograma, la inferencia, la geometría y el dibujo. Encola el evento y avisa a la ventana antes de dibujar. Esas cifras son tiempos de etapa, no la latencia acústica del altavoz. El panel **Diagnóstico** las muestra bajo demanda y no escribe nombres sobre la imagen.

## Motor musical

`music.notes` calcula las diez frecuencias con la afinación temperada y A4 a 440 Hz. `NoteMapper` asocia cada dedo a una de esas notas y se puede sustituir; `AudioEngine` no lo importa. El sintetizador crea las muestras una vez, en PCM de 16 bits y dos canales, y el mezclador solo las reproduce.

`SessionController` es el modo libre. Recibe `MusicalEvent` (nota, origen gesto o clic, y dedo si viene de un gesto). No abre la cámara ni llama a `play_note`. La ventana solo reproduce cuando la sesión está interpretando y el controlador acepta el evento. En pausa no hay notas nuevas. Al iniciar y al reanudar, los dedos que siguen flexionados quedan fuera hasta que vuelven a una pose abierta. El historial guarda nota, dedo, origen y milisegundos desde el inicio de la sesión, sin contar el tiempo en pausa. El modo guiado no está en `available_modes()`: no hay botón ni canción mientras no se añada ahí.

## Interfaz

Los componentes viven en `src/fingermelody/interface/`.

| Pieza | Papel |
| --- | --- |
| `main_window.MainWindow` | Compone la pantalla, posee el hilo de cámara y el único motor de audio, y conecta las señales. |
| `camera_panel` | Vídeo, dispositivo, color de cada mano y FPS. La proporción del fotograma se conserva al redimensionar. |
| `piano_widget` | Diez teclas blancas, C4 a E5, y teclas negras de adorno entre los tonos. El clic emite la nota; no llama al mezclador. |
| `info_panel` | Modo, sesión, historial reciente, última nota, dedo, manos, contador, FPS y estado de la cámara y del sonido. |
| `settings_dialog` | Asociación real dedo-nota, dispositivo y estado del audio. |
| `styles` | Tema oscuro, aplicado una vez. |
| `camera_worker` | Captura y reconocimiento fuera del hilo gráfico. |

La imagen muestra landmarks, conexiones y un anillo breve en la punta cuando hay pulsación. Los nombres de los dedos están en el panel. Izquierda y derecha siguen la mano anatómica de la vista espejada.

Controles de cámara y audio: **Iniciar cámara**, **Detener cámara**, **Volumen**, **Silenciar audio**, **Detener sonidos**, **Reiniciar pulsaciones** y **Configuración**. En el panel, el modo libre añade **Iniciar sesión**, **Pausar**, **Reanudar** y **Finalizar**. El encabezado indica si la cámara está activa y el estado del reconocimiento. Sin una sesión en interpretación, el piano no acepta clics.
