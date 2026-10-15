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

La ventana provisional abre la cámara, muestra el vídeo en directo y los FPS medidos. Todavía no hay reconocimiento de manos, gestos, piano ni sonido.

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

1. Pulsa **Iniciar cámara** para ver el vídeo y los FPS medidos.
2. Pulsa **Detener cámara** para liberar el dispositivo.
3. Cerrar la ventana también detiene la captura.

La cámara principal es el índice 0 y la resolución inicial es 640×480. Para usar otro dispositivo o pedir otra resolución:

```powershell
python -m fingermelody.main --camera 1
python -m fingermelody.main --width 320 --height 240
```

Si el controlador no admite el tamaño pedido, entrega la resolución más cercana. Los FPS que muestra la ventana se calculan con los fotogramas recibidos.

### Pruebas

```powershell
python -m pytest
```

`pytest` no abre la cámara: el dispositivo se simula. Para comprobar el vídeo real, ejecuta la aplicación y pulsa **Iniciar cámara**.

### Problemas habituales

- Si `python` no es 3.11, vuelve a crear el entorno con `py -3.11 -m venv .venv`.
- Si PowerShell bloquea `Activate.ps1`, ejecuta `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y activa el entorno de nuevo. También puedes llamar a `.venv\Scripts\python.exe` sin activarlo.
- No instales `opencv-python` ni `opencv-python-headless` junto a `opencv-contrib-python`. Esas distribuciones publican el mismo módulo `cv2`.
- No uses paquetes instalados en el Python global. El entorno virtual no los incluye.
- En Windows, permite el acceso a la cámara a las aplicaciones de escritorio en Configuración, Privacidad y seguridad, Cámara.
- Si la cámara está abierta en otra aplicación, ciérrala antes de iniciar la captura.
- Si el índice 0 no es la cámara del portátil, prueba `--camera 1`.
- En Windows se intenta primero DirectShow. Si ese backend no entrega imagen, la aplicación prueba el backend predeterminado.
