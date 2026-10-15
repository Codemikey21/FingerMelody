# Jingle Bells: controlador interno aislado

Este documento conserva el contrato del controlador guiado y el arreglo probado.
Ya no están disponibles en la interfaz pública, que usa exclusivamente
SessionController. Las referencias posteriores al despacho describen la
integración histórica retirada, no funcionalidades de la aplicación actual.

El arreglo aprobado conserva 49 pasos y 58 pulsos relativos. Hay 21 pasos
individuales y 28 díadas, siempre con una nota de cada mano. Se interpretan
45 notas izquierdas y 32 derechas. El mapeo de dedos no cambia.

Las frases 1, 2, 7 y 8 son E5, E5, E5 (duraciones 1, 1, 2), con C4 en la
primera posición y G4 en la tercera. Las demás frases conservan la melodía
izquierda y los acompañamientos aprobados. La primera nota de cada SongStep
es siempre la melodía. La prueba de arreglo enumera las doce frases completas.

## Contrato musical

- `SongStep(id, notes, beats)` describe un paso inmutable. `SongNote(note, beats)`
  sigue aceptándose como entrada de una sola nota; recibe un identificador al
  normalizar la canción.
- `step_state()` devuelve una instantánea con definición, notas aceptadas,
  pendientes, estado individual, progreso 0..1 y finalización.
- `GuideHit` representa exclusivamente una nueva nota aceptada. `index`
  identifica su paso; `progress` cuenta pasos completos; `step_complete`
  distingue un acierto parcial. El consumidor reproduce `hit.note` una vez.
- `press_count` cuenta notas aceptadas, incluidas las de intentos de coordinación
  que posteriormente expiran. Completar un conjunto nunca vuelve a emitir notas.
- La duración musical no es una exigencia de sostener el gesto ni una modificación
  de la duración del sonido. El controlador no importa Qt, cámara ni audio.

## Aprendizaje (predeterminado)

No hay plazo. Las notas del paso pueden llegar en cualquier orden. Una nota ya
aceptada se ignora hasta el siguiente paso. Pausar conserva la aceptación parcial;
reanudar suprime los dedos flexionados hasta que se abran. Reiniciar borra todo
el progreso y el contador.

## Coordinación

Configurar `GuidedMode(coordination_mode=COORDINATION, window_ms=450)`.
El reloj monotónico inyectable mide el tiempo de recepción en el controlador.
El límite se incluye: una nota a exactamente 450 ms es válida.

La primera nota válida abre el plazo. Si llega una nota requerida y no suprimida
después del plazo, se descarta la aceptación parcial y esa nota abre un nuevo
intento. Los eventos incorrectos no abren ni extienden ventanas. No hay un
temporizador que emita sonidos o avance pasos. Las instantáneas conservan el
intento anterior hasta esa siguiente entrada válida; no implican vigencia temporal.
Repetir una nota tras expirar puede sonar otra vez porque inicia un intento nuevo,
no porque se reproduzca automáticamente un sonido pendiente.

Pausar cancela el intento parcial. Reanudar exige pulsaciones nuevas y conserva
la protección de dedos flexionados. Finalizar cancela el intento pendiente.

## Lotes y compatibilidad visual

El despachador captura `batch_token` una vez por lote de gestos y lo pasa como
`expected_step` a cada entrada. Al completarse el paso, el resto del lote se
rechaza. Inicio, pausa, reanudación y finalización invalidan tokens anteriores.
La deduplicación de eventos de cámara sigue en MainWindow; los clics son entradas
individuales. El audio continúa en la misma ruta, sin reproducción al cerrar acordes.

Este bloque no modifica el diseño ni los widgets de barras. `chart()`,
`current_note()` y `upcoming_note()` conservan su proyección de una sola nota
melódica para los consumidores antiguos. Por ello, la interfaz todavía no muestra
las dos notas requeridas ni su aceptación parcial: esa visualización corresponde
al Bloque D. No se incorpora aún el selector de modo libre (Bloque C).
