# FingerMelody

Aplicación de escritorio para interpretar melodías con los diez dedos de ambas manos frente a una cámara.

## Descripción general

FingerMelody captura el movimiento de las manos en tiempo real y lo traduce en música. La cámara observa ambas manos, el seguimiento identifica cada dedo y un motor de audio convierte esa interpretación en sonido.

## Objetivo

Permitir interpretar melodías mediante el movimiento de los dedos, sin un instrumento físico, con una respuesta visual y sonora en tiempo real.

## Funcionalidades previstas

- Captura de vídeo desde la cámara.
- Detección y seguimiento de ambas manos y de sus diez dedos.
- Asociación de la posición y el movimiento de cada dedo con notas y parámetros musicales.
- Síntesis de audio en tiempo real a partir de esa interpretación.
- Interfaz de escritorio para ver la captura, el seguimiento y el estado de la interpretación.

## Tecnologías

- Python 3.11
- OpenCV
- MediaPipe
- PySide6
- pygame

## Estado del desarrollo

La ventana es la experiencia de Jingle Bells: las notas bajan hasta el piano, la cámara queda en una tarjeta pequeña y el piano ocupa el ancho de la escena. Flexionar el dedo de la nota indicada la reproduce e ilumina la tecla. El piano también suena al pulsar esa tecla con el ratón. La canción avanza solo cuando se toca la nota que espera.

## Entorno de desarrollo

Hace falta Python 3.11 de 64 bits. En este equipo el lanzador `python` puede apuntar a otra versión; el entorno debe crearse con `py -3.11`.

Desde la raíz del repositorio, en PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt --no-deps
python -m pip install -e . --no-deps
```

`.venv/` está excluido en `.gitignore`. MediaPipe 1.1.1 requiere `opencv-contrib-python`; esa es la única distribución de OpenCV fijada en `requirements.txt`.

`pyproject.toml` solo empaqueta `src/fingermelody`, para que `python -m fingermelody.main` funcione con la estructura `src/`.

### Ejecutar desde Cursor

El intérprete del workspace es `.venv/Scripts/python.exe`. Cursor lo toma de la configuración local del editor; esa configuración no forma parte del repositorio.

En una terminal del proyecto, con el entorno activado:

```powershell
python -m fingermelody.main
```

Se abre la ventana de FingerMelody. La cámara no arranca hasta que se pulsa **Iniciar cámara**.

### Cámara

1. Pulsa **Iniciar** en la tarjeta de la cámara para ver el vídeo y los landmarks.
2. Pulsa **Detener** para liberar la cámara y el modelo. **Detalles** abre FPS, manos, audio y diagnóstico.
3. Cerrar la ventana también detiene la captura.

La imagen se muestra en espejo, como una cámara frontal. OpenCV entrega el fotograma sin voltear; la aplicación lo voltea una sola vez y usa esa copia para reconocer y para dibujar. El Hand Landmarker de MediaPipe Tasks nombra la mano en una imagen sin espejo, así que sobre esta vista la etiqueta se corrige una vez: la mano izquierda aparece como Izquierda y la derecha como Derecha. La etiqueta es anatómica, no el lado de la pantalla. Si la confianza es baja, esa mano no recibe etiqueta.

Pulsa **Iniciar sesión**. Las notas de Jingle Bells bajan hasta la línea y esperan. Toca la nota que se muestra, con el dedo o con el piano: la tecla se ilumina, salen partículas y entra la siguiente. El badge pasa a **Activa**. **Pausar** lo deja en **Pausada** y corta las notas nuevas; la cámara puede seguir. **Reanudar** no repite un dedo que ya estaba flexionado: hay que abrirlo y flexionarlo otra vez. **Finalizar** marca **Finalizada**. Las cápsulas del historial entran y se retiran con un fundido.

Coloca una o las dos manos frente a la cámara, con la palma visible y los dedos extendidos. Con las dos, el indicador debe decir **Ambas manos presentes** y el panel pasa de **Seguimiento perdido** a **Reposo** en los diez dedos. Con la sesión en marcha, dobla un dedo y mantenlo: debe pasar a **Pulsación**, el contador sube una vez y un aro marca la punta; si lo sigues doblando, queda en **Flexionado** sin sumar otra pulsación. Ábrelo y dóblalo otra vez para sumar la siguiente. Mover la mano abierta, sin doblar dedos, no debe aumentar el contador.

Los umbrales iniciales viven en `GestureConfig`. El pulgar no depende solo del ángulo de los otros dedos: también mide cuánto se acerca la punta a la palma. En **Configuración**, **Guardar reposo** (dedos extendidos) y **Guardar flexión** (pulgar y dedos que quieras ajustar) adaptan ese punto de partida a tu mano. **Diagnóstico** muestra el dedo, la flexión, el estado y los tiempos de captura, modelo, geometría y `play_note`. Esos tiempos no incluyen el retardo del altavoz.

La cámara principal es el índice 0 y la resolución inicial es 640×480. Para usar otro dispositivo o pedir otra resolución:

```powershell
python -m fingermelody.main --camera 1
python -m fingermelody.main --width 320 --height 240
```

Si el controlador no admite el tamaño pedido, entrega la resolución más cercana. Los FPS que muestra la ventana se calculan con los fotogramas ya procesados, detección incluida.

### Modelo de manos

Se usa el Hand Landmarker oficial de MediaPipe, variante float16, sin entrenamiento propio.

- Archivo: `assets/models/hand_landmarker.task`
- Origen: <https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task>
- Documentación: <https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python>
- Licencia: Apache License 2.0, la misma de MediaPipe

El archivo se carga una vez al iniciar la cámara. No se vuelve a descargar en cada ejecución. Los 21 puntos van de la muñeca a la punta de cada dedo: pulgar, índice, medio, anular y meñique, con sus articulaciones.

### Audio

El motor no usa grabaciones externas. Al abrir la ventana sintetiza diez notas y las deja en memoria. Cada una dura 450 ms: una fundamental seno, cuatro armónicos más bajos, un ataque corto y una liberación que termina en silencio. La reproducción es pygame.mixer a 44100 Hz, PCM de 16 bits con signo, estéreo y un buffer de 512 muestras. Ese buffer son unos 12 ms de cola interna; el retardo que se oye también depende del controlador y no está medido de punta a punta.

| Nota | Frecuencia temperada |
| --- | --- |
| C4 | 261,63 Hz |
| D4 | 293,66 Hz |
| E4 | 329,63 Hz |
| F4 | 349,23 Hz |
| G4 | 392,00 Hz |
| A4 | 440,00 Hz |
| B4 | 493,88 Hz |
| C5 | 523,25 Hz |
| D5 | 587,33 Hz |
| E5 | 659,255 Hz |

La asociación es pulgar izquierdo C4, índice D4, medio E4, anular F4, meñique G4, y en la derecha A4, B4, C5, D5 y E5. Está en `NoteMapper` y se puede cambiar sin tocar el mezclador. La ventana usa esa tabla: cada pulsación llama a `play_note` una sola vez, y la iluminación de la tecla es aparte.

Para escucharlo, abre la aplicación. Pulsa una tecla del piano o, con la cámara en marcha, flexiona el dedo correspondiente. **Volumen** está en el encabezado. **Silenciar audio** guarda el nivel y deja la salida en cero; **Activar audio** lo recupera. **Detener sonidos** corta lo que siga sonando. Si no hay dispositivo, el indicador lo dice y la cámara sigue funcionando.

En Windows, si no se oye nada: revisa el dispositivo de salida predeterminado, sube el volumen del sistema y cierra otro programa que tenga el audio en exclusiva. Un buffer más corto bajaría la cola interna y en algunos equipos introduce cortes; el valor inicial es 512.

### Pruebas

```powershell
python -m pytest
```

`pytest` no abre la cámara, no ejecuta el modelo real y no necesita altavoces: el mezclador se simula. Para comprobar la interfaz, ejecuta la aplicación y cambia el tamaño de la ventana. Pulsa **Iniciar cámara** y muestra las palmas. En la imagen se ven los puntos y las conexiones, con un color distinto para cada mano; los nombres de los dedos quedan en el panel. Pulsa **Iniciar sesión**. Flexiona un dedo y comprueba que suena una vez, que su tecla se ilumina y que el panel indica la nota, el dedo, el contador y una línea del historial. El pulgar izquierdo debe sonar C4 y el derecho A4, sin repetir mientras sigan flexionados. **Pausar** debe dejar en silencio tanto el dedo como el clic; **Reanudar** no debe repetir un dedo que seguía flexionado. Activa **Diagnóstico** para ver el estado y los tiempos de cada etapa. Si un pulgar abierto no llega a **Reposo**, o una flexión clara no suena, guarda reposo y flexión en **Configuración** con la cámara en marcha. Prueba también una tecla con el ratón, el volumen, el silencio y **Reiniciar pulsaciones**.

### Problemas habituales

- Si `python` no es 3.11, vuelve a crear el entorno con `py -3.11 -m venv .venv`.
- Si PowerShell bloquea `Activate.ps1`, ejecuta `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y activa el entorno de nuevo. También puedes llamar a `.venv\Scripts\python.exe` sin activarlo.
- No instales `opencv-python` ni `opencv-python-headless` junto a `opencv-contrib-python`. Esas distribuciones publican el mismo módulo `cv2`.
- No uses paquetes instalados en el Python global. El entorno virtual no los incluye.
- En Windows, permite el acceso a la cámara a las aplicaciones de escritorio en Configuración, Privacidad y seguridad, Cámara.
- Si la cámara está abierta en otra aplicación, ciérrala antes de iniciar la captura.
- Si el índice 0 no es la cámara del portátil, prueba `--camera 1`.
- Si falta `assets/models/hand_landmarker.task`, la cámara puede seguir en marcha, pero el reconocimiento de manos no se inicia.
