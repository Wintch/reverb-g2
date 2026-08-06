# 08 — Passthrough y límites de juego (idea, no empezado)

**Estado: anotado el 2026-08-04. Nada implementado.** No tocar hasta cerrar el 90Hz (cap. 04).

## La idea

Dos cosas relacionadas, pedidas por el usuario:

1. **Passthrough**: tomar el video de las cámaras del casco y reproyectarlo adentro, como el
   modo del Quest donde ves el ambiente para no chocarte mientras arranca un juego, o cuando
   te acercás a una pared.
2. **Límites**: que el sistema sepa dónde están las paredes. La idea propuesta fue **leer
   marcas** puestas en el ambiente.

## Por qué acá es plausible

Buena parte del andamiaje ya está en el rig:

- El G2 tiene **4 cámaras** de tracking, y el driver WMR de Monado ya las levanta
  (`WMR_CAMERAS=1`; hoy corremos con `0` porque se midió que apagarlas no cambia el 90Hz,
  cap. 06).
- Monado ya parsea la **calibración del casco** que viene en su firmware — la usa para el
  tracking. Los intrínsecos/extrínsecos de las cámaras salen de ahí, no hay que calibrar a
  mano.
- Ya tenemos un **player propio** (`hello_xr` parcheado, cap. 02) con pipeline de texturas y
  proyecciones, que es más de la mitad del trabajo de mostrar algo dentro del casco.

## Expectativa realista de las cámaras

Antes de entusiasmarse, esto no va a verse como el Quest 3:

- Las cámaras del G2 son **monocromáticas**, para tracking, no a color. **El passthrough va
  a ser en blanco y negro.** No hay forma de sacarle color a un sensor que no lo capta.
- Son de **gran angular / ojo de pez**, y están separadas más que los ojos y apuntando hacia
  afuera. Reproyectar eso a la posición real de cada ojo no es pegar dos imágenes: hay
  distorsión y paralaje que corregir.
- Resolución y framerate: **verificar antes de diseñar nada.** El plan más rápido es
  levantar Monado con `WMR_CAMERAS=1` y mirar qué formato y qué fps reporta. Si las cámaras
  van a 30 fps y el panel a 90, el passthrough va a ir a saltos y hay que decidir si se
  interpola o se acepta.

Para el propósito real —**no chocarte**— nada de esto es descalificante. B/N, con algo de
distorsión y a 30 fps, alcanza perfectamente para ver dónde está la mesa.

## Caminos, en orden de dificultad

### v0 — Ver las cámaras, sin reproyectar (no depende de nada pendiente)

Mostrar el stream crudo en una capa plana dentro del casco, tipo "ventana flotante". Feo pero
útil, y sirve para medir qué dan las cámaras de verdad. **Es lo único de esta lista que se
puede hacer hoy**, porque no necesita 6DoF ni corrección de paralaje.

### v1 — Passthrough estéreo reproyectado

Las dos frontales → un ojo cada una, con undistort y reproyección usando la calibración del
firmware. Sin información de profundidad hay que asumir un plano a distancia fija: los
objetos a esa distancia se ven bien, los cercanos "nadan". Es lo que hacían los passthrough
de primera generación y es aceptable para orientarse.

### v2 — Límites por marcadores

**El camino más realista para lo que pediste, y por lejos el más barato.** Marcadores
fiduciales (ArUco / AprilTag) impresos y pegados en las paredes: se detectan muy bien con
cámaras B/N de baja resolución, dan pose completa (posición + orientación) por marcador, y
la detección es código maduro y liviano. Con tres o cuatro marcadores por pared, definís el
volumen jugable sin SLAM denso.

La alternativa "sin marcas" —reconstruir el ambiente y detectar planos— necesita SLAM denso y
es otro proyecto entero. **Tu instinto de usar marcas es el atajo correcto.**

## Idea parqueada (2026-08-06): un frontend/shell propio dentro del casco

Pedido del usuario, referencia Johnny Mnemonic: un "sistema operativo" o shell 3D dentro del
visor — navegar un directorio y abrir videos desde ahí, en vez de lanzar `play360.sh` a mano
desde una terminal. **Sin investigar todavía** qué existe ya para Linux/Wayland/OpenXR de lo
que agarrarse (compositores VR embebidos, shells Wayland para XR, cosas tipo lo que ya
encontramos hoy investigando players — `xr-video-player`, etc. — pero para un file browser en
vez de un solo video). Retomar como su propia sesión de research antes de diseñar nada.

## La dependencia que hay que mirar de frente

**v1 y v2 necesitan 6DoF, y el 6DoF hoy no funciona.** Basalt diverge (cap. 03 y 06) y todo
el trabajo de 360/video se hace en modo `3dof`. Sin posición de la cabeza no podés reproyectar
correctamente ni saber a qué distancia estás de una pared.

O sea que el orden real es: **90Hz → 6DoF estable → passthrough reproyectado**. La v0 se
puede colar antes, y de hecho conviene, porque contesta barato las preguntas de formato,
resolución y latencia que hacen falta para diseñar el resto.

## Primer paso concreto cuando se retome

```bash
# Levantar con cámaras y ver qué reportan de verdad (formato, resolución, fps)
cd ~/vr && WMR_CAMERAS=1 XRT_COMPOSITOR_LOG=debug ./jack-in.sh 3dof
grep -iE "camera|stream|format|fps" ~/vr/jack-in.log
```

Anotar acá lo que salga. Todo el diseño de arriba depende de esos números, y hoy son
suposiciones.
