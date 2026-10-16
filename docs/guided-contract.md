# Contrato musical de lectura (D1)

`GuidedMode.snapshot()` devuelve una instantánea inmutable `GuidedSnapshot`:
`steps`, `index` (desde cero), `phase`, `finished`, `completed`, `batch_token`.
Ofrece `total`, `current`, `paused` y `progress` (pasos completos / total).
Al completar la canción, `index == total` y `current is None`. En espera inicial
o después de finalizar manualmente, puede existir `current`; el consumidor debe
consultar `phase` antes de habilitar entradas.

Cada `StepState` contiene la definición `SongStep`, `accepted_notes`, `index`,
`total` y `phase`. Expone `step_id`, `required_notes`, `relative_duration` en
pulsos, `position` desde uno, `paused`, `pending_notes`, `completed`, `progress`
parcial y `visual_notes`. Cada `VisualNoteState` tiene `step_id`, `note`,
`accepted` e `identity == (step_id, note)`. Las dos notas de un acorde comparten
paso y duración, pero nunca identidad. Las instantáneas no cambian al aceptar
notas ni reiniciar. Consultarlas no lee el reloj ni produce efectos secundarios.

`step_state(index)` permite consultar un solo paso. `steps`, `chart()`,
`current_note()`, `upcoming_note()` y `submit()` siguen disponibles.
`chart()` solo proyecta la melodía: no debe alimentar una vista de acordes.

## Entradas y diagnósticos

Usar **una** de `submit()` o `submit_result()` por evento, nunca ambas.
La primera devuelve el `GuideHit` histórico o `None`. La segunda devuelve
`SubmissionResult(reason, hit, state)`; `accepted` indica si existe un hit.
`state` describe el paso afectado después de procesarlo, incluso si ya terminó.
En rechazos describe el paso actual, o `None` después del final de la canción.

Motivos: `accepted`, `step_completed` (ambos aceptan una única nota),
`already_accepted`, `note_not_required`, `session_paused`,
`finger_pending_release`, `stale_batch`, `session_inactive`, `song_completed`.
La prioridad de rechazo es: pausa/inactividad/final de canción, token antiguo,
dedo sin liberar, nota ajena, nota ya aceptada. Así un evento antiguo no se
diagnostica como error musical del paso nuevo.

Capturar `batch_token` una vez por lote y pasarlo como `expected_step` en
**todos** sus eventos. Sin token se mantiene la API histórica, pero el controlador
no puede identificar sobrantes de otro lote. Inicio, pausa y reanudación invalidan
tokens; avanzar de paso también. Un token no sustituye el descarte de entradas
en cola al cambiar de modo, que deberá resolver la integración posterior.

Aprendizaje sigue sin límite temporal: acepta cualquier orden, conserva parciales
al pausar y avanza solo al completar el conjunto. La política de coordinación
existente no cambia: vencido el plazo, la siguiente nota requerida válida reinicia
el intento parcial. Consultar estados nunca vence intentos ni acepta notas.

El consumidor reproduce únicamente `result.hit.note` cuando hay aceptación.
GuidedMode no genera audio ni diagnostica fallos de reproducción o reconocimiento;
esos errores deben informarse desde sus respectivos componentes.

## Anatomía e integración pendiente

`NoteMapper.assignments_for_note(note)` devuelve una tupla de `NoteAssignment`
inmutables con `note`, `finger_id`, `hand` y `finger`. Deriva la información de
las asignaciones vigentes, sin otra tabla musical. Usa LEFT/RIGHT y
THUMB/INDEX/MIDDLE/RING/PINKY. Identificadores personalizados sin anatomía
reconocible tienen `hand` y `finger` en `None`. Una asociación personalizada
puede tener varios dedos para la misma nota; se devuelven todos.

D2 deberá consumir estas instantáneas para dibujar ambas barras, distinguir
aceptadas y pendientes y detenerlas en la línea de impacto hasta completar el
paso. Esta API no cambia animaciones, selector, cámara ni el piano libre.

## Consumidor visual D2

`NoteHighway.set_snapshot(snapshot, mapper=None)` consume el contrato completo;
no recibe el controlador ni usa `chart()`. Reenviar una aceptación parcial o una
pausa no reinicia el descenso. La fase de la instantánea gobierna el movimiento.
`bar_identities()` enumera las identidades pendientes de retirar, incluidas las
notas aceptadas de un paso todavía incompleto. `bar_rect(index, note)` consulta
cada barra; omitir la nota conserva la consulta histórica de la melodía.

Las notas de un paso comparten tiempo vertical y altura, mientras los centros y
anchos proceden de los carriles que MusicalScene obtiene de PianoWidget. Las
etiquetas traducen la anatomía de NoteMapper; no mantienen otra tabla musical.
La aceptación atenúa la barra, su iluminación y añade una marca. El índice de la
instantánea decide cuándo retirar el paso. El temporizador solo mueve la escena
hasta el paso actual, donde espera indefinidamente.

La entrada histórica `set_chart()` continúa disponible y limpia el contrato
visual anterior. La interfaz pública permanece en modo libre. D3 deberá enviar
instantáneas y eventos aceptados desde la integración, gestionar cambios de modo
y descartar lotes antiguos. La tarjeta de cámara conserva su posición actual;
su adaptación a posibles carriles futuros ocultos queda para esa integración.

## Integración pública D3

El selector del encabezado inicia en modo libre. MainWindow usa SessionController
para libre y crea GuidedMode de forma diferida al seleccionar guiado. Cada cambio
termina la sesión saliente y prepara una sesión en espera, sin reproducir música.
Cámara, reconocimiento, calibración, volumen y AudioEngine conservan sus instancias
(o valores). Las reglas de aceptación continúan separadas.

Cada llamada a `_handle_press_events` obtiene una sola vez el token de GuidedMode
antes de recorrer la tupla extraída de CameraWorker. Todos sus eventos comparten
ese token, incluso si un acierto completa el paso. Cada clic consulta un token
nuevo para su entrada individual. No se conserva un token entre invocaciones.
La deduplicación por dedo y timestamp precede a la aceptación musical.

Al cambiar de modo se drena la cola, se detienen sonidos y se limpian efectos.
Al iniciar/reanudar con cámara activa se marca además un límite monotónico para
rechazar eventos antiguos que lleguen tarde. Los dedos ya flexionados se pasan
al controlador y deben liberarse antes de una nueva aceptación.

Solo `_perform` despacha una nota aceptada: una llamada a audio, iluminación,
efecto de escena e historial. GuidedMode conserva la autoridad del progreso.
Su historial visual separado registra notas aceptadas, con tiempo descontando
pausas. Reiniciar pulsaciones reinicia el contador mostrado, no la partitura.

La franja superior del escenario guiado se reserva para cámara. La carretera
mantiene todo el ancho y sus carriles proceden del piano; ninguna barra puede
quedar debajo de la tarjeta. En libre se recupera la altura original sin barras.
D4 queda pendiente para validación con cámara real y ajustes de uso/rendimiento.

## Ajustes visuales D4

Las barras contienen únicamente la nota y una marca de aceptación. La anatomía
se muestra una sola vez en la indicación de notas pendientes del paso activo.
Las futuras tienen menor intensidad y las aceptadas permanecen atenuadas hasta
completar el paso. Un acierto temprano actualiza inmediatamente la instantánea.
El destello de barra es translúcido para no tapar su marca de aceptación.

La llegada automática solo detiene el descenso: no crea impactos, partículas ni
audio. Las reacciones líquidas se disparan por el despacho de notas aceptadas.
Se mantienen la iluminación ambiental y la luz de proximidad sin pulsaciones.

La cámara guiada usa un hueco entre los carriles de los ocho pasos de anticipación
cuando cabe. Si no hay espacio, reserva 180 píxeles de altura (tarjeta de 168 más
margen superior de 12). La geometría horizontal siempre procede del piano. La
ubicación se reevalúa al cambiar el paso o redimensionar; no sigue cada fotograma.
D5 deberá comprobar comodidad de estos cambios de posición, cámara real,
latencia percibida, rendimiento sostenido y lectura con diferentes pantallas.
