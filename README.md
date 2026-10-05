# PowerTips.es — archivo estático

Migración reproducible de WordPress a GitHub Pages, con **powertips.es** como dominio canónico. El sitio se genera desde el contenido y los medios incluidos en este repositorio; ni la compilación ni el navegador consultan la API de WordPress.

## Contenido conservado

| Inventario público (5 de octubre de 2026) | Resultado |
|---|---|
| Artículos | **283**, del 30/04/2013 al 19/08/2024; títulos, fechas, HTML completo, rutas originales con fecha y barra final |
| Páginas | **18** URL originales; 9 páginas dinámicas se sustituyen por avisos explícitos |
| Sitemaps de WordPress | 283 artículos y 19 URL de páginas, incluida la portada; coincidencia completa con la API y la portada generada |
| Taxonomías | **45 categorías y 231 etiquetas**, con archivos navegables |
| Medios necesarios | **259 archivos locales**, 64.135.095 bytes; ninguna descarga fallida |
| Vídeos y cursos | **170 embeds de YouTube y 15 de LinkedIn Learning**; dependen de la disponibilidad del proveedor |
| Adjuntos | Se conserva además la ruta de la página de adjunto enlazada por el artículo de Año Nuevo de 2013 |

La identidad y el lema son los originales: **PowerTips.es — Microsoft Power Platform, Modern Work, Dynamics 365 y más...** La portada, el archivo cronológico, los temas y la búsqueda están en español. Las antiguas páginas de demostración del tema (`home`, `about`, `courses`, `e-books`, `contact`, `sample-page`) estaban publicadas: conservamos sus rutas y su contenido en lugar de ocultarlas; no aparecen en la navegación principal. La página `about` no tenía texto público.

`content/` contiene las respuestas de contenido sin truncar, inventarios de medios/taxonomías, sitemaps originales y los informes [de importación](content/migration-report.json) y [de generación](content/build-report.json). No contiene comentarios, listas de usuarios ni los inventarios de temas/respuestas de los foros.

**Discrepancia de la API de medios:** `X-WP-Total` anuncia 345 adjuntos, pero las cuatro páginas de la API pública devuelven **339 registros distintos** (99, 95, 100 y 45, ordenados por ID). Se guardan los 339 disponibles; los seis restantes no exponen sus ID ni su contenido en esas respuestas públicas. No se atribuye una causa no verificable ni se accede a contenido privado. Los artículos y las páginas no presentan esa discrepancia. Hay **110 fuentes originales de adjuntos no referenciadas directamente**: se inventarían, pero no se descargan por defecto; un artículo puede utilizar una variante de imagen. Se copian las imágenes/archivos realmente enlazados y las imágenes destacadas, no todas las variantes de `srcset`.

## Límites de la versión estática

No hay comentarios, formularios, cuentas, perfiles, recuperación de contraseña, foros, preguntas/respuestas, administración ni shortcodes activos de WordPress. Se conservan avisos en `/foros/`, `/registro-2-2/`, `/recuperar-contrasena/` y las seis rutas `/questions/…`. Se retiran los formularios de `/contact/`, `/meetup/` y `/colaborar/`, con un enlace externo de contacto; el resto de esas páginas se mantiene. Las llamadas históricas a comentar dentro de los artículos pertenecen al texto original; un aviso aclara que los comentarios locales no están disponibles.

Los enlaces externos y sus recursos siguen en su proveedor original; los cursos pueden exigir acceso en LinkedIn. La nueva presentación mantiene el formato editorial, las imágenes, los vídeos y el logo, no el tema/plugins de WordPress. No se migran los sitemaps de foros, temas, respuestas, usuarios ni plantillas de Elementor.

Las rutas son directorios con `index.html`, incluidos los slugs con Unicode/emoji codificados. GitHub Pages sirve las barras finales y redirige las peticiones al directorio sin barra. JavaScript proporciona compatibilidad **del lado del cliente**, no redirecciones HTTP 301, para `?p=ID`, `?page_id=ID`, `?cat=ID` y rutas conocidas que llegan al 404. Las URL desconocidas muestran un 404 informativo. No se promete compatibilidad con todas las rutas de plugins ni los antiguos feeds de comentarios.

SEO: títulos/descripciones por página, canonical HTTPS, Open Graph, datos estructurados de artículos, sitemap, robots y RSS en `/feed/index.xml`. Las páginas dinámicas reemplazadas se marcan `noindex`. La búsqueda funciona sobre un índice local completo; con JavaScript desactivado siguen disponibles todo el archivo y las taxonomías.

## Compilar y comprobar

Requiere **Python 3.13**. Desde la raíz, con `python` disponible:

```text
python -m pip install -r requirements.txt
python scripts/build.py
python -m unittest discover -s tests -v
python -m http.server 8000 --bind 127.0.0.1 --directory _site
```

Visita `http://127.0.0.1:8000/`. `_site/` es generado y no se versiona. Las 13 comprobaciones cubren paginación, coincidencia API/sitemap, todos los permalinks, igualdad del texto íntegro de los artículos, embeds, imágenes, enlaces internos, búsqueda, eliminación de funciones dinámicas, sitemap y compatibilidad por ID.

Para actualizar deliberadamente la copia desde el WordPress público:

```text
python scripts/import_wordpress.py
python scripts/build.py
python -m unittest discover -s tests -v
```

La importación necesita conexión; la compilación y las comprobaciones son locales. Revisa los cambios en `content/` y `assets/media/` antes de confirmarlos. El importador reintenta errores de red, verifica los totales de artículos/páginas y los sitemaps, falla ante registros duplicados/cambios de inventario y registra explícitamente cualquier descarga fallida o discrepancia de medios. El nuevo informe de generación queda en `_site/build-report.json`; copia ese archivo a `content/build-report.json` al actualizar el snapshot. Los archivos locales ya descargados se reutilizan: si WordPress reemplaza un archivo conservando su URL, elimina **solo ese archivo identificado en `content/media-map.json`** antes de reimportar para actualizarlo.

## Publicación y dominio: pasos manuales pendientes

**No se han cambiado ajustes de GitHub ni registros DNS. El cambio de dominio todavía no se ha realizado.**

1. Publica/integra esta rama en `main`. En el repositorio, configura **Settings → Pages → Source: GitHub Actions**. El workflow `.github/workflows/pages.yml` compila y comprueba, sube `_site` con `upload-pages-artifact` y despliega desde `main` con `deploy-pages`. Las PR solo compilan; no despliegan. Si existe protección del entorno `github-pages`, aprueba el despliegue cuando corresponda.
2. Verifica la propiedad del dominio en GitHub y configura **Custom domain: `powertips.es`** antes de cambiar DNS. Se incluye `CNAME` en la raíz y en el artefacto, pero con despliegue mediante Actions **no sustituye** el ajuste manual del dominio.
3. Cuando la versión estática esté revisada y preparada para el corte, configura en el proveedor DNS los cuatro registros `A` del dominio raíz (`@`):

   | Tipo | Nombre | Destino |
   |---|---|---|
   | A | @ | `185.199.108.153` |
   | A | @ | `185.199.109.153` |
   | A | @ | `185.199.110.153` |
   | A | @ | `185.199.111.153` |
   | CNAME | www | `mllorcag.github.io` |

   Alternativamente, el proveedor puede usar `ALIAS`/`ANAME` para el apex hacia `mllorcag.github.io`. IPv6 opcional: los cuatro `AAAA` son `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153`. Sustituye los registros web incompatibles, **no** los de correo (`MX`/TXT). Evita comodines DNS.
4. Espera la propagación y el certificado de GitHub, activa **Enforce HTTPS** y comprueba portada, artículos antiguos con emoji, páginas, búsqueda y el redireccionamiento de `www` al apex. Conserva una copia de seguridad de WordPress antes de retirarlo.

Las rutas absolutas y canonical están diseñadas para el dominio raíz `powertips.es`, no para una previsualización bajo `/powertips.es/` en `github.io`; utiliza la vista previa local antes del corte.

Referencias oficiales: [publicación con Actions](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [dominios y DNS](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site), [verificar el dominio](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages).
