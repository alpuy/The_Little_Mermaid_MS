# The Little Mermaid — port NES → Sega Master System

Port de *The Little Mermaid* (Capcom, NES) a Sega Master System mediante **recompilación estática 6502 → Z80**
a partir del desensamblado de [cyneprepou4uk/NES-Games-Disassembly](https://github.com/cyneprepou4uk/NES-Games-Disassembly/tree/main/The%20Little%20Mermaid).
Comparte el traductor con el [port de MSX2+](https://github.com/alpuy/The-Little-Mermaid---MSX).

## Estado
- El juego completo funciona: un TAS de la NES (24.278 lecturas de mando) se reproduce **sincronizado de principio a fin**.
- Modo de vídeo de **224 líneas** (Master System II): se ven 224 de las 240 líneas de la NES (8 arriba y 8 abajo recortadas).
- Scroll horizontal y vertical, sprites con sus 4 paletas y volteos, paletas convertidas a los 64 colores de la SMS.
- Sonido por el **PSG SN76489**: pulso 1 → tono 0, pulso 2 → tono 1, triángulo → tono 2, ruido → canal de ruido.
  Se usa el motor de sonido original del juego (la música va a tiempo real).
- Velocidad: ~42 fps de lógica (el original va a 60).

## Requisitos
- **Master System II** (o compatible con el modo de 224 líneas). En una Master System I el modo de 224 líneas no existe.
- Cartucho con **RAM** (mapper Sega con RAM en el slot 2, como los de juegos con batería; los flash carts habituales lo soportan):
  se usa para guardar la CHR-RAM de la NES y las cachés de patrones.

## Controles
Cruceta = cruceta, botón 1 = B, botón 2 = A, PAUSE = Start.

## Diseño
- **Mapa de memoria**: página 0 de ROM (slot 0) = banco fijo de la NES (datos leídos por el juego) con los vectores de la SMS
  sobre bytes que sólo eran código; bancos 00-06 de la NES sin modificar en el slot 2; código traducido en el slot 1.
  La RAM de la NES va en `C000h`; las direcciones se traducen en la recompilación y los punteros `(zp),Y` en tiempo de ejecución.
- **Runtime** en `src/`: una copia idéntica al final de cada página de código (así está siempre visible aunque se cambie de página).
- **PPU → VDP modo 4**: las 4 paletas de fondo de la NES se combinan en la paleta 0 de la SMS (color = 3·paleta + píxel) y las de
  sprites en la paleta 1. Cada celda usa un patrón generado para su par (tile, paleta), con caché y contador de referencias.
  La tabla de nombres de 32×32 contiene las 32 columnas visibles de las 64 de la NES y las 30 filas en 32 (dos filas libres que se
  mueven con el scroll vertical). Los sprites, que en la SMS no pueden voltearse, usan patrones generados por (tile, paleta, volteos).
- `tools/translate.py`: traductor 6502 → Z80 con análisis de flags; `tools/placement.json`: reparto del código en páginas.
- Algunas rutinas muy usadas tienen versión nativa Z80 (`src/rt_native.asm`).

## Compilar
Requiere `python3`, `cc65` (ca65/ld65) y `sjasmplus`.
```
NESSRC="/ruta/NES-Games-Disassembly/The Little Mermaid" ./build.sh
```
Genera `build/mermaid.sms`. El ROM no se distribuye en este repositorio.

### Pruebas
`test/smsemu.py` controla el núcleo Genesis Plus GX (libretro) desde Python; `test/gpgx_debug.patch` añade al núcleo
contadores, traza y perfilador para las pruebas.
- `TAS=tas/tas1.bin ./build.sh` y `python3 test/tas_check.py build/mermaid.sms` comprueban la sincronización con el TAS
  (el flujo de entradas y la referencia se generan con `tools/tas_reads.py` / `tools/tas_ramlog.py`, ver el port de MSX).
- `python3 test/perf.py` mide la velocidad; `python3 test/prof.py rom A B` perfila el tramo entre las lecturas A y B del TAS.
