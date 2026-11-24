# QuickView 1.0.4: descripción

## Análisis

QuickView es un visor rápido de archivos para KDE Plasma, a la manera de Quick Look en macOS: se selecciona un archivo en Dolphin, se pulsa la barra espaciadora y un panel lo muestra de inmediato, sea lo que sea (una foto, un PDF, un documento de Word, un libro EPUB, un video, código fuente, un archivo comprimido); otra pulsación lo cierra. Mustapha Alioglou escribió las primeras versiones entre junio y octubre de 2026. Nicolas Vaughan hizo una bifurcación (fork) en noviembre de 2026, que es el programa aquí descrito y que llegó a la versión 1.0 el 19 de noviembre de 2026. QuickView es software libre, bajo la Licencia Pública General de GNU, versión 3 o posterior.

Los requisitos venían de la costumbre de Quick Look. El panel tenía que aparecer en una fracción de segundo, sin abrir ningún programa, y desaparecer con la misma tecla. Tenía que servir para casi todo lo que hay en una carpeta, y mostrar cada cosa como es: las páginas de un PDF o de un documento de oficina con su aspecto real, el código con colores, un libro con su tabla de contenido. Con varios archivos seleccionados, las flechas debían recorrerlos, y una cuadrícula mostrarlos todos a la vez. El texto de las páginas tenía que poder seleccionarse y copiarse, y la vista ampliarse con el teclado o la rueda del ratón.

Había un requisito menos visible y más importante. Un visor que abre de un vistazo cualquier archivo que llegue al disco (un adjunto, una descarga) es una superficie de ataque: un PDF o una imagen hechos para explotar un error de su decodificador no deben poder comprometer la sesión del usuario. De ahí que ningún archivo se lea en el proceso principal.

Por último, en Plasma tenía que funcionar sin configuración: instalar el paquete debía bastar para que la barra espaciadora abriera la vista previa en Dolphin, sin pisar ningún atajo que el usuario hubiera elegido.

## Diseño

El programa tiene tres partes. Un cliente pequeño, escrito en Rust, recibe de Dolphin la ruta del archivo y se la pasa por un socket Unix a un demonio en Python (PySide6), que mantiene Qt cargado y dibuja el panel. El demonio no analiza ningún archivo: abre cada uno una sola vez y entrega su descriptor a un proceso trabajador (worker) que corre dentro de una jaula de bubblewrap, sin red, sin la carpeta personal y con el sistema en solo lectura. El trabajador decodifica el archivo y devuelve píxeles o texto, y el demonio revisa todo lo que recibe antes de usarlo, como si viniera de un desconocido, porque el trabajador es el proceso que acaba de leer un archivo quizá hostil.

El panel es una ventana hecha de piezas (mixins), una por tipo de vista: `view_image.py`, `view_document.py` (páginas de PDF, libros y Markdown), `view_office.py`, `view_text.py`, `view_media.py`, `view_selection.py` (la selección de texto), `view_zoom.py` y `view_index.py` (la cuadrícula). Los decodificadores están en el paquete `renderers/`, y `worker.py` reúne en una tabla las operaciones que un trabajador sabe hacer. `sandbox.py` lanza la jaula y reparte los trabajos.

Las páginas ya dibujadas se guardan en una caché en disco, con el archivo, su fecha y su tamaño como clave, y las imágenes decodificadas en una caché en memoria. El demonio lo arranca systemd con la primera pulsación, mediante un socket siempre abierto, y puede salir cuando lleva un rato sin uso; la configuración vive en `~/.config/quickview/quickview.conf` y se aplica en cuanto se guarda.

Para Dolphin hay dos piezas más. `dolphin_shortcut.py` escribe el atajo en la copia de la configuración de Dolphin del usuario, y `dolphin_watch.py` es un servicio pequeño que avisa cuando Dolphin lo pierde. El aviso es una notificación crítica, que Plasma deja en pantalla hasta que se responde; si el atajo vuelve a perderse mientras espera, se reemplaza por uno nuevo (hasta la versión 1.0.1, el vigilante callaba mientras hubiera un aviso sin responder en el historial).

## Implementación

Está escrito en Python 3.15 o posterior, con PySide6 (Qt 6, LGPL 3.0), cuyo módulo QtPdf dibuja los PDF con PDFium; Pygments colorea el código, y el cliente rápido está en Rust, con solo su biblioteca estándar. La lista completa del software libre que usa, con sus licencias, está en `docs/THIRD-PARTY.md`. El repositorio tiene 102 archivos y unas 23 000 líneas, de las cuales unas 7400 son pruebas.

### La jaula y lo que sale de ella

Cada trabajo abre el archivo sin bloquearse y rechaza lo que no sea un archivo regular, porque una tubería con nombre (FIFO) llamada `a.txt` esperaría para siempre a quien escriba en ella. Las páginas vuelven como PNG o JPEG, y el demonio solo decodifica esos dos formatos, nombrándolos: la detección automática de Qt habría entregado un PDF disfrazado de miniatura a PDFium dentro del proceso principal. LibreOffice, que da la maquetación exacta de los documentos de oficina, corre dentro de la jaula, también en su versión Flatpak, con una segunda caja anidada.

### Seleccionar texto

Las páginas son imágenes, así que para seleccionar texto hay que saber dónde está cada palabra. En los PDF lo dice `pdftotext -bbox-layout`, de Poppler, en la jaula, unos 25 milisegundos por página; en Markdown, los libros y los documentos de oficina, el trabajador vuelve a maquetar el texto con el mismo ancho y la misma fuente con que se dibujó, o lee el PDF que LibreOffice hizo de él. El demonio verifica cada caja y cada desplazamiento (`text_select.py`).

### El atajo de Dolphin

Dolphin 26.08 olvida los atajos de los menús de servicio en sus ventanas abiertas cada vez que se aplican sus ajustes, aunque no cambien. La corrección llegará con Dolphin 26.12. Mientras tanto, QuickView devuelve la barra espaciadora al iniciar sesión y escucha en el bus de sesión las dos señales con que Dolphin anuncia esos momentos, para ofrecer reiniciarlo con una notificación.

### La página web

Las páginas HTML se muestran con Qt WebEngine, que las dibuja con Qt Quick, y eso pide dos cuidados. El filtro de eventos del zoom (Ctrl y la rueda) va en los widgets de la ventana, no en toda la aplicación: PySide envuelve en Python cada objeto cuyos eventos pasan por un filtro así, y al envolver los objetos internos de Qt Quick se caía. Y la sombra del panel, un `QGraphicsDropShadowEffect`, se apaga mientras se ve una página, porque el efecto compone una imagen del panel en la que falta el dibujo de Qt Quick, y la página salía en blanco. Ambos fallos se corrigieron en la versión 1.0.4.

## Validación

Hay 506 pruebas automáticas, en 34 archivos, que corren en unos doce segundos sin pantalla (las de Qt usan la plataforma `offscreen`); GitHub Actions las corre con cada push. Cubren el enrutamiento de cada tipo de archivo, los decodificadores, la jaula y la verificación de lo que devuelve, la caché, la configuración, la selección de texto, el zoom, la cuadrícula, el atajo de Dolphin y su vigilante, el paquete, el guion de publicación y la firma de una versión, esta con una clave hecha en la prueba y nunca con la del autor. Las pruebas del vigilante usan sustitutos y no envían nada al bus de sesión real, donde un vigilante instalado las oiría; las de LibreOffice se saltan donde no está instalado.

Varias pruebas reproducen fallos encontrados en una revisión completa del código antes de la versión 1.0: la miniatura falsa de una presentación, la tubería con nombre que congelaba el demonio, los nombres de archivo que no son UTF-8, una búsqueda lenta que pintaba sus resultados en el documento siguiente y respuestas malformadas del trabajador. Se comprobó, además, que esas pruebas fallaban con el código anterior. La vista HTML se revisó con capturas de la pantalla real, porque una imagen dibujada por Qt puede mostrar una página que la pantalla no muestra.

Las operaciones nuevas del trabajador se probaron dentro de la jaula real, con LibreOffice y sin él. Las vistas se revisaron a ojo, guardando imágenes del panel dibujado fuera de pantalla. El diagnóstico del atajo perdido salió de leer el código fuente de Dolphin, y el vigilante se probó contra un Dolphin en marcha sin cerrarlo.

## Plataforma

Funciona en Linux con KDE Plasma 6 y Dolphin; el paquete RPM es para Fedora 45 y Rawhide (x86_64), y en otras distribuciones se instala desde el código con `install.sh`. Necesita Python 3.15 o posterior, PySide6, Pygments, bubblewrap y systemd en modo usuario; sin systemd, el demonio arranca con la sesión gráfica. Son opcionales Poppler (`pdftotext`), para seleccionar texto más rápido en los PDF; LibreOffice, del sistema o de Flathub, para la maquetación exacta de los documentos de oficina; Rust, para compilar el cliente rápido, y `bsdtar`, `7z` o `unrar`, para listar los archivos comprimidos que no son zip ni tar.

No necesita internet. La jaula no tiene red, y el visor no hace ninguna petición fuera del equipo; las páginas HTML se muestran con JavaScript desactivado y sin cargar nada de fuera.

## Ambiente

Fue desarrollado en Fedora Linux 45 con KDE Plasma, Dolphin 26.08 y Python 3.15. El código se gestiona con git y se publica en GitHub (https://github.com/nivaca/QuickView) y en Codeberg (https://codeberg.org/nivaca/QuickView); el proyecto original de Mustapha Alioglou está en https://github.com/MustaphaAlioglou/QuickView. Cada versión se publica en los dos sitios con los RPM firmados con la clave de Nicolas Vaughan, la clave pública y un archivo Zip del programa, y se compila en Copr. Cada archivo publicado lleva además su firma aparte (`.asc`), junto con las sumas `SHA256SUMS` y su firma, y la etiqueta de la versión va firmada; `packaging/sign_release.py` comprueba cada firma con solo la clave publicada antes de que nada salga de la máquina.

En Fedora se instala con `sudo dnf copr enable nivaca/quickview` y `sudo dnf install quickview`; después, la barra espaciadora abre la vista previa en Dolphin (si Dolphin estaba abierto, hay que reiniciarlo). En otras distribuciones se descomprime el Zip o se clona el repositorio y se ejecuta `./install.sh`; `./uninstall.sh` lo deshace, atajo de Dolphin incluido. Los ajustes están en `~/.config/quickview/quickview.conf`, que también edita la ventana de configuración (`quickview --settings`), la caché en `~/.cache/quickview/` y el registro en `~/.local/share/quickview/`.

Para escribir a su autor: nicolasvaughan@proton.me.
