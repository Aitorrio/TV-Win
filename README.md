# TV-Win

**Televisión en abierto para Windows**, sin navegador, sin cookies de webs y sin publicidad de apps.

Desarrollado por **[Aitor Riolobos (EA4HBL)](https://github.com/Aitorrio)**.

El catálogo se obtiene de la misma fuente pública que usa [TDT Spain](https://www.tdtspain.com/). La reproducción usa un motor **mpv embebido** (no hace falta instalar reproductores aparte en la release).

## Descargar

Ve a [Releases](https://github.com/Aitorrio/TV-Win/releases) y descarga `TV-Win-windows-x64.zip`.

1. Extrae la carpeta  
2. Ejecuta `TV-Win.exe`  
3. Elige un canal (doble clic o *Ver canal*)

## Qué reproduce

| Tipo | Ejemplos | Cómo |
|------|----------|------|
| HLS directo | La 1, La 2, TRECE | mpv |
| Atresmedia | Antena 3, laSexta, Neox… | Streamlink → mpv |
| Mediaset | Cuatro, Telecinco, FDF… | HLS SSAI → mpv (anuncios de la cadena) |

Algunos canales pueden exigir IP en España (GEO).

## Controles

- `Enter` — ver canal  
- `Esc` — detener  
- `F5` — actualizar catálogo  

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

Al publicar un tag `v*` (por ejemplo `v1.1.0`), GitHub Actions:

1. Compila en Windows  
2. Embebe mpv  
3. Sube `TV-Win-windows-x64.zip` a la Release  

```bash
git tag v1.1.0
git push origin v1.1.0
```

## Aviso legal

TV-Win no aloja ni redistribuye emisiones: enlaza fuentes públicas de cada cadena / listas de TDT Spain. Respeta los términos de cada emisora. Uso personal / educativo.

## Licencia

MIT © Aitor Riolobos (EA4HBL)
