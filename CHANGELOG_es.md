# Registro de cambios

Los cambios notables de QuickView. El formato sigue [Keep a
Changelog][kac]; el proyecto todavía no tiene etiquetas de versión, así que
las entradas llevan fecha.

[kac]: https://keepachangelog.com/en/1.1.0/

## Sin publicar

### Cambios

- **Las entradas del menú de Dolphin, en un submenú.** Quick Look y
  QuickView Settings están ahora en el submenú **Folder tools** del menú
  contextual de Dolphin, no en su primer nivel. El atajo de la barra
  espaciadora no cambia.

## 1.0.4 — 2026-11-24

### Correcciones

- **Sin caídas al pasar el ratón sobre una página web.** El demonio se
  caía (SIGSEGV) en cuanto el ratón pasaba sobre una vista previa HTML.
  El zoom con Ctrl+rueda vigilaba todos los eventos de la aplicación,
  así que PySide tenía que envolver cada objeto que recibía uno, también
  los elementos internos de Qt Quick de la vista web, y al envolverlos
  se caía (con PySide 6.11 y con 6.12). Ahora el zoom vigila solo los
  widgets de la ventana de vista previa; Ctrl+rueda funciona como antes.
- **Las vistas previas HTML vuelven a mostrar la página, no un panel en
  blanco.** Una página web la dibuja Qt Quick, y la sombra del panel
  (`QGraphicsDropShadowEffect`) no sabe componerla, así que la página
  quedaba en blanco. La sombra se apaga mientras se ve una página HTML y
  vuelve con el archivo siguiente.

## 1.0.3 — 2026-11-22

### Cambios

- **Cada versión firmada.** Además de los RPM, cada archivo que se
  adjunta a una versión (los dos RPM y el Zip) va con su firma aparte
  (`.asc`), con `SHA256SUMS` y su firma, y con la clave pública; la
  etiqueta de la versión también va firmada (`git tag --sign`).
  `packaging/release.py` comprueba cada firma con solo la clave publicada
  antes de que nada salga de la máquina, y otra vez en los archivos
  descargados de GitHub. El README explica cómo comprobar una descarga.

## 1.0.2 — 2026-11-21

### Correcciones

- **El vigilante de Dolphin ya no se queda callado tras un aviso sin
  responder.** Mostraba un aviso a la vez, y en Plasma una notificación
  con un botón sigue esperando después de que su ventanita pasa al
  historial; mientras nadie la respondiera allí, cada nueva pérdida del
  atajo Espacio de Dolphin pasaba sin aviso. Ahora una pérdida nueva
  reemplaza el aviso pendiente por uno nuevo.

### Cambios

- El aviso del vigilante de Dolphin es una notificación crítica, así que
  Plasma la deja en pantalla hasta que se elige **Restart Dolphin** o
  se cierra.

## 1.0.1 — 2026-11-21

### Nuevo

- **El software libre que usa QuickView, con sus licencias**, en
  `docs/THIRD-PARTY.md`: lo que necesita para funcionar, lo que usa si
  está instalado y lo que sirve para construirlo y publicarlo.

## 1.0.0 — 2026-11-19

QuickView 1.0. Además de lo que se enumera abajo, todo el programa se
revisó antes de esta versión, y aquí se corrigen los problemas que
aparecieron. El README y `docs/` (DESCRIPTION.md y DESCRIPCIÓN_es.md,
nuevos) cuentan cómo funciona y cómo se hizo.

### Nuevo

- **Una hoja índice para una selección de varios archivos**, como en
  Quick Look: el botón **▦** de la barra de título, o Ctrl+Enter, muestra
  cada archivo seleccionado como miniatura; las flechas se mueven entre
  ellos, y Enter o un clic abre uno. Las miniaturas salen de la caché de
  freedesktop que llena Dolphin (leídas solo como PNG, y solo mientras
  coincidan con la fecha de modificación del archivo) o, para las
  imágenes, de la jaula; los demás archivos muestran el icono de su tipo.
- **Seleccionar y copiar texto en documentos de oficina** (Word,
  LibreOffice y los formatos antiguos que LibreOffice abre), como en los
  PDF: a partir del PDF que LibreOffice hace del documento, o de la
  maquetación propia de QuickView, según cuál haya dibujado las páginas
  (nueva operación del trabajador, `officetext`). El texto de todas las
  páginas vuelve de una sola conversión, así que solo la primera pulsación
  lo espera.
- **QuickView nota cuándo Dolphin pierde el atajo de Espacio.** Dolphin
  26.08 olvida el atajo en sus ventanas abiertas cada vez que se aplica
  Configure Dolphin (aunque no haya cambiado nada) o cambian sus ajustes
  del menú contextual, y solo un reinicio lo recupera. Un pequeño servicio
  en segundo plano, `quickview-dolphin-watch`, escucha esos dos momentos
  en el bus de sesión y muestra una notificación con un botón **Restart
  Dolphin**, que cierra las ventanas de Dolphin como lo harían sus botones
  de cierre y lo vuelve a iniciar. Obedece el ajuste `dolphin_space`, y
  termina de inmediato con Dolphin 26.12 o posterior, que conserva el
  atajo.
- **Cómo se hizo QuickView**, en `docs/DESCRIPTION.md`, y una descripción
  en español, `docs/DESCRIPCIÓN_es.md`.

### Cambios

- **Cada compilación deja sus paquetes en `dist/`.** `build-rpm.sh`
  copia allí el RPM binario y añade un paquete Zip,
  `quickview-VERSION.zip`, con los mismos archivos que el tarball de
  fuentes bajo `quickview-VERSION/` (una vez descomprimido, está listo
  para `./install.sh`). Cada compilación reemplaza las anteriores; git no
  sigue `dist/`.
- **Las versiones traen el paquete Zip.** `release.py` adjunta
  `quickview-VERSION.zip` a las versiones de GitHub y Codeberg, con su
  suma de verificación, y las notas lo ofrecen para otras distribuciones.
- **También en Codeberg.** El repositorio y todas las versiones, desde la
  0.1.0, están también en <https://codeberg.org/nivaca/QuickView>, y cada
  versión nueva se publica tanto en GitHub como en Codeberg.

### Correcciones

- **Desinstalar le devuelve Espacio a Dolphin.** `uninstall.sh` ejecuta
  ahora `dolphin_shortcut.py --remove`, que saca las entradas de Quick
  Look de los ajustes de Dolphin y le devuelve Espacio al modo de
  selección; antes, Espacio quedaba asignado a una acción que ya no
  existía. Antes de `dnf remove`, hay que ejecutarlo a mano (véase el
  README).
- **El atajo de Dolphin cae en la sección correcta** de los ajustes de
  Dolphin cuando el archivo tiene más de un esquema de atajos.
- **Una copia en una carpeta con espacios se instala bien.** El paso de
  Dolphin de la unidad del socket partía esa ruta y fallaba en silencio,
  así que el atajo nunca se fijaba; ahora las unidades ponen sus órdenes
  entre comillas, e `install.sh` escapa la ruta para sed (`|`, `&`) y
  para systemd (`%`).
- **Buscar muestra solo la respuesta a la última búsqueda.** Una respuesta
  más lenta a una búsqueda anterior podía aparecer bajo la nueva consulta
  o, si el documento había cambiado, pintarse sobre el siguiente. También
  se descartan las coincidencias malformadas que manda el trabajador.
- **Los nombres de archivo que no están en UTF-8 se previsualizan** (un
  `café.png` en Latin-1, por ejemplo). La clave de la caché codificaba el
  nombre de forma estricta y lanzaba una excepción, así que el panel nunca
  aparecía.
- **Una tubería con nombre ya no congela QuickView.** Un FIFO cuyo nombre
  terminaba en .txt, .zip, .md y otros se encaminaba por su nombre y se
  abría para lectura, lo que espera a que alguien escriba, en el hilo
  principal del demonio, para siempre. Ahora todo lo que no sea un archivo
  regular recibe la tarjeta de información, y la jaula abre los archivos
  sin bloquear y rechaza lo demás.

### Seguridad

- **El demonio decodifica solo PNG y JPEG.** Las páginas y los fotogramas
  de los trabajadores, las entradas de la caché en disco y la miniatura
  incrustada de un archivo de oficina se decodificaban con la detección de
  formato de Qt, de modo que, si la "miniatura" de una presentación era en
  realidad un PDF o un SVG, la analizaban pdfium o el dibujante de SVG
  dentro del demonio. Ahora cada una de esas decodificaciones verifica la
  firma PNG o JPEG y nombra ese decodificador; cualquier otra cosa se
  rechaza.
- **Se verifica antes de usarlo más de lo que mandan los trabajadores**:
  el nivel de una entrada del índice (uno enorme congelaba el demonio), un
  encabezado que no es un objeto, los mensajes y tiempos del reproductor,
  los tramos de color, los tamaños y cantidades de los archivos
  comprimidos, la demora entre fotogramas de una animación (0 hacía girar
  el temporizador sin parar) y una tabla de contenido en caché. Un mensaje
  del reproductor demasiado grande para leerlo termina ahora la vista
  previa con un error, en lugar de dejar controles muertos.

## 0.2.5 — 2026-11-14

### Cambios

- **Se requiere Python 3.15 o posterior**, en lugar de 3.13: `install.sh`
  lo comprueba, y el RPM lo exige (Fedora 45 y rawhide, las versiones para
  las que se compila, lo tienen).

## 0.2.4 — 2026-11-14

### Cambios

- **Se requiere Python 3.13 o posterior**, en lugar de 3.10: `install.sh`
  lo comprueba, y el RPM lo exige (todas las versiones de Fedora
  mantenidas tienen uno más reciente).

## 0.2.3 — 2026-11-13

### Cambios

- **El RPM nombra a su autor.** `rpm -qi quickview` y `dnf info
  quickview` muestran a Nicolas Vaughan como Packager y Vendor, en lugar
  de "Fedora Copr - user nivaca", de Copr, y ningún empaquetador.

## 0.2.2 — 2026-11-13

### Nuevo

- **Seleccionar y copiar texto en Markdown dibujado y en libros EPUB**,
  como en los PDF: arrastrar, hacer doble clic en una palabra, Ctrl+A,
  Ctrl+C, con cualquier zoom. La jaula vuelve a maquetar el texto
  exactamente como se pintaron las páginas y manda la caja de cada palabra
  (nuevas operaciones del trabajador, `mdtext` y `epubtext`), así que el
  demonio sigue sin analizar nada. Las líneas partidas se copian unidas;
  los párrafos, los elementos de lista y los encabezados, en líneas
  propias, y una fila de tabla como una sola línea, con tabuladores entre
  sus celdas. El texto plano, el código y los archivos org ya podían
  seleccionarse en su vista de texto.

## 0.2.1 — 2026-11-13

### Nuevo

- **"Espacio abre Quick Look" en Dolphin, y así se queda.** Un ajuste en
  QuickView Settings → Previews (`dolphin_space` en `[dolphin]`, activado
  por omisión). Dolphin 26.08 pierde los atajos de los menús de servicio
  cada vez que se aplican sus ajustes, y puede guardar esa pérdida en su
  archivo de interfaz; QuickView leía una entrada vaciada como elección del
  usuario y la dejaba así. Ahora, en cada inicio de sesión y al guardar la
  ventana de ajustes, Quick Look recupera Espacio (junto a cualquier otra
  tecla que tenga), y el modo de selección vuelve a quitarse de Espacio si
  ha regresado a su valor predeterminado. Si Espacio se asignó a otra
  acción de Dolphin, se sigue dejando en paz. Desactivado, QuickView ya no
  toca para nada los atajos de Dolphin, ni siquiera en la primera
  instalación.

## 0.2.0 — 2026-11-13

### Nuevo

- **Zoom.** Ctrl++ (o Ctrl+=) y Ctrl+- acercan y alejan, igual que la
  rueda del ratón con Ctrl pulsado; Ctrl+0 vuelve al 100 %. También
  funcionan + - 0 del teclado numérico, y los pequeños desplazamientos de
  un panel táctil se suman hasta dar un paso. El nivel aparece un momento
  en la parte inferior del panel, va en pasos del 25 % al 400 % y empieza
  en el 100 % con cada archivo.

  - Las imágenes se desplazan dentro del panel cuando están ampliadas. En
    cuanto una foto se muestra más grande de lo que se decodificó, la
    jaula la vuelve a decodificar a su nuevo tamaño (nunca más allá del
    original), de modo que se ve nítida y no estirada.
  - Los PDF, los documentos de oficina, los libros y el Markdown escalan
    sus páginas, y el punto bajo el puntero (o el centro de la vista) se
    queda quieto. Las páginas en pantalla se vuelven a dibujar entonces a
    la nueva resolución, hasta 4x; las que quedan fuera vuelven a sus
    píxeles normales, así que una lectura larga al 400 % no acumula
    imágenes de páginas. Los resaltados de Buscar y la selección de texto
    se escalan con las páginas, y seleccionar sigue funcionando con
    cualquier zoom.
  - El texto y el código, los listados de carpetas y de archivos
    comprimidos, el texto de oficina y las hojas de cálculo cambian el
    tamaño de su letra; las páginas HTML usan el zoom del propio
    navegador.

  El nivel se mantiene cuando se reconstruye la vista del mismo archivo,
  como cuando la maquetación exacta de un documento de oficina reemplaza
  la rápida.

## 0.1.9 — 2026-11-13

### Cambios

- **`build-rpm.sh --sign` firma siempre con la clave del proyecto:** la
  misma de `packaging/RPM-GPG-KEY-quickview`, en lugar de la primera clave
  secreta que tenga gpg. El script se detiene si la clave que firmó no es
  la de ese archivo.

## 0.1.8 — 2026-11-12

### Cambios

- **Las notas de las versiones y el README dan crédito a la bifurcación
  igual que el cuadro Acerca de:** "By Nicolas Vaughan (forked from the
  QuickView app by Mustapha Alioglou)".

## 0.1.7 — 2026-11-12

### Cambios

- **El cuadro Acerca de da crédito primero a la bifurcación:** "By
  Nicolas Vaughan (forked from the QuickView app by Mustapha Alioglou)".

## 0.1.6 — 2026-11-12

### Nuevo

- **Un botón About en la ventana de ajustes.** Muestra la versión de
  QuickView, sus autores (Mustapha Alioglou, y Nicolas Vaughan para esta
  bifurcación), enlaces a esta bifurcación y al proyecto original, la
  licencia, y las versiones de Qt y PySide6 en uso. La versión sale de un
  nuevo `version.py`, que `packaging/release.py` ahora fija junto con la
  del spec, y una prueba mantiene las dos al día.

## 0.1.5 — 2026-11-12

### Correcciones

- **Actualizar el RPM reinicia el demonio en marcha.** Antes seguía
  ejecutando la versión antigua hasta el siguiente inicio de sesión, así
  que una función nueva (seleccionar el texto de un PDF, en la 0.1.4)
  parecía faltar después de `dnf upgrade`. Ahora el paquete marca
  `quickview.service` para reiniciarlo, y systemd lo hace al final de la
  transacción para cada usuario con sesión abierta.

## 0.1.4 — 2026-11-12

### Nuevo

- **El texto de un PDF puede seleccionarse y copiarse, como en Quick
  Look.** Arrastrar sobre una página selecciona de palabra en palabra,
  también entre páginas, y la vista se desplaza cuando el puntero pasa de
  su borde; un doble clic selecciona una palabra; Ctrl+A selecciona todo y
  Ctrl+C copia. Un clic en otro sitio borra la selección, que también va a
  la selección primaria para pegar con el botón central. Las páginas
  muestran un cursor de texto.

  Las posiciones de las palabras salen de la jaula, como todo lo que se lee
  del archivo: una nueva operación, `pdftext`, ejecuta `pdftotext
  -bbox-layout`, de Poppler, sobre el descriptor recibido (unos 25 ms por
  página), con QtPdf como respaldo si Poppler no está instalado. El texto
  de una página se pide solo cuando una pulsación cae en ella. Los saltos
  de línea y de párrafo del texto copiado salen de las posiciones de las
  líneas, así que los elementos de una lista quedan en líneas seguidas y el
  número de un encabezado se queda con su título. El demonio valida cada
  posición y cada caja que recibe, y limita el texto que acepta. El RPM
  recomienda `poppler-utils`.

### Cambios

- **Una nueva clave de firma.** Los RPM de las versiones se firman ahora
  con la clave de Nicolas Vaughan
  `8187 0643 CA22 1AF9 0C30  554E BE68 32CD 3599 4948`, que reemplaza a
  `236E F043 AB7A 4434 A05C  A4EC B554 9099 FC0D 6464`.
  `packaging/RPM-GPG-KEY-quickview` y la clave adjunta a la versión son la
  nueva; quien instale los RPM descargados debe importarla otra vez
  (`sudo rpm --import RPM-GPG-KEY-quickview`). Los paquetes de Copr los
  firma la clave del propio Copr, y no cambian.

## 0.1.3 — 2026-11-11

### Nuevo

- **Espacio abre Quick Look en Dolphin sin configurar nada.** Un menú de
  servicio no puede llevar un atajo, así que `dolphin_shortcut.py` escribe
  uno en los ajustes de Dolphin del usuario
  (`kxmlgui5/dolphin/dolphinui.rc`); lo ejecuta `quickview.socket` cada vez
  que arranca (al iniciar sesión y al instalar) e `install.sh`. El modo de
  selección de Dolphin, que tiene Espacio por omisión, deja de tenerlo si
  todavía conserva ese valor predeterminado. Un atajo que el usuario
  eligió nunca se sobrescribe: un atajo de Quick Look ya existente (o uno
  borrado), o Espacio asignado a cualquier otra acción, dejan el archivo
  como está. Solo se edita la sección de atajos, el original se guarda una
  vez como `dolphinui.rc.before-quickview` y, si no hay archivo de
  ajustes, se escribe uno mínimo, que Dolphin amplía con el suyo. Se probó
  con un Dolphin 26.08 real en una sesión aislada.

- **`packaging/release.py VERSION` hace una versión completa.** Comprueba
  que el árbol esté limpio y al día con GitHub, que las herramientas
  tengan la sesión iniciada, que la clave de firma pueda usarse y que las
  pruebas pasen; convierte la sección "Unreleased" de este registro de
  cambios en la de la versión (y en la entrada `%changelog` del spec);
  hace el commit y la etiqueta; compila y firma los RPM con la clave
  publicada como `packaging/RPM-GPG-KEY-quickview`; publica la versión en
  GitHub, con notas hechas a partir del registro de cambios y sumas de
  verificación; comprueba las firmas de los RPM descargados como lo haría
  el `dnf` de un usuario, y compila en Copr, esperando hasta que cada
  chroot sirva la nueva versión. `--dry-run` muestra lo que haría y no
  cambia nada.

### Cambios

- **Los RPM de las versiones van firmados.** Los RPM adjuntos a la versión
  0.1.2 en GitHub se volvieron a firmar con la clave de Nicolas Vaughan
  (`236E F043 AB7A 4434 A05C  A4EC B554 9099 FC0D 6464`), cuya mitad
  pública está ahora en el repositorio como
  `packaging/RPM-GPG-KEY-quickview` y adjunta a la versión. Los paquetes de
  Copr ya venían firmados por Copr.

## 0.1.2 — 2026-11-11

### Nuevo

- **QuickView está en Copr.** En Fedora 45 y Rawhide,
  `sudo dnf copr enable nivaca/quickview && sudo dnf install quickview` lo
  instala como un paquete que Copr compila y firma, y `dnf upgrade` lo
  mantiene al día. La sección Install del README empieza ahora por ahí,
  antes de `install.sh` para otras distribuciones y de compilar el RPM uno
  mismo.

- **`packaging/build-rpm.sh --sign`** firma ambos RPM con OpenPGP, para que
  `dnf` pueda comprobar de dónde vienen en lugar de advertir que se saltó
  la comprobación. `--sign` usa la clave GPG predeterminada, `--sign=KEY`
  indica una; la clave pública se exporta como
  `build/rpm/RPM-GPG-KEY-quickview` para que la gente la importe. Luego
  cada paquete firmado se verifica como lo haría el `dnf` de un usuario,
  en un anillo de claves propio que solo tiene esa clave exportada, de modo
  que una clave equivocada o una firma fallida detienen la compilación. Si
  falta `rpm-sign` o la clave, se avisa antes de compilar.

### Correcciones

- **El error en cola de una tarea del trabajador ya no sobrevive a la
  tarea.** Cuando un archivo no podía abrirse o un trabajador no podía
  iniciarse, el error se informaba desde un temporizador de demora cero; si
  la ventana dueña de la tarea se borraba antes, el temporizador se
  ejecutaba igual y fallaba sobre la tarea borrada ("Internal C++ object
  already deleted"). Ahora los temporizadores están atados a la tarea, y Qt
  los descarta con ella. La única ventana del demonio vive tanto como el
  demonio, así que esto aparecía en las pruebas y no en el uso.
- **Las pruebas ya no ensucian `/tmp`.** `tests/test_config.py` creaba una
  carpeta temporal para cada prueba y nunca la borraba: quince por cada
  ejecución de las pruebas. Las pruebas que manejan una ventana con un
  trabajador de reemplazo también detienen su trabajo antes de que el
  reemplazo vuelva a cambiarse por el trabajador real.

## 0.1.1 — 2026-11-10

La entrada de abajo (el paquete no requiere cerrar sesión después de
instalarlo), y:

- **Avisos de la GPL-3 en los archivos de empaquetado.** El paquete ya era
  GPL-3.0-or-later (su etiqueta License y el texto de la GPLv3 que
  instala), pero el spec, el lanzador, las unidades de systemd y el preset
  llevan ahora también la cabecera de licencia del proyecto, como todos
  los archivos fuente.

## 2026-11-10 — sin cerrar sesión después de instalar el paquete

### Cambios

- **El lanzador del paquete pone en marcha el socket la primera vez que se
  usa.** Instalar el RPM habilita `quickview.socket` para todos los
  usuarios, pero el socket solo empezaba a escuchar en el siguiente inicio
  de sesión (el instalador corre como root, fuera de la sesión), así que
  hasta entonces cada vista previa recurría a un demonio que systemd no
  gestionaba, y que volvía a arrancar en frío después de cada salida por
  inactividad. Ahora, cuando nadie responde a la solicitud de un archivo,
  el lanzador mira si el socket está habilitado pero no escucha, lo pone en
  marcha (recargando una vez el systemd del usuario si todavía no ha visto
  los nuevos archivos de unidad) y vuelve a mandar la solicitud. Un socket
  deshabilitado se deja como está, opciones como `--settings` nunca tocan
  systemd, y sin systemd nada cambia.

## 2026-11-10 — un paquete RPM

### Nuevo

- **QuickView se compila como RPM** (`packaging/quickview.spec`, versión
  0.1.0), con `packaging/build-rpm.sh`, que lo deja en `build/rpm/`. El
  paquete funciona con el Python, el PySide6 y el Pygments del sistema,
  sin virtualenv, que era la parte de `install.sh` que se rompía cuando se
  copiaba una copia del repositorio sin su `pyvenv.cfg`. Instala el código
  en `/usr/share/quickview/`, compilado a bytecode de antemano porque la
  jaula lo ve en solo lectura; el cliente compilado en
  `/usr/libexec/quickview/`; un lanzador `/usr/bin/quickview`; el socket y
  el servicio como unidades de usuario de systemd, habilitadas para todos
  los usuarios por un preset, y las entradas de menú de la ventana de
  ajustes y de Dolphin. bubblewrap es obligatorio; las herramientas de
  archivos comprimidos y LibreOffice se sugieren.

### Cambios

- **Las unidades de systemd son archivos** (`packaging/quickview.socket`,
  `quickview.service.in`) y no texto dentro de `install.sh`, de modo que el
  paquete e `install.sh` instalan las mismas.

## 2026-11-10 — capturas de pantalla con un script

### Nuevo

- **`tools/screenshots.py` toma las capturas de pantalla del README.** El
  panel con la vista previa de un PDF, de una imagen y de un archivo
  fuente, el tema breeze con el índice de un PDF abierto y, como novedad,
  la ventana de ajustes, guardados en `docs/screenshots/` al doble del
  tamaño de la pantalla por omisión (`--scale`). QuickView corre en el
  propio proceso del script, en la plataforma offscreen de Qt, con una
  pantalla virtual de 1920×1200, así que nada aparece en pantalla y no
  hace falta un display; los ajustes, la caché y los registros son
  temporales, de modo que los del usuario no se tocan; y los archivos pasan
  por los verdaderos trabajadores enjaulados, así que las capturas muestran
  lo que QuickView dibuja. Las muestras salen de paquetes del sistema (el
  manual de Ghostscript si está instalado, si no el de hwloc, abierto en su
  primer capítulo, y el fondo de pantalla Next de KDE), y `--pdf`, `--page`
  e `--image` indican otras. La captura de breeze y la ventana de ajustes
  toman sus colores del archivo del esquema Breeze Dark de Plasma
  (`--scheme light` para Breeze Light), no del esquema actual del
  escritorio.

### Cambios

- **Las capturas de pantalla se rehicieron** con él: código actual, el
  botón ⚙, nítidas a 2×, y una de la ventana de ajustes en la sección
  Settings del README.

## 2026-11-10 — una ventana de ajustes, y tipos de letra

### Nuevo

- **Una ventana de ajustes.** Todos los ajustes de `quickview.conf`, en
  cinco pestañas (Appearance, Fonts, Previews, Background, que es el modo
  del demonio y su tiempo de inactividad, y Cache & logs), con OK, Apply,
  Cancel y Restore Defaults, un botón "Clear cache now" y un acceso directo
  a la carpeta de registros. Se abre desde **QuickView Settings** en el
  menú de aplicaciones, desde el menú contextual de Dolphin, desde un nuevo
  botón **⚙** en el panel y con `quickview --settings`. Es un proceso
  aparte, así que funciona sin que el demonio esté corriendo, y solo
  escribe el archivo: el demonio aplica lo que cambió, como con cualquier
  edición. Los límites y las opciones salen de `config.py`, de modo que no
  puede ofrecer un valor que el cargador rechazaría; señala los ajustes que
  una variable de entorno `QUICKVIEW_*` sobrescribe, y solo hay una
  ventana a la vez.
- **Ajustes de tipos de letra.** `[fonts] code_font` y `code_font_size`
  para los archivos fuente, `reading_font` y `reading_font_size` para los
  libros EPUB y el Markdown dibujado, y `ui_font_size` para el texto del
  propio panel (el título un paso por encima, la letra menuda un paso por
  debajo). Los valores predeterminados son exactamente los tipos de letra
  que se usaban antes. El tipo de lectura cambia dónde se cortan las
  páginas, así que las páginas de libros y de Markdown, y sus índices,
  cuyos números de página salen de la maquetación, se guardan en caché por
  tipo de letra, y la búsqueda en un libro maqueta con el mismo tipo para
  que las coincidencias caigan donde está el texto. Los nombres de los
  tipos de letra se reducen a letras, dígitos, espacios y `-_.` antes de
  entrar en una hoja de estilos, en el demonio y otra vez en la jaula.
- **`config.save()`** actualiza el archivo de ajustes en el sitio: los
  valores se reescriben donde están, los comentados vuelven a usarse, los
  nuevos se añaden a su sección y los comentarios se conservan; se escribe
  en un archivo temporal y se renombra, de modo que el demonio nunca lee
  la mitad.

## 2026-11-10 — el demonio a demanda

### Cambios

- **El demonio arranca a demanda y sale cuando está inactivo, como los
  servicios de Quick Look de macOS.** Antes arrancaba al iniciar sesión y
  seguía hasta cerrarla, ocupando unos 130 MB para ahorrar unos 200 ms por
  vista previa (un arranque en frío mide unos 250–300 ms, no el segundo
  que afirmaba el README). Ahora `install.sh` instala `quickview.socket`:
  systemd escucha en el socket de QuickView desde el inicio de sesión y
  arranca el demonio con la primera conexión, dejando esa solicitud en cola
  hasta que el demonio la lee, así que nunca se pierde una pulsación de
  Espacio. El antiguo servicio que arrancaba al iniciar sesión se
  deshabilita al actualizar.
- **El demonio es opcional.** `[daemon] daemon_mode` elige: `on-demand`
  (el predeterminado) sale tras `idle_minutes` (10) sin una vista previa
  abierta; `resident` se queda una vez arrancado, como antes; `off` sale en
  cuanto se cierra la vista previa, de modo que nada queda entre vistas
  previas. Se aplica al guardar el archivo. Sin systemd, el autoarranque de
  XDG y el lanzador arrancan el demonio, y los modos se comportan igual.

### Correcciones

- **Un socket que pertenece a systemd nunca se borra.** `QLocalServer`,
  cuando recibe un descriptor, elimina el archivo del socket al cerrarse,
  como si lo hubiera creado él, lo que tras la primera salida por
  inactividad dejaría a systemd escuchando en una ruta que ningún cliente
  puede alcanzar. Las conexiones en el socket de systemd se aceptan
  directamente y se entregan al mismo código que los `QLocalSocket`, y el
  archivo se queda.
- **Un demonio activado por socket no se confunde consigo mismo con otro.**
  La comprobación de instancia única se conecta al socket; arrancado por
  systemd, llegaría al suyo propio y saldría. La comprobación se omite
  cuando systemd le pasó el socket.

## 2026-11-10 — velocidad y estructura

### Nuevo

- **Los documentos de oficina se muestran de inmediato, y luego se
  afinan.** Con LibreOffice en uso, un docx u odt esperaba unos 0,6 s en
  "Loading…" a que LibreOffice arrancara y lo maquetara. Ahora la
  maquetación propia aparece en unos 35–50 ms, mientras LibreOffice trabaja
  al lado en un segundo trabajador; sus páginas reemplazan a las rápidas en
  cuanto están en caché, y el lector se queda en la misma fracción del
  documento aunque los dos paginen de forma distinta. Pasar a otro archivo
  cancela la conversión, así que recorrer una carpeta nunca deja a
  LibreOffice trabajando en archivos ya pasados. Las presentaciones y los
  formatos antiguos, que no tienen maquetación rápida, esperan a
  LibreOffice como antes. Si LibreOffice falla, se queda la maquetación
  rápida.
- **Se precargan los documentos vecinos, no solo las imágenes.** Los
  archivos que ← → mostrarían a continuación solo se preparaban si eran
  imágenes. Ahora también se preparan los PDF y los documentos de oficina,
  sus dos primeras páginas (`PREFETCH_PAGES`), lo que basta para que se
  abran en unos 5 ms frente a unos 85 ms en frío; el resto se dibuja cuando
  el lector llega allí. Un documento de oficina vecino se prepara con la
  maquetación con que se abrirá, así que con LibreOffice se abre
  directamente en las páginas de LibreOffice. La precarga sigue haciendo
  una tarea a la vez, después de que la vista previa actual termine de
  dibujarse, y espera a la maquetación de LibreOffice de un documento de
  oficina antes de empezar.
- **Los ajustes se aplican sin reiniciar.** El demonio vigila
  `quickview.conf` (y su carpeta, para los editores que guardan
  renombrando) y lo vuelve a leer un cuarto de segundo después del último
  cambio. Todos los ajustes se aplican desde la siguiente vista previa; el
  tema del panel (incluido el sitio del botón de cerrar) y el nivel de
  registro cambian de inmediato, y una caché en disco más pequeña se poda
  enseguida. También se recoge una edición guardada mientras el demonio
  todavía arranca. Un archivo malformado vuelve a los valores
  predeterminados en lo que tenga mal, como al arrancar.

### Cambios

- **`renderers.py` es un paquete.** Los decodificadores eran un solo
  archivo de 3.948 líneas; ahora son `renderers/`, con un módulo por
  familia (`images`, `pdf`, `highlight`, `archives`, `office`, `suite`, que
  ejecuta LibreOffice, `sheets`, `epub`, `markdown`) y `base` para los
  límites y los codificadores comunes. Se trasladaron con un script y se
  revisaron línea por línea: no cambió el código, e `import renderers`
  sigue alcanzando todos los nombres, así que los trabajadores y los
  scripts auxiliares no se tocan. No hay ciclos de importación.
- **El trabajador despacha mediante una tabla.** `main()` de `worker.py`
  tenía 221 líneas, con doce tipos de tarea en una sola cadena if/elif.
  Ahora cada tipo es una función en una tabla `OPS`, que escribe mediante
  un pequeño objeto `Reply` que lleva la cuenta de si ya salió el
  encabezado, que es lo que decide cómo se informa un fallo. `serve()`
  responde una solicitud y puede manejarse por un par de sockets, así que
  el protocolo se prueba ahora sin jaula, incluida la regla de que un flujo
  que falla después de su encabezado termina sin la marca de fin de flujo,
  y la de que cada tipo de tarea que manda el demonio tiene quien lo
  atienda.
- **Los ajustes se leen cuando se usan.** Siete ajustes se copiaban en
  constantes al arrancar el demonio (`PDF_MAX_PAGES`, `OFFICE_ENGINE` y
  otros), y eso era lo que obligaba a reiniciar y lo que hacía que las
  pruebas modificaran variables de módulo. Ahora se leen del único dict
  `SETTINGS` en el punto de uso, y una recarga actualiza ese dict en el
  sitio.
- **Una sola comprobación decide si la respuesta de un trabajador todavía
  se quiere.** Once callbacks en cuatro vistas reimplementaban cada uno
  "¿es esta la tarea que dibuja ahora el panel, para el archivo en
  pantalla?"; un descuido en cualquiera de ellos pintaría la vista previa
  de un archivo bajo el nombre de otro. Ahora comparten `_is_current()`, y
  una prueba verifica que las respuestas tardías se descarten.
- **El encaminamiento de archivos es un solo método.** Qué vista
  previsualiza un archivo se decidía dentro de `show_file()`; ahora es
  `route()`, al que consultan `show_file()` y la precarga, de modo que los
  dos no pueden discrepar sobre un archivo.
- **Los métodos largos de la interfaz se dividieron.** La fila de
  controles de medios es un widget propio, `PlaybackBar` (`show_media()`
  pasó de 162 líneas a 34), y `show_image()` pasó de 97 a 10, como una
  consulta a la caché y un dibujo. Los controles se disponen al píxel como
  antes.
- **La ubicación de la caché en disco es privada de `common.py`.** La
  precarga de imágenes construía ella misma las rutas de la caché; ahora
  pregunta a `cache_has()`.

## 2026-11-10 — bifurcación de Nicolas Vaughan

Los primeros cambios hechos en [nivaca/QuickView][fork], una bifurcación
de [MustaphaAlioglou/QuickView][upstream] que mantiene Nicolas Vaughan
(<nicolasvaughan@proton.me>): revisar el código, reproducir cada error
antes de corregirlo y comprobar cada cambio con las pruebas y con un
demonio en marcha. Todo hasta la entrada del 2026-10-07, más abajo, es
obra original de Mustapha Alioglou.

[fork]: https://github.com/nivaca/QuickView
[upstream]: https://github.com/MustaphaAlioglou/QuickView

### Nuevo

- **Se usa el LibreOffice de Flathub.** Solo se buscaba un LibreOffice de
  la distribución bajo `/usr`, y el README decía que una copia Flatpak no
  podía ejecutarse en la jaula. En una máquina que solo tuviera el Flatpak,
  todos los docx, odt y presentaciones recurrían por eso a la maquetación
  propia aproximada, y los archivos antiguos `.doc`, `.xls`, `.ppt` y
  `.rtf`, a la tarjeta de metadatos. Ahora:
  - **Detección** (`renderers.flatpak_suite`).
    `org.libreoffice.LibreOffice` se encuentra leyendo directamente los
    directorios de instalación (primero el del usuario, luego
    `/var/lib/flatpak`, como busca el propio `flatpak`), y el runtime es el
    que nombra el `metadata` de la aplicación, de la instalación que lo
    tenga (una aplicación de usuario sobre un runtime de todo el sistema es
    el caso común). No se ejecuta ninguna orden `flatpak`, y ambos árboles
    se resuelven a rutas reales, de modo que una actualización que cambie
    el enlace `active` no puede quitarle uno de debajo a una conversión. Es
    una entrada más en `OFFICE_SUITES`, `flatpak:org.libreoffice.LibreOffice`,
    después de las rutas de la distribución: un LibreOffice de la
    distribución sigue teniendo prioridad, y `office_engine = builtin`
    sigue desactivando ambos.
  - **Dentro de la jaula del trabajador** (`sandbox._office_suite_binds`).
    El demonio monta los árboles de la aplicación y del runtime en solo
    lectura bajo `/run/quickview/libreoffice/` en la jaula de los
    trabajadores de dibujo, y solo en la de ellos; la jaula del reproductor
    de medios no cambia. No se añade nada escribible, y sigue sin entrar
    ningún documento del usuario: el archivo llega como descriptor, como
    antes.
  - **Una jaula anidada** (`renderers.suite_command`). El LibreOffice de
    Flatpak está compilado contra su runtime, no contra el `/usr` de la
    distribución, así que el trabajador lo ejecuta en una segunda jaula de
    bubblewrap dispuesta como la dispone Flatpak: el runtime como `/usr`,
    la aplicación como `/app`, `/lib`, `/bin` y lo demás reconstruidos como
    enlaces hacia él, `--unshare-all` (sin red), `--cap-drop ALL`, un
    entorno vacío y el directorio temporal de la conversión como única ruta
    escribible. Dentro de la jaula del trabajador queda anidada; ejecutada
    desde una prueba en el anfitrión, es la misma jaula. Matarla al cumplirse
    el límite de 12 s sigue derribando todo el árbol.
  - **Tipos de letra.** Las fuentes del sistema se montan donde busca el
    fontconfig del runtime (`/run/host/fonts`), y también las del usuario,
    de `~/.local/share/fonts`. Las entradas de esa carpeta suelen ser
    enlaces simbólicos a una colección de fuentes en otro lugar de la
    carpeta personal, que un montaje de la carpeta traería como enlaces a
    ninguna parte, así que cada entrada se monta en su destino real. Se
    comprobó convirtiendo un documento compuesto en Junicode, una fuente
    instalada por el usuario: sin esto salía en DejaVu Serif.
  - **Un ajuste de Flatpak se deja fuera a propósito.** El metadata de la
    aplicación fija `LIBO_FLATPAK=1`, que activa la integración con el
    escritorio que tiene una caja de arena Flatpak real (portales,
    `/.flatpak-info`); en esta jaula LibreOffice sale entonces con estado 1
    y sin mensaje.
  - **Velocidad.** Unos 0,4 s para convertir un documento corto, unos
    0,6 s para un `.doc` antiguo mediante el grupo real de trabajadores del
    demonio, contando la jaula anidada.
  - **Pruebas.** Siete nuevas (`FlatpakSuite` en `tests/test_office.py`)
    se ejecutan sobre un árbol de instalación falso, así que la integración
    continua cubre sin Flatpak la detección, la prioridad de una
    instalación de la distribución, las instalaciones rotas, los montajes,
    la rama dentro de la jaula y la forma de la jaula anidada. En una
    máquina con el Flatpak, las nueve pruebas con LibreOffice real que allí
    se saltaban (docx, pptx, odp, doc, ppt, xls como páginas y como
    cuadrícula, rtf) ahora se ejecutan y pasan.
- **Lint en la integración continua.** El flujo de trabajo ejecuta las
  comprobaciones de pyflakes de ruff (`ruff check --select F`) antes de las
  pruebas. Señalan nombres no definidos e importaciones sin usar, y habrían
  atrapado el error corregido más abajo el mismo día en que se escribió. Se
  quitaron seis importaciones sin usar para que empiece limpio.

### Cambios

- **El demonio está dividido en módulos** (commit `56d4f84`).
  `quickview.py` había crecido hasta unas 4.000 líneas, unas 2.500 de ellas
  en una sola clase de ventana. Ahora contiene la ventana, el socket de IPC
  y el despacho del tipo de archivo a la vista (unas 770 líneas). Cada
  familia de vistas es una clase mixin que `QuickView` hereda, en su propio
  módulo:
  - `view_image.py`: imágenes fijas, precarga de vecinos, animaciones
  - `view_document.py`: PDF, Markdown, EPUB, la barra lateral del índice,
    la búsqueda
  - `view_media.py`: audio y vídeo
  - `view_text.py`: texto fuente y plano, HTML, carpetas, archivos
    comprimidos
  - `view_office.py`: documentos de oficina, presentaciones, hojas de
    cálculo

  y las piezas comunes pasaron a `common.py` (ajustes, tablas de tipos de
  archivo, hoja de estilos, registro, la caché en disco), `sandbox.py` (la
  jaula, el grupo de trabajadores, `SandboxJob`, `MediaSession`) y
  `widgets.py` (la barra de título, la barra de avance y la capa de
  coincidencias). La división la hizo un script que trasladaba líneas, no
  una mano, y luego se comprobó que cada línea trasladada fuera idéntica
  byte a byte a la original: solo difieren las importaciones y la cabecera
  de la clase, y el comportamiento no cambia. Nada vuelve a importar
  `quickview`: el demonio lo ejecuta como `__main__`, y una segunda
  importación cargaría una segunda copia con sus propios ajustes. Las
  pruebas que cambiaban un atributo de módulo (`MediaSession`,
  `office_suite`, `OFFICE_ENGINE`, `CACHE_VERSION`) lo cambian ahora en el
  módulo que lo lee, donde el cambio de verdad surte efecto.

### Correcciones

- **Un archivo que no puede abrirse muestra su error en lugar de dejar
  colgado el panel** (commit `c0e767c`). Un archivo borrado, movido o
  vuelto ilegible entre el momento de seleccionarlo y el de previsualizarlo
  dejaba el panel esperando para siempre. El error se entregaba desde un
  temporizador de demora cero cuyo callback leía `exc` de un bloque
  `except OSError as exc:`, pero Python desliga ese nombre cuando el
  bloque termina, así que el callback lanzaba `NameError` y el `on_done`
  de la tarea nunca se disparaba. Estaba en cinco sitios: dos en
  `SandboxJob` (todas las vistas previas de documentos e imágenes) y tres
  en `MediaSession` (audio y vídeo). Ahora cada uno guarda el mensaje
  mientras todavía existe. Se reprodujo antes de la corrección;
  `tests/test_sandbox_job.py` falla con el código antiguo y pasa con el
  nuevo.
- **El búfer de fotogramas de medios se libera cuando el reproductor no
  puede arrancar** (commit `c0e767c`). Si el trabajador de medios
  enjaulado no conseguía lanzarse, su búfer de fotogramas en memoria
  compartida seguía mapeado: `MediaSession.stop()` vuelve antes de tiempo
  en una sesión que nunca arrancó, así que nada más lo desmapeaba.
- **`install.sh` repara un virtualenv que perdió su `pyvenv.cfg`.** Un
  `.venv` copiado o sincronizado sin ese archivo todavía tiene un `python`
  que se ejecuta, pero como el intérprete del sistema a secas, para el que
  los paquetes de `.venv` son invisibles. El demonio perdía entonces el
  resaltado de sintaxis, y el paso de pip del instalador apuntaba a
  `/usr/local` y fallaba con `Permission denied`. Ahora el instalador
  vuelve a ejecutar `venv` sobre ese directorio, lo que reescribe el
  archivo y conserva todos los paquetes instalados, y se niega a seguir con
  un `python` que no sea un virtualenv, en lugar de dejar que pip escriba
  en el sistema.

### Documentación

- El README describe la compatibilidad con Flatpak, la nueva disposición
  de los módulos y las contribuciones de esta bifurcación, y las
  instrucciones de instalación clonan la bifurcación.

## 2026-10-07

### Nuevo

- **Los libros antiguos `.xls` se abren como cuadrícula con pestañas.** Con
  LibreOffice instalado, un libro antiguo se convierte a xlsx en la jaula y
  lo lee el mismo lector de cuadrícula que uno actual, así que recibe una
  tabla por hoja, con las pestañas abajo, en lugar de páginas planas. Unos
  0,6 s la primera vez; después la cuadrícula queda en caché en disco, y el
  demonio comprueba la forma y los límites de una cuadrícula en caché antes
  de construir con ella una tabla, ya que en el directorio de la caché
  puede escribir cualquier cosa que corra como el usuario. Si la cuadrícula
  no puede leerse, la vista de páginas queda como respaldo.
- **Las cifras de las hojas de cálculo conservan sus formatos de número.**
  Las celdas de xlsx se mostraban como números desnudos, salvo las fechas y
  los porcentajes: €1,234.50 se leía 1234.5. Ahora se aplican los códigos
  de formato (decimales, separadores de miles, moneda escrita entre
  comillas, escapada o como etiqueta de configuración regional
  `[$€-408]`, notación científica, y las secciones positivo;negativo;cero
  que ponen los negativos entre paréntesis o muestran el cero como un
  guion), redondeando la mitad hacia fuera del cero, como hace Excel. Las
  secciones condicionales, las fracciones y las disposiciones de dígitos,
  como los números de teléfono, siguen mostrando el número sin formato.
- **Las presentaciones y los formatos de oficina antiguos se previsualizan
  con LibreOffice.** Las presentaciones `.pptx`, `.ppsx` y `.odp` reciben
  una página por diapositiva, y los antiguos binarios `.doc`, `.xls` y
  `.ppt`, y `.rtf`, se maquetan como páginas, todos mediante la misma
  conversión dentro de la jaula que ya usaban los documentos de Word, con
  la misma caché. Antes cada uno mostraba solo la tarjeta de metadatos. Sin
  LibreOffice (o con `office_engine = builtin`), una presentación muestra
  la miniatura que trae incrustada, con su texto a un botón de distancia, y
  los formatos antiguos y el RTF conservan la tarjeta. El formato se decide
  por el contenido: los miembros del zip o el `mimetype` de ODF, la entrada
  de directorio del flujo principal en el contenedor OLE2 que comparten los
  formatos binarios (comprobada como entrada de directorio, de modo que un
  nombre de flujo escrito dentro de un documento no pueda decidirlo) y el
  `{\rtf` con que empieza un RTF. Un `.odp` sin LibreOffice ya no lo lee la
  maquetación propia como una columna de cuadros de texto sueltos. La
  integración continua instala Impress y Calc junto con Writer para que se
  prueben las conversiones reales.
- **Integración continua.** Un flujo de trabajo de GitHub Actions ejecuta
  las pruebas con cada push y cada pull request, en Python 3.10 (el más
  antiguo que acepta `install.sh`) y 3.14, con las ruedas de PySide6 en
  Ubuntu y LibreOffice Writer instalado, para que también se pruebe la
  conversión real de `.docx`; allí no se salta ninguna prueba.
- **Las pruebas del índice y de la búsqueda en PDF se ejecutan en todas
  partes.** Antes se saltaban salvo que se les indicara un documento real,
  y las de búsqueda afirmaban cantidades de coincidencias en un archivo
  concreto que solo tenía su autor. Ahora se ejecutan sobre un PDF de nueve
  páginas que `tests/samplepdf.py` escribe con sintaxis PDF en crudo, con
  un índice anidado y un texto conocido, así que las cantidades esperadas
  salen de lo que se escribió. Hay dos comprobaciones nuevas: el índice
  vuelve exactamente como se escribió, con cada entrada en su línea, y
  cada resaltado de búsqueda cubre las palabras que informa, releídas de la
  página. La segunda atrapa una posición de coincidencia que no se
  traslada de vuelta por el aplanamiento del texto, lo que corre de lado
  cada resaltado y que nada más había notado. `QUICKVIEW_SEARCH_PDF`
  desaparece; `QUICKVIEW_TEST_PDF` sigue sustituyendo la muestra del
  índice.

### Correcciones

- **Los porcentajes muestran los decimales que pide su formato.** Todos
  los porcentajes se imprimían con todos sus dígitos, así que `0.0%`
  mostraba 52.65% donde Excel muestra 52.7%, y `0.00%` mostraba 22.3% por
  22.30%.
- **Las pruebas ya no abortan según cómo se las arranque.** `python -m
  unittest discover tests` moría con SIGABRT a medio camino: sin `-t .`
  los archivos se cargan como módulos de nivel superior, así que la
  `QApplication` compartida de `tests/__init__.py` nunca se creaba,
  `test_epub` creaba en su lugar una `QGuiApplication`, y la primera prueba
  de widgets de `test_media` hacía abortar a Qt. Ahora cada módulo de
  pruebas crea él mismo una `QApplication` (que sirve igual para las
  pruebas sin widgets), así que funcionan tanto el descubrimiento desde
  cualquier sitio como la ejecución directa de un solo archivo.
- **La prueba de la configuración ilegible se salta sola como root.** Root
  lee de todos modos un archivo con modo 000, así que en un contenedor el
  caso no podía prepararse y la prueba fallaba.

## 2026-09-25

### Nuevo

- **Los documentos de Word se previsualizan con exactitud cuando
  LibreOffice está instalado.** LibreOffice convierte un `.docx` o `.odt`
  a PDF dentro de la jaula de bwrap, y la vista de páginas PDF lo muestra,
  así que las fotos conservan su tamaño y su posición, el texto fluye
  alrededor de ellas, y los tipos de letra, la justificación, los
  encabezados y los logotipos EMF aparecen como en el documento. Unos
  1,3 s la primera vez; después queda en caché. Las máquinas sin
  LibreOffice, o una conversión que falla o tarda más de 12 s, recurren a
  la maquetación propia. La clave de la caché de oficina nombra ahora el
  motor, de modo que instalar o quitar LibreOffice nunca deja en pantalla
  las páginas del otro motor.

  Preferir la velocidad a la fidelidad es un ajuste: `office_engine =
  builtin` en `[preview]` se salta LibreOffice aunque esté instalado.

### Correcciones

- **Las páginas se ven nítidas en pantallas escaladas.** Las páginas de
  PDF, de oficina, de EPUB y de Markdown se dibujaban a su ancho lógico y
  luego el compositor las estiraba, así que con un escalado del 125 % o el
  150 % se veían borrosas al lado de Okular. Ahora se dibujan con la
  proporción de píxeles del dispositivo de la ventana (que se le pide a la
  ventana, porque con el escalado fraccionario de Wayland solo ella conoce
  el 1,25 exacto) y se muestran al mismo tamaño con todos los píxeles. La
  maquetación no cambia: los libros y el Markdown se pintan a mayor
  resolución, sin volver a fluir el texto, y los resaltados de búsqueda,
  el índice y las posiciones de los capítulos conservan su geometría
  lógica. La proporción forma parte de la clave de la caché de páginas, y
  cada página anota la proporción con que de verdad se dibujó.
- **La maquetación propia de .docx se parece mucho más al documento.** Las
  imágenes se dibujan al tamaño que les da el documento y no a 420 px
  fijos; el texto de una tabla o de un cuadro de texto ya no se imprime dos
  veces; `<w:b w:val="0"/>` ("no negrita") ya no sale en negrita; los
  encabezados se encuentran por el *nombre* del estilo, de modo que se
  reconocen los encabezados de un Word en griego o en alemán; se conservan
  la alineación, las sangrías, el espaciado entre párrafos, los saltos de
  página y de línea, los tabuladores, los tamaños, colores y tipos de letra
  de cada tramo, el tachado y el superíndice y subíndice; y las imágenes
  EMF/WMF, que Qt no puede decodificar, se omiten en lugar de dejar un
  hueco.
- **`install.sh` ya no sale en silencio en las distribuciones sin un
  PySide6 empaquetado** (Ubuntu 22.04/24.04, Mint). La comprobación de
  ubicación añadida el 2026-09-23 fallaba bajo `set -e` cuando no había
  PySide6, y terminaba el script antes de que pudiera instalar la copia
  privada. Se verificó con instalaciones limpias en contenedores de Ubuntu
  22.04 y 24.04, junto con Fedora, Debian 13 y Arch.
- **La pista para Arch/CachyOS sobre los módulos de Qt que faltan era
  errónea.** QtPdf está en `qt6-webengine` y QtMultimedia en
  `qt6-multimedia`, ambos opcionales para `pyside6`; ahora la pista los
  nombra a ellos en lugar de `pyside6`, que el usuario ya tiene.

## 2026-09-23

### Nuevo

- **El shebang decide el lenguaje cuando no hay extensión.** Un script
  guardado como `~/bin/deploy` en lugar de `deploy.sh` se previsualizaba
  como texto gris; ahora se lee su línea `#!`. Cuando se elige el lexer el
  contenido ya está decodificado, así que esto cuesta una división de una
  cadena y ninguna E/S adicional.

  No se usa, a propósito, `guess_lexer()` de Pygments. Ejecuta el
  `analyse_text()` de cada lexer sobre contenido no confiable (la
  superficie lenta y cargada de expresiones regulares que el camino por el
  nombre del archivo existe para evitar), y se equivoca lo bastante a menudo
  como para importar: `#!/usr/bin/env node` y `#!/usr/bin/awk -f` dan
  ambos "Text only", y `#!/usr/bin/php` da JavaScript. Leer el nombre del
  intérprete en la línea es exacto. `env` se desenvuelve, incluidos `-S` y
  las asignaciones `VAR=value` iniciales, y se recorta el sufijo de versión
  (`python3.12` → `python`). Una pequeña tabla cubre los nombres para los
  que Pygments no tiene alias (`node`, `deno`, `dash`, `Rscript`, …) o que
  resuelve mal (`v` es el lenguaje V, no Verilog).

  Una extensión que Pygments reconoce sigue teniendo prioridad; el shebang
  solo llena el hueco cuando no la hay.

- **`[logging] log_level`**, uno de `error`, `warning`, `info`, `debug`,
  con `info` por omisión. El demonio estaba fijado en `DEBUG`, así que cada
  instalación escribía para siempre los aciertos de la caché y el ciclo de
  vida de los trabajadores en `quickview.log` y en el diario. Para una sola
  ejecución se cambia con `QUICKVIEW_LOG_LEVEL`. La captura de cuelgues no
  se ve afectada: un cuelgue nativo sigue yendo a `crash.log`, sea cual sea
  este ajuste.

### Cambios

- **Se usan el PySide6 y el Pygments de la distribución cuando son lo
  bastante buenos.** Ahora `install.sh` crea `.venv` con
  `--system-site-packages` y solo instala PySide6 con pip cuando el sistema
  no tiene uno utilizable (6.4 o posterior, la versión que añadió los
  enlaces de QtPdf). Un virtualenv existente se actualiza en el sitio
  cambiando la opción en `pyvenv.cfg`, que el intérprete vuelve a leer en
  cada arranque.

  Es sobre todo un ahorro de disco: medido en una máquina, `.venv` baja de
  672 MB a 13 MB. La memoria también mejora, pero poco. Compartir el Qt de
  la distribución con los procesos de Plasma lleva las páginas
  private-clean del demonio de 14,7 MB a menos de 0,1 MB; en contra, la
  distribución divide Qt en más bibliotecas de las que carga la compilación
  incluida (17 frente a 6), y las reubicaciones adicionales suman unos
  8,6 MB de private-dirty. En neto, en tres ejecuciones de un demonio recién
  arrancado: PSS de 51,2 MB a 46,7 MB, páginas exclusivas (privadas) de
  44,9 MB a 38,9 MB. El RSS a secas *sube*, de 77 MB a 112 MB, porque cuenta
  enteras esas bibliotecas compartidas adicionales, y por eso es la cifra
  equivocada para citar aquí.

  El ahorro depende de que algo más en el escritorio ya tenga las
  bibliotecas residentes, lo que en Plasma ocurre; en una sesión desnuda
  sería menor.

  La jaula alcanza los site-packages del sistema sin cambios: `/usr` ya se
  monta en solo lectura. No alcanza `~/.local/lib`, que
  `--system-site-packages` también expone y que está *antes* que `/usr` en
  `sys.path`, así que el instalador comprueba dónde se resuelve un módulo y
  no solo que se importe; de lo contrario, un `pip install --user PySide6`
  anterior pasaría todas las comprobaciones y luego faltaría dentro de
  bubblewrap.

  PySide6 se sondea módulo por módulo y no con un simple `import PySide6`,
  porque las distribuciones lo dividen de maneras distintas. `QtCore`,
  `QtGui`, `QtWidgets` y `QtNetwork` son obligatorios; `QtPdf`,
  `QtWebEngine` y `QtMultimedia` se importan de forma perezosa y cada uno
  cuesta exactamente un tipo de vista previa, así que si falta uno se
  nombra de paso, en lugar de provocar todo un Qt privado. `./install.sh
  --pip-qt` fuerza el comportamiento anterior.

## 2026-08-30

### Nuevo

- **Un tema de panel Breeze**, con `panel_theme = breeze` en la nueva
  sección `[appearance]`. El panel siempre ha sido una impresión de Quick
  Look (una ventana oscura fija, el botón de cerrar arriba a la izquierda,
  indiferente al esquema de colores de Plasma), y eso sigue siendo el
  valor predeterminado y sigue siendo la idea. La alternativa lee cada
  color de la `QPalette` en uso, así que sigue el esquema propio del
  usuario, claro u oscuro, con su color de acento, en lugar de ser un
  segundo tema fijo que por casualidad se parezca al Breeze de hoy.
  También cuadra las esquinas y pasa el botón de cerrar a la derecha.

  Los colores estaban escritos en once hojas de estilos como unos treinta
  literales. Ahora pasan por un solo conjunto de tokens en `theme.py`, que
  es lo que hace posible un segundo tema, y la paleta predeterminada son
  esos mismos literales, así que el aspecto predeterminado no cambia: una
  prueba compara la hoja de estilos construida con la anterior,
  declaración por declaración.

- **Velocidad de reproducción y silencio** en vídeo y audio, de 0,25x a
  2x. Ambos son operaciones nuevas del reproductor enjaulado, y la
  velocidad se acota del lado del trabajador.

- **Vistas previas de Photoshop (`.psd`, `.psb`).** Qt no trae ningún
  manejador de PSD, así que estos archivos fallaban con "unsupported or
  corrupt": un .psd coincide con `image/*` e iba al camino de las
  imágenes, que no podía leerlo. Ahora QuickView analiza el formato por sí
  mismo, en la jaula con todos los demás analizadores y sin usar nada más
  que la biblioteca estándar.

  Lee la imagen compuesta aplanada que Photoshop ya guarda junto a las
  capas y nunca mira una capa, de modo que la mitad costosa del formato es
  la mitad que una vista previa se salta. Los datos de imagen comprimidos
  van precedidos por una tabla con la longitud de cada línea de barrido, lo
  que permite *saltarse* filas en lugar de decodificarlas; así el costo
  depende del tamaño de la vista previa y no del tamaño del documento, el
  mismo trato que el camino de las imágenes ya hace con el escalado DCT de
  libjpeg. En un archivo de 6000x4000, 95 ms frente a 281 ms para la misma
  decodificación sin diezmar, y la diferencia crece con el documento.
  Importa más lo cargada que esté la imagen que lo grande que sea: las
  líneas de barrido de dos colores con tramado o con alta frecuencia se
  codifican como miles de códigos PackBits cortos en lugar de decenas de
  códigos largos, y recorrerlas cuesta unas 25 veces más, así que los
  mismos 12 megapíxeles van de 95 ms a 733 ms.

  Se decodifican RGB, escala de grises, indexado, CMYK y duotono, a 8 o
  16 bits, en PSD y PSB, comprimidos con RLE o en crudo. CMYK se convierte
  dibujando la plancha negra sobre las otras tres con una mezcla por
  multiplicación, que es exactamente la fórmula y deja a Qt el trabajo por
  píxel. Un archivo guardado sin "Maximize Compatibility" no tiene imagen
  compuesta y recurre a la miniatura JPEG de sus recursos de imagen; los
  mapas de bits Lab y de 1 bit hacen lo mismo.

  Como el respaldo vive dentro de `decode_image` y no en una rama propia,
  PSD hereda la caché de dos niveles, el fotograma ARGB32 en crudo que
  viaja por la conexión, la precarga de vecinos y las dimensiones reales
  del documento en la barra de título, sin que ninguno de ellos sepa que el
  formato existe.

- **Vistas previas de Krita y OpenRaster (`.kra`, `.ora`).** Ambos son un
  zip que guarda la imagen aplanada como un PNG corriente, que Krita
  escribe justamente para que un generador de miniaturas nunca tenga que
  entender una pila de capas. Leer ese miembro es todo el decodificador, y
  se devuelve al camino de las imágenes para que reciba la lectura escalada
  y las dimensiones como cualquier otro PNG. `preview.png` es el respaldo
  para un archivo guardado sin la imagen combinada.

- **Vistas previas de Illustrator (`.ai`).** Un `.ai` es un PDF desde
  Illustrator 9, así que se entrega a la vista de páginas PDF y se
  transmite, desplaza, busca y guarda en caché igual. El demonio lee
  primero cuatro bytes para buscar `%PDF` (un olfateo, no un análisis, de
  modo que ningún decodificador vuelve al demonio), y un `.ai` anterior,
  solo PostScript, sigue recibiendo la tarjeta de metadatos.

### Correcciones

- **Hacer clic en la barra de avance salta a ese punto.** La ranura de un
  QSlider es por omisión un control de paso de página, así que un clic
  movía el tirador un empujón fijo hacia el cursor y arrastrarlo era la
  única manera de llegar a algún sitio. Ahora toda la línea de tiempo es el
  destino, como en cualquier reproductor de medios. Los informes de
  posición del reproductor se ignoran también mientras se sostiene el
  tirador, lo que evita que salte hacia atrás a mitad de arrastre.

### Seguridad

- El lector de PSD es el primer formato que QuickView analiza a mano, así
  que cada campo de longitud se compara con el tamaño real del archivo
  antes de reservar o saltar nada, y se ponen topes al lienzo, al número de
  canales, al recorrido de los recursos, al recurso de la miniatura y al
  resultado diezmado. El miembro del zip del que sale la vista previa de un
  `.kra` está acotado tanto por su tamaño declarado como por lo que de
  verdad produce, así que una cabecera mentirosa no consigue nada. Un
  archivo malformado sigue derribando solo su propio trabajador
  desechable.

## 2026-08-27

### Nuevo

- **Vistas previas de EPUB.** Los libros recibían la tarjeta de metadatos.
  Ahora se maquetan como páginas con la misma cadena que usan los PDF y
  los documentos de oficina: el spine se convierte al subconjunto de HTML
  que entiende `QTextDocument` y se inserta capítulo a capítulo con un
  cursor, y cada documento del spine empieza una página nueva, como un
  capítulo en un libro impreso. No interviene ningún motor de lectura, y
  nada nuevo corre fuera de la jaula.
- **El Markdown se dibuja**, con el mismo botón de la barra de título que
  usa el HTML: páginas dibujadas por omisión, el código fuente resaltado
  tras **Code**, y la elección se recuerda durante la sesión. Qt analiza
  el Markdown por sí mismo (md4c, tras `QTextDocument.setMarkdown`), así
  que esto no necesita ninguna biblioteca ni ningún motor de HTML: el
  análisis corre en la jaula como todos los demás, una operación
  `markdown` transmite imágenes de páginas, y estas se desplazan y se
  guardan en caché exactamente como las de un PDF. Las tablas, las listas
  de tareas y los bloques de código cercados se dibujan, y la paleta de
  página (`book_theme`) también se aplica aquí, de modo que el Markdown
  lleva el tema de los libros.

  **Sus encabezados son la barra lateral**, anidados según sus almohadillas
  y con la página donde cae cada uno, en el mismo botón ☰ que los
  marcadores de un PDF y los capítulos de un libro. Un archivo Markdown no
  tiene índice propio, así que sus encabezados lo son.

  A un documento le pasan tres cosas antes de pintarse, y todas corrigen
  cosas que se veían rotas:

  - **Las etiquetas HTML en crudo se quitan fuera del código.** Qt entrega
    un bloque HTML a su importador de texto enriquecido en mitad del
    análisis, y uno desequilibrado (un `<p align="center">` que envuelve
    dos etiquetas `<img>`, como empiezan la mitad de los README de GitHub)
    se traga el resto del documento. El propio README de este proyecto se
    importaba como 2.420 caracteres de los 22.222 que tiene, y todos los
    párrafos después del bloque desaparecían sin aviso. Los bloques
    cercados y el código en línea conservan sus etiquetas, así que un
    README que documente HTML lo sigue mostrando.
  - **Las imágenes se reemplazan por una nota que las nombra.** Las
    imágenes de un archivo Markdown están a su lado en el disco, y la
    jaula no tiene disco: el archivo llega como descriptor. Qt resuelve
    esas rutas relativas contra el directorio de trabajo del trabajador,
    así que una imagen solo se cargaba cuando el documento estaba por
    casualidad dentro de la carpeta de esta misma aplicación: bien para el
    README del proyecto, mal para cualquier archivo que alguien de verdad
    previsualice.
  - **El código cercado puede partirse en líneas.** Qt lo importa como
    líneas que no se pueden partir, y una página no puede desplazarse de
    lado: una línea larga sencillamente quedaba cortada en el margen.
    Partirla se lee un poco mal; perder media línea se lee como un error.

### Correcciones

- **Hacer clic en una entrada del índice desplazaba a la página, no al
  encabezado.** Una página dibujada aquí es a menudo más alta que la
  ventana (2326 px frente a una vista de 1451 px en una pantalla de
  3072×1728), así que una entrada que solo llevaba un número de página
  desplazaba al principio de esa página: todas las secciones de un capítulo
  iban al mismo sitio, y hacer clic en una cuyo encabezado ya estaba en
  pantalla no hacía nada. Ahora las entradas llevan el lugar de la página
  donde están, tomado del destino del propio marcador en un PDF y de la
  maquetación que produjo las páginas en un libro o un archivo Markdown, y
  la vista se desplaza hasta allí. Los índices guardados en caché por la
  versión anterior se reemplazan en lugar de reutilizarse, ya que no
  tienen posiciones.
- **Un documento en caché sin índice en caché se volvía a dibujar cada vez
  que se abría.** Ahora la entrada del índice se escribe aunque el
  documento no tenga ningún encabezado, de modo que "ninguno" se guarda
  como respuesta en lugar de leerse como "desconocido". Afectaba por igual
  a libros y archivos Markdown.

- **Ctrl+F funciona en las vistas previas de EPUB**, con el mismo
  resaltado, el mismo avance con Enter / Shift+Enter y el mismo contador
  de coincidencias que un PDF. El camino es distinto: un libro no tiene una
  capa de texto que extraer, así que una nueva operación, `epubsearch`,
  vuelve a maquetar el libro en la jaula (mismo ancho de página, misma hoja
  de estilos, y por tanto la misma maquetación con que se pintaron las
  páginas) y mide cada coincidencia contra ella línea por línea. Lo que
  vuelve es lo mismo que devuelve la búsqueda en PDF,
  `{"matches": [{"page", "rects"}], "capped"}`, así que el demonio pinta
  ambas con el código que ya tenía. Una coincidencia partida en dos líneas
  recibe un rectángulo por línea, en lugar de un bloque que cruce el
  hueco, y una coincidencia en una página más allá del tope de dibujo se
  descarta en lugar de resaltarse donde nadie puede llegar.

  Maquetar el libro dos veces (una para dibujar, otra para buscar) es
  deliberado: un rectángulo solo significa algo dentro de una maquetación,
  y la alternativa, que el demonio guarde un libro analizado, es justo lo
  que la jaula existe para impedir. Los documentos de oficina siguen sin
  búsqueda, por la misma razón de siempre: nada los vuelve a maquetar para
  buscar.
- **`book_theme`, una paleta de página para las vistas previas de EPUB**:
  `paper` (la predeterminada), `sepia`, `dark`, `gruvbox-dark` y
  `gruvbox-light`. El trabajador pinta con la paleta elegida el fondo de la
  página, el texto, los encabezados y las citas; solo la página, nunca el
  panel que la rodea, que es parte de la interfaz de la aplicación. Los
  libros se maquetan ahora también con una letra con serifa a 11 pt, igual
  que el camino de oficina. El nombre del tema entra en la clave de la
  caché de páginas, así que cambiar de tema vuelve a dibujar en lugar de
  devolver las páginas del tema anterior, y un nombre desconocido en el
  archivo de configuración se lee como el predeterminado y no como un
  libro sin ningún color.
- **Una barra lateral con el índice, en un botón ☰ arriba a la
  izquierda.** Enumera los marcadores de un PDF o los capítulos de un
  libro, anidados y con números de página, y hacer clic en una entrada
  desplaza a esa página. El botón aparece solo en los documentos que tienen
  índice, y la barra lateral, una vez abierta, sigue abierta de un archivo
  a otro.

  Las dos fuentes son distintas, pero la barra lateral es la misma. El
  índice de un PDF sale de una nueva operación, `pdfoutline`, que recorre
  el modelo de marcadores de Qt en la jaula; los capítulos de un libro
  salen de la pasada de maquetación que produjo sus páginas (la posición
  del cursor donde se insertó cada capítulo es lo que hace posible un
  número de página), así que viajan en el encabezado del dibujo en lugar
  de costar un segundo análisis. Ambos se guardan en caché junto a las
  imágenes de las páginas, de modo que al reabrir un documento la barra
  lateral vuelve sin trabajador. Las entradas que apuntan más allá de la
  última página dibujada se descartan en lugar de mostrarse como filas que
  no llevan a ninguna parte.

  Se leen los dos tipos de índice de EPUB, el documento de navegación de
  EPUB 3 y el NCX de EPUB 2, y un libro sin ninguno de los dos recibe de
  todos modos una lista de capítulos, construida con el primer encabezado
  de cada archivo del spine. Una entrada del índice que apunta a un
  fragmento *dentro* de un archivo parte ese archivo en el fragmento, así
  que los libros que guardan varios capítulos en un solo documento siguen
  llegando a la página correcta.

- **Las hojas de cálculo se previsualizan como cuadrícula, con una pestaña
  por hoja.** `.xlsx`, `.xlsm` y `.ods` se vertían en la vista de páginas
  de oficina, que convertía un libro en un muro indistinto de filas con
  bordes, rotuladas "Sheet 1", "Sheet 2" (los nombres reales de las hojas
  nunca se leían). Ahora van a una nueva operación del trabajador,
  `sheets`, que lee las celdas en la jaula, y el demonio las muestra en una
  tabla: los nombres de las hojas en pestañas abajo, las letras de columna y
  los números de fila del propio libro en los márgenes, las columnas
  numéricas alineadas a la derecha, y la fila de encabezado destacada
  cuando la primera fila lo parece. Las hojas ocultas se omiten, como en
  Excel.

  Las celdas se colocan ahora por su propia referencia y no por el orden en
  que aparecen, así que una fila dispersa (una que omite sus celdas
  vacías, que es lo que escribe el formato) conserva sus columnas en lugar
  de correr todos los valores a la izquierda. Las fechas y los porcentajes
  en xlsx son números corrientes con un formato de número, así que también
  se lee `styles.xml`, incluidos los códigos de formato personalizados; sin
  él, cada fecha de un libro aparecía como un número de serie de cinco
  dígitos. Los decimales se imprimen redondeados (`15.7`, no
  `15.700000000000001`).

  Cada hoja tiene límites (2000 filas, 64 columnas, 512 caracteres por
  celda, 24 hojas), de modo que un libro de un millón de filas cuesta lo
  que uno pequeño. Un archivo que no se deja analizar como cuadrícula sigue
  recurriendo a la vista de páginas de oficina y, de ahí, a la tarjeta de
  metadatos.

## 2026-08-26

### Nuevo

- **Pruebas**: `python -m unittest discover -s tests`. 51 comprobaciones
  en cerca de un segundo, sin necesidad de display: el formato de la
  conexión (incluidos los nombres de archivo que no están en UTF-8, que
  antes fallaban en silencio), el analizador de ajustes, la protección de
  límites del fotograma en crudo, la codificación y las claves de la caché,
  y el aplanamiento del texto y la geometría de la búsqueda en PDF.
- **`uninstall.sh`**, que deshace lo que hizo `install.sh`: el demonio y su
  unidad, el menú de servicio de Dolphin, el lanzador en el `PATH`, la
  caché y los registros. Los ajustes se conservan salvo que se pase
  `--purge`, y la copia del repositorio nunca se toca.
- **Un archivo de ajustes en `~/.config/quickview/quickview.conf`**,
  escrito con sus valores predeterminados comentados la primera vez que
  arranca el demonio y nunca reescrito después. Tiene el estilo del
  resaltado de sintaxis, el límite de la vista previa de texto, el tope de
  páginas de PDF y los dos tamaños de caché; cada uno conserva una variable
  de entorno `QUICKVIEW_*` que prevalece sobre el archivo. Antes, el único
  ajuste que existía tenía que ir en el `Environment=` de la unidad de
  systemd, que `install.sh` regenera cada vez que se ejecuta, así que se
  perdía sin aviso en la siguiente actualización. Los valores fuera de
  rango se acotan, y un archivo que no se deja analizar vuelve a los
  valores predeterminados. Las muchas otras constantes son límites de
  seguridad sobre entradas no confiables y se quedan en el código a
  propósito.
- **Ctrl+F busca texto en la vista previa de un PDF.** Las coincidencias se
  resaltan en su sitio, y Enter / Shift+Enter avanzan por ellas,
  desplazando cada una a la vista. El demonio no tiene ningún analizador de
  PDF, así que la consulta va a un trabajador enjaulado (una nueva
  operación, `pdfsearch`) que extrae el texto y responde con rectángulos de
  coincidencia ya en píxeles de página; el demonio solo los pinta.
  Funcionan las frases de varias palabras, también cuando cruzan un salto
  de línea: la capa de texto de un PDF parte las líneas con `\r\n`, así que el
  texto de la página se compara con los espacios colapsados, y cada
  coincidencia se resalta con un rectángulo por cada línea que abarca, en
  lugar de un solo recuadro que se trague el hueco entre ellas. Algunos PDF
  colocan sus glifos en vez de emitir espacios, y Qt los extrae como
  "accordingtoyoursoftskills"; cuando una búsqueda exacta de varias
  palabras no encuentra nada, vuelve a intentarlo sin tener en cuenta los
  espacios y marca el resultado con `≈`, para que un acierto aproximado
  nunca se tome por uno literal. La búsqueda cubre las páginas que el
  visor de verdad muestra (las primeras 50), porque un acierto informado en
  la página 73 de un documento que deja de dibujarse en la 50 es peor que
  el silencio. Los documentos de oficina comparten la vista de PDF, pero se
  maquetan con `QTextDocument`, así que no tienen la fila de búsqueda.

### Rendimiento

- **Las vistas previas de fotos se abren unas 2,4 veces más rápido: de
  unos 338 ms a unos 127 ms** (mediana de 15 dibujos en frío sobre cinco
  fotos, medida con el propio registro del demonio, de `preview:` a
  `rendered:`). El trabajador comprimía en PNG cada imagen decodificada
  para pasarla por un socket Unix a un proceso que la descomprimía de
  inmediato: unos 107 ms para escribirla y unos 31 ms para leerla, más que
  la decodificación JPEG que venía antes. Ahora manda píxeles ARGB32 en
  crudo (unos 0,4 ms en cada sentido), y el demonio pinta en cuanto llegan.
  La copia que quiere la caché en disco se sigue haciendo, pero en el
  trabajador enjaulado y *después* de que la imagen esté en pantalla, fuera
  del camino que ve el usuario. BMP habría sido el término medio obvio, y
  es un error: el escritor de BMP de Qt descarta el canal alfa, así que los
  PNG y SVG transparentes habrían vuelto opacos.
- **Reabrir una foto es unas 3,4 veces más rápido: de unos 54 ms a unos
  16 ms**, y la caché en disco guarda diez veces más. Las imágenes de vista
  previa sin alfa se guardan en caché como JPEG y no como PNG (unos 24 ms
  para escribirlas y unos 11 ms para leerlas, frente a unos 111 y unos 37,
  con una décima parte del tamaño), de modo que el tope de 256 MB admite
  ahora más de mil vistas previas en lugar de unas 110. Las imágenes con
  alfa siguen en PNG, porque JPEG no lo tiene, y un logotipo transparente
  volvería sobre un cuadrado negro. El fragmento tEXt
  `QuickView:OrigSize` sobrevive como marcador de comentario JPEG, así que
  el camino de un acierto de la caché no cambia, y las entradas PNG
  existentes siguen siendo legibles.
- La precarga de una imagen vecina ya no transmite píxeles que va a tirar:
  prepara la caché en disco y no muestra nada, así que pide solo el
  fotograma codificado.
- **El camino rápido es ahora un cliente compilado (`client.rs`).**
  Entregarle una ruta al demonio ya caliente costaba unos 29 ms, casi todo
  en el arranque del intérprete de Python (solo `urllib.parse` se llevaba
  unos 6 ms). El cliente en Rust hace el mismo trabajo en unos 0,8 ms, así
  que `bin/quickview somefile` vuelve ahora en unos 4 ms de principio a fin
  en lugar de unos 40 ms. Sin crates, para que `rustc` lo compile sin
  Cargo; `install.sh` lo omite con una nota cuando no hay cadena de
  herramientas, y `client.py` queda como respaldo (él mismo baja ahora a
  unos 15 ms, sin su importación de `urllib`).

### Seguridad

- **El cliente del camino rápido ya no analiza nada.** La decodificación de
  porcentajes y la normalización de rutas pasaron del cliente a `ipc.py`,
  del lado del demonio, así que el único proceso de QuickView que corre
  *fuera* de la jaula de bubblewrap reenvía ahora sus argumentos byte a
  byte y nunca los inspecciona. Los nombres de archivo son entradas no
  confiables (un nombre preparado dentro de un archivo comprimido
  descargado es un vector plausible), y así todos los analizadores quedan
  del lado de la conexión que es seguro en memoria. Deja también a
  `normalize_arg` con una sola implementación, que es lo que su docstring
  pedía desde siempre.

### Correcciones

- **Las imágenes opacas vuelven a guardarse en caché como JPEG.** La
  comprobación del formato usaba `hasAlphaChannel()`, que responde sobre el
  *formato* de la imagen y no sobre sus píxeles, así que las capturas de
  pantalla y la mayoría de los PNG, que se decodifican a ARGB32 aunque sean
  del todo opacos, se guardaban como PNG de varios megabytes. Ahora se
  comprueban de verdad los píxeles (unos 2 ms, en el trabajador, después de
  que la imagen esté en pantalla): la entrada de caché de un PNG de muestra
  pasó de 190 KB a 76 KB.
- **Las entradas de la caché de vistas previas llevan ahora una versión de
  formato.** Las claves se construían con la ruta, la fecha de
  modificación, el tamaño y el recuadro de ajuste del archivo de origen,
  nada sobre *cómo* se dibujó, así que cambiar un dibujante dejaba que se
  sirviera para siempre la salida antigua. El camino de PDF lo había
  sorteado con cadenas `v2` subidas a mano en los nombres de sus
  variantes; ahora un solo `CACHE_VERSION` cubre todas las entradas.
- **Los nombres de archivo que no son UTF-8 válido se previsualizan en
  lugar de fallar en silencio.** El formato de la conexión decodificaba con
  `errors="replace"`, que convertía un byte indecodificable en U+FFFD: una
  ruta que no existe. Ahora ambos sentidos usan `surrogateescape`, el
  códec que ya hablan `sys.argv` y `open()`, así que esos bytes van y
  vuelven intactos.

### Cambios

- El mensaje del cliente al demonio ganó un campo inicial: el directorio
  de trabajo del remitente, contra el que el demonio resuelve los
  argumentos relativos (su propio directorio de trabajo, bajo systemd, no
  es el del cliente). Un demonio antiguo que siguiera corriendo durante una
  actualización leería mal el nuevo formato; `install.sh` ya reinicia el
  servicio en lugar de dejar en paz uno que esté corriendo.

## 2026-08-25 — primera versión pública

La versión que convirtió a QuickView de herramienta personal en programa
publicado: dibujo en caja de arena para todos los formatos, una ventana que
se porta bien en Wayland y un instalador que funciona en una máquina que no
sea la del autor.

### Seguridad

- **Todos los formatos que QuickView decodifica por sí mismo se analizan
  ahora fuera del demonio.** Las imágenes, los PDF, las animaciones, el
  audio, el vídeo y el resaltador de sintaxis corren todos en una jaula de
  bubblewrap (el HTML es la excepción, y se queda en la propia caja de
  arena del renderizador de Chromium); el demonio conserva la ventana, el
  socket y la caché, y no tiene ningún decodificador. Las excepciones
  documentadas antes, los GIF animados (`QMovie`) y el audio y el vídeo
  (`QMediaPlayer`), desaparecen.
- **La jaula ya no tiene ningún acceso a los archivos del usuario.** El
  archivo de destino llega como descriptor de archivo mediante
  `SCM_RIGHTS`, así que no hay nada que montar. Se verificó desde dentro de
  un trabajador: `/etc/passwd` y `$XDG_RUNTIME_DIR` inalcanzables, la
  carpeta personal muestra solo el esqueleto del montaje (1 entrada visible
  donde la carpeta real tiene 32), y `connect()` falla con `ENETUNREACH`.
- Se añadió `--cap-drop ALL` a la jaula.
- Se acotó el campo de longitud de fotograma en el flujo del trabajador.
  Venía del auxiliar y se guardaba en el búfer sin comprobarlo, así que un
  auxiliar comprometido podía pedirle al demonio que reservara 4 GiB; ahora
  los fotogramas de más de 64 MiB matan al trabajador.
- `QUICKVIEW_STRICT_SANDBOX=1` solo gobierna ahora el HTML (vista del
  código fuente en lugar de QtWebEngine). Los GIF y los medios ya no lo
  necesitan: siempre van enjaulados.

### Nuevo

- **Los archivos comprimidos y los documentos de oficina se previsualizan
  en lugar de caer en la tarjeta de metadatos.** Los archivos comprimidos
  (zip, rar, 7z, tar y compañía) muestran un listado del contenido con
  tamaños; nunca se extrae nada, solo se leen las cabeceras, así que una
  bomba zip queda inerte. zip y tar pasan por la biblioteca estándar de
  Python, y todo lo demás por `bsdtar`/`7z`/`unrar`, que leen el archivo
  desde `/dev/fd`, de modo que la jaula sigue recibiendo un descriptor y
  ninguna ruta, y no se hace ninguna copia. Si falta el programa de
  listado, si las cabeceras están cifradas o si el archivo está dañado, se
  recurre a la tarjeta de metadatos sin error.

  Los documentos de oficina **se maquetan como páginas** y los muestra la
  misma vista que usan los PDF, así que se desplazan, se transmiten y se
  guardan en caché página por página. docx, odt, xlsx y ods se convierten
  en la jaula al subconjunto de HTML que entiende `QTextDocument`
  (encabezados, negrita y cursiva, tablas, imágenes incrustadas) y se
  dibujan solo con Qt: sin suite de oficina, sin QtWebEngine. Medido: un
  .docx de 7 páginas se convierte en 8 ms y dibuja una página en 7 ms.

  Las presentaciones no se previsualizan, a propósito: su contenido son
  gráficos con posición absoluta, sin camino posible por QTextDocument, y
  lo único que las maqueta es una suite de oficina completa. Los binarios
  antiguos .doc/.xls/.ppt quedan fuera por la misma razón; ambos muestran
  la tarjeta de metadatos.
- **Resaltado de sintaxis en la vista previa de texto**, con Pygments, y
  corre en la jaula, no aquí. Los lexers son expresiones regulares; un
  archivo escrito para hacer retroceder una debería costar un trabajador
  desechable, no el proceso que tiene la ventana y el socket de IPC. El
  trabajador devuelve el texto y unos tramos `[start, length, colour]`, y
  el demonio pinta rangos: ni lexer ni analizador de HTML de este lado. Por
  eso las vistas previas de texto pasan ahora por un trabajador, y la
  lectura antigua dentro del proceso (`show_text_direct`) queda como
  respaldo para cuando la caja de arena no está disponible.

  Los archivos de más de 256 KiB se quedan sin color: 83 KiB de Python se
  analizan en unos 245 ms, pero 1 MiB tarda unos 1,5 s, más que la vista
  previa que decora. Cualquier estilo de Pygments puede elegirse con
  `QUICKVIEW_CODE_STYLE` (por omisión, `one-dark`); sin Pygments, la vista
  previa sencillamente no tiene color.
- `worker.py`: un trabajador enjaulado y caliente para imágenes, páginas
  de PDF y fotogramas de animación, que decodifica a partir de un
  descriptor recibido.
- `media_worker.py`: un reproductor de audio y vídeo enjaulado. Lleva el
  reloj del audio (con el socket de PipeWire montado en la jaula), así que
  Qt sincroniza el audio y el vídeo allí dentro; los fotogramas de vídeo
  pasan al demonio por un `memfd` compartido, y el demonio solo los copia
  en pantalla. Reproducir, pausar y saltar son mensajes por el socket.
- `renderers.py`: los decodificadores mismos, compartidos por los
  trabajadores y los scripts independientes.
- Un grupo de trabajadores con repuestos ya arrancados, de modo que la
  importación de Qt, de unos 150 ms, se paga antes de que una vista previa
  la necesite y no durante ella. Cada trabajador sigue atendiendo
  exactamente un archivo y luego sale.
- Reproducción de animaciones sin analizador de animaciones en el demonio:
  los fotogramas se decodifican en la jaula y se alternan como pixmaps con
  un temporizador, con un tope de 512 fotogramas / 256 MiB.
- Una línea de registro de depuración que anota quién dio tamaño a la
  ventana de la vista previa y respecto a qué pantalla, para diagnosticar
  una ventana que se abre con el tamaño equivocado.

### Cambios

- **Las vistas previas son más rápidas que antes de meterlas en la caja de
  arena.** Medido en esta máquina: la página 1 de un PDF sin caché, de
  583 ms a 122 ms; una imagen sin caché, de unos 150 ms a 56 ms; un acierto
  de la caché, de unos 20 ms a 2 ms; un vecino precargado, 2 ms. Entrar en
  la jaula cuesta unos 3 ms; el costo anterior era importar Qt para cada
  archivo.
- La ventana es del todo opaca. El panel era `rgba(34, 34, 38, 245)` y el
  borde fino era blanco translúcido; ahora ambos son colores sólidos, igual
  que los fondos de los botones, del deslizador y del texto.
  `WA_TranslucentBackground` sigue activado (es lo que permite componer las
  esquinas redondeadas y la sombra), pero el panel no deja ver nada de lo que
  hay detrás.
- Las vistas previas de texto se leen en un hilo del grupo (ahora el camino
  de respaldo, porque el texto pasa normalmente por la jaula), así que un
  archivo en un montaje NFS o FUSE atascado ya no puede congelar la ventana
  ni el socket del demonio. La ventana recibe de entrada el tamaño para
  texto, en lugar de cambiar de tamaño cuando llega la lectura.
- `render.py` y `render_pdf.py` son ahora envoltorios delgados de línea de
  órdenes sobre `renderers.py`, que se conservan para reproducir un dibujo
  a mano. El demonio habla ahora con `worker.py`.
- El README se reescribió en torno a la nueva frontera, con una lista
  honesta de lo que todavía corre en el demonio: el HTML (en la propia caja
  de arena del renderizador de Chromium), los bytes de texto, la detección
  de MIME y la decodificación de la salida PNG de los trabajadores.

### Correcciones

- **Una vista previa de texto podía tumbar el demonio.** `FileReader` era
  un `QRunnable` del que el demonio guardaba exactamente una referencia,
  así que previsualizar un segundo archivo mientras la primera lectura
  seguía bloqueada (el caso del montaje atascado, para el que existe el
  hilo lector) soltaba la última referencia a un objeto en ejecución, y el
  grupo vuelve a tocar un runnable después de que `run()` retorna. Ahora
  es un `QObject` simple, que se entrega al grupo como método ligado, y
  cada lector en curso se conserva hasta que llega su señal.
- **Cerrar una vista previa de medios podía colgar todo el demonio.**
  `stop()` esperaba al trabajador matado sin límite de tiempo en el hilo de
  la interfaz, así que un trabajador atascado en una lectura no
  interrumpible se llevaba consigo la ventana, los atajos y el socket de
  IPC. Ahora el límite es de 2 s, como en `Worker.kill()`.
- **Un dibujo truncado se informaba como exitoso.** Una vez que el
  trabajador había mandado su encabezado `{"ok": true}`, no podía
  retirarlo, así que un PDF que moría en la página 7 de 50 parecía
  completo: el demonio deducía el éxito de "llegó un encabezado". Ahora el
  trabajador termina un flujo con un fotograma de longitud cero; un fallo
  después del encabezado cierra el socket sin él y se explica en stderr, y
  el demonio trata como truncado un flujo sin marca de fin.
- **Los fotogramas de vídeo podían llegar desordenados.** El trabajador de
  medios reciclaba sus dos ranuras de memoria compartida con cada
  fotograma decodificado, sin acuse de recibo, así que a un demonio ocupado
  con la maquetación le llegaba una ranura cuyos píxeles ya se habían
  reemplazado. Ahora una ranura solo se reutiliza cuando el demonio
  confirma que la copió, y el trabajador descarta un fotograma en lugar de
  competir por ella.
- Se protegió `MediaSession.read_frame()` contra su propio trabajador:
  `slot`, `w`, `h` y `stride` solo se comprobaban como `stride * h`, así
  que un fotograma que declaraba `w=100000, h=1, stride=4` pasaba y luego
  leía unos 400 KB más allá de un búfer de 4 bytes. Ahora se comprueba el
  rango de cada campo, `stride` contra `w * 4`, y se rechaza una ranura
  negativa.
- Se acotó la altura en píxeles de una página de PDF dibujada. Una página
  declarada de 1 pt × 10000 pt pedía una columna de diez millones de
  píxeles: decenas de GB de QImage, en una jaula que no tiene límite de
  memoria propio.
- Se acotaron los fotogramas de animación en el demonio además de en el
  trabajador: 512 pixmaps del tamaño de la pantalla son gigabytes de
  memoria en el proceso dueño de la ventana, y el vigilante de la tarea se
  reinicia con cada fotograma, así que un trabajador que transmitiera para
  siempre nunca se cortaba.
- Se corrigió el montaje de la caché de fuentes. La jaula corre con
  `--clearenv` y `HOME=/tmp`, así que fontconfig busca en
  `/tmp/.cache/fontconfig` y nunca veía `~/.cache/fontconfig` montado en
  su ruta real, lo que en un sistema sin `/var/cache/fontconfig` equivalía
  a montar `/etc/fonts` sin una caché utilizable: el peor caso, de 749 ms,
  que el código pretendía evitar.
- La salida stderr de los trabajadores de repuesto se vacía ahora desde el
  momento en que se lanzan y no desde que reciben una tarea: un trabajador
  que hablara durante el arranque de Qt podía llenar el búfer de 64 KiB de
  la tubería y bloquearse antes de leer su solicitud, y la tarea fallaba
  por el vigilante.
- Los objetos `SandboxJob` se borran cuando terminan. Uno por vista previa
  *y* uno por precarga se acumulaban como hijos de la ventana durante toda
  la vida de un demonio pensado para correr semanas.
- Los fotogramas de animación ya no se desempaquetan de una carga más
  corta que la cabecera de demora de 4 bytes, y la precarga se salta APNG
  además de GIF (preparaba una entrada de la caché de la operación de
  imagen que el camino de las animaciones nunca lee).
- Se limitaron las actualizaciones de posición del trabajador de medios a
  los 200 ms que la constante siempre había descrito: Qt 6 eliminó
  `setNotifyInterval`, así que el trabajador mandaba un mensaje por cada
  fotograma decodificado para mover un solo deslizador.
- **El panel se abría donde al compositor le parecía.** El demonio es un
  cliente nativo de Wayland, y Wayland ignora `QWidget.move()`, así que
  `center_on_screen()` no había hecho nada en toda la sesión: KWin colocaba
  la ventana, y cada cambio de tamaño (un PDF que cambia su tarjeta
  "Loading…" por la columna de páginas) la hacía crecer desde ese punto.
  Ahora la ventana es una capa transparente del tamaño del área de trabajo,
  con el panel centrado dentro de ella, en coordenadas de *pantalla*, de
  modo que el panel cae justo en el centro aunque el compositor ponga la
  capa en otro sitio. Una vista previa se abre ahora centrada y sigue
  centrada al cambiar de tamaño. Arrastrar la barra de título desliza el
  panel dentro de la capa.

  Hay dos cosas que la capa *no* debe hacer, ambas aprendidas a golpes. No
  es de pantalla completa: KWin baja una ventana de pantalla completa
  inactiva por debajo de la que tiene el foco, lo que hacía que una vista
  previa levantada por el demonio (sin token de activación, ya que ningún
  clic la inició) desapareciera detrás de otras ventanas más o menos la
  mitad de las veces. Y su región de entrada se fija con
  `QWindow.setMask()`, nunca con `QWidget.setMask()`: la del widget recorta
  tanto el pintado como la entrada, así que un panel que se encogía (un
  PDF, luego un archivo de texto) dejaba en pantalla los píxeles del panel
  anterior, más grande, con el nuevo dibujado dentro: una ventana dentro de
  una ventana. En cualquier caso, la máscara sirve para que los clics fuera
  del panel vayan a lo que haya debajo, exactamente como cuando la ventana
  tenía el tamaño del panel.
- **Un PDF volvía a desplazarse solo hasta arriba durante el primer
  segundo o dos.** Las páginas se añadían a la columna a medida que se
  decodificaban, así que el rango de desplazamiento crecía mientras eso
  durara: en un documento de 30 páginas a 1689 px, algo más de dos
  segundos. Desplazarse en ese lapso quedaba limitado a las dos páginas que
  existían, y cuando llegaba el resto el lector quedaba cerca del principio
  de una columna de 69499 px, lo que parece exactamente que la vista se
  desplazó hacia arriba por sí sola. Ahora cada página recibe un marcador
  de posición de su tamaño real antes de que llegue ningún píxel (los
  tamaños salen de las cabeceras IHDR de los PNG en caché, 24 bytes cada
  una, sin decodificar), así que el rango es definitivo desde el primer
  pintado y un desplazamiento temprano llega adonde apuntaba.
- **Un PDF en caché solo en parte volvía a empezar desde la página 1 cada
  vez que se abría**, tiraba las páginas que ya estaban en pantalla y
  devolvía al lector al principio: parecía que la vista previa se cerraba
  y se volvía a abrir. Ahora una página que falta (porque la poda la quitó,
  o porque un dibujo anterior se interrumpió al cerrarse el panel) reanuda
  el dibujo en esa página y añade a la vista que ya está abierta, así que
  la posición de desplazamiento se conserva y cada apertura avanza en lugar
  de volver a dibujar el mismo principio. La operación `pdf` del
  trabajador recibe para esto una página `start`.
- **Las páginas de PDF se dibujaban como texto negro sobre fondo
  transparente.** `QPdfDocument.render()` devuelve una imagen ARGB, y un
  PDF pinta los glifos pero no su página, así que no había nada detrás del
  texto. Ahora las páginas se componen sobre blanco. Las páginas en caché
  de antes de la corrección se evitan con una variante de caché subida
  (`pdf{i}v2`).
- Los trabajadores retirados no se recogían, y se perdía un proceso zombi
  por cada vista previa en un demonio que corre durante semanas.
- Fontconfig no tenía configuración ni caché dentro de la jaula, así que Qt
  reconstruía su índice de fuentes en cada dibujo: 583 ms en lugar de
  148 ms para un PDF de una página. Ahora `/etc/fonts` y las cachés de
  fontconfig se montan en solo lectura. (Montar solo `/etc/fonts` es peor
  que no montar ninguno, con 749 ms: activa el escaneo sin aportar la
  caché.)
- `shutil.which("bwrap")` se ejecutaba en cada dibujo y en cada precarga;
  ahora se resuelve una vez.

### Limitaciones conocidas

- **Las presentaciones (`.pptx`, `.odp`) no se previsualizan en
  absoluto**, y vale la pena dejar escrita la razón para que nadie vuelva a
  recorrer el mismo camino. Su contenido es DrawingML con posición
  absoluta, que `QTextDocument` no puede maquetar, así que el único
  dibujante fiel es LibreOffice. Se implementó y luego se quitó:
  `soffice --headless --convert-to pdf` **se cuelga dentro de la jaula**
  (90 s con cero bytes en stdout *y* en stderr, y ningún archivo de
  salida), mientras que la misma orden en el anfitrión convierte una
  presentación de 149 diapositivas en 9 s. Montar `/etc/passwd` no sirvió;
  devolverle el espacio de nombres de red, tampoco. Dejarlo activado era
  peor que inútil, porque cada presentación esperaría a que se agotara el
  vigilante antes de recurrir al respaldo. La opción que queda es un
  dibujante de DrawingML propio (geometría de las formas en EMU, posiciones
  de los marcadores de posición a partir de los diseños de diapositiva,
  imágenes a partir de las partes de medios): ninguna dependencia, pero
  faltarían los gráficos y el SmartArt.
- Las hojas de cálculo se rotulan "Sheet 1", "Sheet 2" y no con sus
  nombres reales; los nombres están en `xl/workbook.xml` y sencillamente
  todavía no se leen.
- La maquetación de oficina es la aproximación de `QTextDocument`, no la de
  Word: los tipos de letra, los márgenes y los saltos de página difieren de
  lo que muestra la aplicación con que se escribió. Es una página legible,
  no una reproducción fiel.
- Las entradas de archivos comprimidos listadas con `bsdtar`/`7z`/`unrar`
  (rar, 7z, iso) muestran solo los nombres: sin tamaños y sin el total sin
  comprimir. Los formatos de listado largo cambian según la herramienta y
  la configuración regional, y una vista previa no los necesita; zip y
  tar, que pasan por la biblioteca estándar, sí muestran tamaños.
- El audio del reproductor enjaulado está conectado y el socket es
  alcanzable (`pactl info` funciona por él), pero no se ha
  confirmado que suene: esta máquina no expone por ahora ninguna salida
  real (`auto_null`).
- El demonio todavía decodifica la salida PNG de los trabajadores, así que
  un trabajador comprometido podría apuntar un PNG malformado al
  decodificador del propio demonio. Un solo formato endurecido en lugar de
  todos los que admite Qt, pero no cero.

## 2026-06-13

- Dibujo de PDF en caja de arena: un auxiliar de bubblewrap dibuja las
  páginas y las transmite una a una, de modo que la página 1 aparece
  mientras se dibuja el resto (con un tope de 50), y cada página se guarda
  en caché por separado.

## 2026-06-12

- Dibujo asíncrono de imágenes mediante `QProcess`, con un vigilante de
  20 s, en lugar de un `subprocess.run` bloqueante en el hilo de la
  interfaz; los dibujos en curso se cancelan al navegar y los resultados
  obsoletos se descartan.
- Decodificación de imágenes fuera del proceso, con bubblewrap
  (`render.py`), que rechaza decodificaciones no confiables sin `bwrap`
  salvo con `QUICKVIEW_ALLOW_UNSANDBOXED=1`.
- Caché de vistas previas en dos niveles: un LRU de pixmaps dentro del
  demonio y PNG bajo `~/.cache/quickview/previews`, con clave por ruta +
  fecha de modificación + tamaño, tope de 256 MiB, poda de los más
  antiguos primero y `--clear-cache`.
- Selección de varios archivos: el menú de servicio pasa `%U`, el
  protocolo del demonio recibe rutas separadas por saltos de línea, y las
  flechas recorren la selección, con los archivos de la misma carpeta como
  respaldo para un solo archivo.
- Registro rotativo en `~/.local/share/quickview/quickview.log`, y trazas
  de cuelgues de faulthandler en `crash.log`.
- Servicio de usuario de systemd (que se reinicia si falla), con el
  autoarranque de XDG como respaldo; `install.sh` genera a partir de una
  plantilla el `Exec` del menú de servicio, para que el repositorio
  funcione desde cualquier ruta.
