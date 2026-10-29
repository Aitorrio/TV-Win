# TV-Win

**Televisión en abierto para Windows**, sin navegador, sin cookies de webs y sin publicidad de apps.

Desarrollado por **[Aitor Riolobos (EA4HBL)](https://github.com/Aitorrio)**.

El catálogo se obtiene de la misma fuente pública que usa [TDT Spain](https://www.tdtspain.com/). La reproducción usa un motor **mpv embebido** (no hace falta instalar reproductores aparte en la release).

## Descargar

Ve a [Releases](https://github.com/Aitorrio/TV-Win/releases):

| Canal | Tag | Rama |
|-------|-----|------|
| **Estable** | [`latest-stable`](https://github.com/Aitorrio/TV-Win/releases/tag/latest-stable) | `main` |
| **Beta** | [`latest-beta`](https://github.com/Aitorrio/TV-Win/releases/tag/latest-beta) | `beta` |

1. Extrae la carpeta  
2. Ejecuta `TV-Win.exe`  
3. Elige un canal (doble clic o *Ver canal*)

La app puede comprobar y aplicar actualizaciones sola (Ajustes → canal Estable/Beta).

## Qué reproduce

| Tipo | Ejemplos | Cómo |
|------|----------|------|
| HLS directo | La 1, La 2, TRECE | mpv |
| Atresmedia | Antena 3, laSexta, Neox… | Streamlink API → DASH/HLS → mpv |
| Mediaset | Cuatro, Telecinco, FDF… | HLS SSAI → mpv (anuncios de la cadena) |

Algunos canales pueden exigir IP en España (GEO).

## Controles

| Tecla | Acción |
|-------|--------|
| `Enter` | Ver canal |
| `Esc` | Detener |
| `F5` | Actualizar catálogo |
| `F` | Marcar / quitar favorito |
| `F11` | Pantalla completa (mpv) |
| `PgUp` / `PgDn` | Canal anterior / siguiente |
| `Ctrl` + `,` | Ajustes |

También: filtro **Favoritos**, clic en ★/☆ de la lista y bandeja del sistema (opcional en Ajustes).

## Desarrollo

Requisitos: Python 3.12+, Windows.

```bat
python -m pip install -r requirements.txt
```

Coloca `mpv.exe` en `player\` (o genera el portable) y ejecuta:

```bat
run.bat
```

Portable local:

```bat
build_portable.bat
```

## Release automática

- Push a **`main`** → release rolling **`latest-stable`**
- Push a **`beta`** → release rolling **`latest-beta`** (prerelease)

Cada build embebe mpv, iconos y `version.txt`. El cuerpo de la release incluye el marcador de versión para el actualizador in-app.

## Aviso legal

TV-Win no aloja ni redistribuye emisiones: enlaza fuentes públicas de cada cadena / listas de TDT Spain. Respeta los términos de cada emisora. Uso personal / educativo.

## Licencia

MIT © Aitor Riolobos (EA4HBL)
