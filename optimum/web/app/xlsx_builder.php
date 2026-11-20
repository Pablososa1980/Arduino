<?php
declare(strict_types=1);

// Copiado sin cambios del panel SEP2 (automatizacion-sep2-grupos/web/app/xlsx_builder.php).

/**
 * Genera un .xlsx real (una sola hoja) sin depender de ninguna librería
 * externa (no hay Composer en este proyecto). Un .xlsx es simplemente un
 * ZIP con unos pocos XML adentro; acá se arma a mano el mínimo necesario.
 *
 * @param string $sheetTitle Nombre de la hoja (máx. 31 caracteres, sin : \ / ? * [ ]).
 * @param array<int,array<int,string>> $blocks Cada bloque es un array de líneas de
 *        texto; la primera línea de cada bloque se pinta como encabezado
 *        (fondo azul oscuro, texto blanco en negrita), igual que en el
 *        Python. Se deja una fila vacía entre bloque y bloque.
 */
function build_single_sheet_xlsx(string $sheetTitle, array $blocks): string
{
    $sheetTitle = substr(preg_replace('/[:\\\\\/\?\*\[\]]/', ' ', $sheetTitle), 0, 31) ?: 'Hoja1';

    // ---- Construye las filas ----
    $rowsXml = '';
    $rowIndex = 1;
    foreach ($blocks as $lineas) {
        foreach ($lineas as $offset => $texto) {
            $styleId = $offset === 0 ? 2 : 1;
            $texto = htmlspecialchars((string) $texto, ENT_QUOTES | ENT_XML1, 'UTF-8');
            $cellRef = 'A' . $rowIndex;
            $rowsXml .= '<row r="' . $rowIndex . '" ht="21" customHeight="1">'
                . '<c r="' . $cellRef . '" t="inlineStr" s="' . $styleId . '">'
                . '<is><t xml:space="preserve">' . $texto . '</t></is>'
                . '</c></row>';
            $rowIndex++;
        }
        // fila vacía separadora entre suministros
        $rowsXml .= '<row r="' . $rowIndex . '" ht="8" customHeight="1"/>';
        $rowIndex++;
    }
    $ultimaFila = max($rowIndex - 1, 1);

    // ---- [Content_Types].xml ----
    $contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        . '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        . '<Default Extension="xml" ContentType="application/xml"/>'
        . '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        . '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        . '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        . '</Types>';

    // ---- _rels/.rels ----
    $rootRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        . '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        . '</Relationships>';

    // ---- xl/_rels/workbook.xml.rels ----
    $workbookRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        . '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        . '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        . '</Relationships>';

    // ---- xl/workbook.xml ----
    $sheetTitleXml = htmlspecialchars($sheetTitle, ENT_QUOTES | ENT_XML1, 'UTF-8');
    $workbookXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        . 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        . '<sheets><sheet name="' . $sheetTitleXml . '" sheetId="1" r:id="rId1"/></sheets>'
        . '</workbook>';

    // ---- xl/styles.xml ----
    // Fuente 0: normal. Fuente 1: negrita blanca (encabezados de suministro).
    // Fill 2: EAF2F8 (contenido). Fill 3: 1F4E78 (encabezado, igual que el Python).
    $stylesXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        . '<fonts count="2">'
        . '<font><sz val="10"/><name val="Aptos"/><color rgb="FF1F2937"/></font>'
        . '<font><b/><sz val="10"/><name val="Aptos"/><color rgb="FFFFFFFF"/></font>'
        . '</fonts>'
        . '<fills count="4">'
        . '<fill><patternFill patternType="none"/></fill>'
        . '<fill><patternFill patternType="gray125"/></fill>'
        . '<fill><patternFill patternType="solid"><fgColor rgb="FFEAF2F8"/><bgColor indexed="64"/></patternFill></fill>'
        . '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>'
        . '</fills>'
        . '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        . '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        . '<cellXfs count="3">'
        . '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        . '<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center"/></xf>'
        . '<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center"/></xf>'
        . '</cellXfs>'
        . '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        . '</styleSheet>';

    // ---- xl/worksheets/sheet1.xml ----
    $sheetXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        . '<sheetViews><sheetView showGridLines="0" workbookViewId="0"/></sheetViews>'
        . '<cols><col min="1" max="1" width="118" customWidth="1"/><col min="2" max="2" width="2" customWidth="1"/></cols>'
        . '<sheetData>' . $rowsXml . '</sheetData>'
        . '<printOptions/>'
        . '<pageMargins left="0.25" right="0.25" top="0.35" bottom="0.35" header="0.3" footer="0.3"/>'
        . '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        . '</worksheet>';

    // ---- Empaquetar como ZIP ----
    $tmp = tempnam(sys_get_temp_dir(), 'xlsx_');
    $zip = new ZipArchive();
    if ($zip->open($tmp, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
        throw new RuntimeException('No se pudo crear el archivo XLSX temporal.');
    }
    $zip->addFromString('[Content_Types].xml', $contentTypes);
    $zip->addFromString('_rels/.rels', $rootRels);
    $zip->addFromString('xl/_rels/workbook.xml.rels', $workbookRels);
    $zip->addFromString('xl/workbook.xml', $workbookXml);
    $zip->addFromString('xl/styles.xml', $stylesXml);
    $zip->addFromString('xl/worksheets/sheet1.xml', $sheetXml);
    $zip->close();

    $bytes = file_get_contents($tmp);
    unlink($tmp);
    return $bytes;
}

/* ==========================================================================
 * Tabla real (varias columnas, celdas numéricas y de fecha de verdad).
 *
 * build_single_sheet_xlsx() de arriba escribe una sola columna de texto y
 * arma todo el XML en memoria: sirve para la Vista Resumida (unas decenas de
 * líneas), pero no para un perfil de carga de un mes (unas 3.000 filas por
 * suministro). Esta función:
 *   - escribe la hoja directamente a un archivo temporal, sin acumular el
 *     XML entero en una variable;
 *   - acepta un iterable (se le puede pasar un generador que lea de PDO fila
 *     por fila, sin traer todo el resultado a un array);
 *   - graba números como números y fechas como fechas, para que Excel pueda
 *     filtrar, sumar y graficar sin conversiones manuales.
 *
 * Devuelve la RUTA de un archivo temporal, no los bytes. Enviarlo con
 * stream_xlsx_download(), que lo transmite y lo borra.
 * ========================================================================== */

/** Convierte 1 -> A, 27 -> AA. */
function xlsx_column_letter(int $index): string
{
    $letra = '';
    while ($index > 0) {
        $resto = ($index - 1) % 26;
        $letra = chr(65 + $resto) . $letra;
        $index = intdiv($index - 1 - $resto, 26);
    }
    return $letra;
}

/** Texto seguro para XML: escapa y saca caracteres de control que Excel rechaza. */
function xlsx_escape(string $texto): string
{
    $texto = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F]/u', '', $texto) ?? '';
    return htmlspecialchars($texto, ENT_QUOTES | ENT_XML1, 'UTF-8');
}

/**
 * Número de serie de Excel para una fecha/hora. Se interpreta el texto como
 * hora local "tal cual" (UTC en ambos lados) para que no se corra ninguna
 * hora: las lecturas ya vienen en America/Asuncion desde la base.
 */
function xlsx_date_serial(string $valor): ?float
{
    try {
        $utc = new DateTimeZone('UTC');
        $fecha = new DateTimeImmutable($valor, $utc);
        $base = new DateTimeImmutable('1899-12-30 00:00:00', $utc);
        return ($fecha->getTimestamp() - $base->getTimestamp()) / 86400.0;
    } catch (Throwable) {
        return null;
    }
}

/**
 * Número sin notación científica ni separadores de miles.
 *
 * Los seriales de fecha necesitan muchos más decimales que una potencia: con
 * 6 decimales el error es de ~0,09 s y una lectura de las 23:45 se guarda como
 * 23:44:59,97, que Excel muestra como 23:44. Por eso $decimales es parámetro.
 */
function xlsx_number_literal(float $valor, int $decimales = 6): string
{
    $texto = number_format($valor, $decimales, '.', '');
    $texto = rtrim(rtrim($texto, '0'), '.');
    return $texto === '' || $texto === '-' ? '0' : $texto;
}

/**
 * @param array<int,array{label:string,type?:string,width?:int}> $columns
 *        type: 'text' (por defecto), 'number', 'datetime', 'integer'.
 * @param iterable<int,array<int,mixed>> $rows Cada fila en el orden de $columns.
 * @param array<int,string> $titleLines Líneas de contexto arriba del encabezado.
 */
function build_table_xlsx(string $sheetTitle, array $columns, iterable $rows, array $titleLines = []): string
{
    if (!$columns) {
        throw new InvalidArgumentException('La tabla necesita al menos una columna.');
    }
    $sheetTitle = substr(preg_replace('/[:\\\\\/\?\*\[\]]/', ' ', $sheetTitle) ?? '', 0, 31) ?: 'Hoja1';
    $totalColumnas = count($columns);
    $ultimaLetra = xlsx_column_letter($totalColumnas);

    $rutaHoja = tempnam(sys_get_temp_dir(), 'sheet_');
    $hoja = fopen($rutaHoja, 'wb');
    if ($hoja === false) {
        throw new RuntimeException('No se pudo abrir el archivo temporal de la hoja.');
    }

    // ---- Encabezado del XML de la hoja (todo lo que va antes de las filas) ----
    $colsXml = '';
    foreach ($columns as $indice => $columna) {
        $ancho = (int) ($columna['width'] ?? 18);
        $numero = $indice + 1;
        $colsXml .= '<col min="' . $numero . '" max="' . $numero . '" width="' . $ancho . '" customWidth="1"/>';
    }

    $filaEncabezado = count($titleLines) + ($titleLines ? 2 : 1);

    fwrite($hoja, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        . '<sheetViews><sheetView showGridLines="0" workbookViewId="0">'
        . '<pane ySplit="' . $filaEncabezado . '" topLeftCell="A' . ($filaEncabezado + 1) . '" activePane="bottomLeft" state="frozen"/>'
        . '</sheetView></sheetViews>'
        . '<sheetFormatPr defaultRowHeight="15"/>'
        . '<cols>' . $colsXml . '</cols>'
        . '<sheetData>');

    $numeroFila = 1;

    // ---- Líneas de contexto ----
    foreach ($titleLines as $indice => $linea) {
        $estilo = $indice === 0 ? 5 : 6;
        fwrite($hoja, '<row r="' . $numeroFila . '" ht="18" customHeight="1">'
            . '<c r="A' . $numeroFila . '" t="inlineStr" s="' . $estilo . '">'
            . '<is><t xml:space="preserve">' . xlsx_escape((string) $linea) . '</t></is>'
            . '</c></row>');
        $numeroFila++;
    }
    if ($titleLines) {
        fwrite($hoja, '<row r="' . $numeroFila . '" ht="6" customHeight="1"/>');
        $numeroFila++;
    }

    // ---- Fila de encabezados ----
    $celdas = '';
    foreach ($columns as $indice => $columna) {
        $ref = xlsx_column_letter($indice + 1) . $numeroFila;
        $celdas .= '<c r="' . $ref . '" t="inlineStr" s="1">'
            . '<is><t xml:space="preserve">' . xlsx_escape((string) $columna['label']) . '</t></is></c>';
    }
    fwrite($hoja, '<row r="' . $numeroFila . '" ht="20" customHeight="1">' . $celdas . '</row>');
    $numeroFila++;

    // ---- Filas de datos ----
    $tipos = array_map(static fn(array $c): string => (string) ($c['type'] ?? 'text'), $columns);
    $filasEscritas = 0;
    $bufer = '';
    foreach ($rows as $fila) {
        $celdas = '';
        for ($i = 0; $i < $totalColumnas; $i++) {
            $ref = xlsx_column_letter($i + 1) . $numeroFila;
            $valor = $fila[$i] ?? null;
            if ($valor === null || $valor === '') {
                $celdas .= '<c r="' . $ref . '" s="2"/>';
                continue;
            }
            switch ($tipos[$i]) {
                case 'number':
                    $celdas .= '<c r="' . $ref . '" s="4"><v>' . xlsx_number_literal((float) $valor) . '</v></c>';
                    break;
                case 'integer':
                    $celdas .= '<c r="' . $ref . '" s="7"><v>' . (int) $valor . '</v></c>';
                    break;
                case 'datetime':
                    $serial = xlsx_date_serial((string) $valor);
                    $celdas .= $serial === null
                        ? '<c r="' . $ref . '" t="inlineStr" s="2"><is><t>' . xlsx_escape((string) $valor) . '</t></is></c>'
                        : '<c r="' . $ref . '" s="3"><v>' . xlsx_number_literal($serial, 11) . '</v></c>';
                    break;
                default:
                    $celdas .= '<c r="' . $ref . '" t="inlineStr" s="2">'
                        . '<is><t xml:space="preserve">' . xlsx_escape((string) $valor) . '</t></is></c>';
            }
        }
        $bufer .= '<row r="' . $numeroFila . '">' . $celdas . '</row>';
        $numeroFila++;
        $filasEscritas++;
        // Se vuelca cada 500 filas para que el búfer no crezca sin control.
        if ($filasEscritas % 500 === 0) {
            fwrite($hoja, $bufer);
            $bufer = '';
        }
    }
    if ($bufer !== '') {
        fwrite($hoja, $bufer);
    }

    $ultimaFila = max($numeroFila - 1, $filaEncabezado);
    fwrite($hoja, '</sheetData>'
        . '<autoFilter ref="A' . $filaEncabezado . ':' . $ultimaLetra . $ultimaFila . '"/>'
        . '<pageMargins left="0.25" right="0.25" top="0.35" bottom="0.35" header="0.3" footer="0.3"/>'
        . '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        . '</worksheet>');
    fclose($hoja);

    // ---- Partes fijas del paquete ----
    $contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        . '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        . '<Default Extension="xml" ContentType="application/xml"/>'
        . '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        . '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        . '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        . '</Types>';

    $rootRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        . '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        . '</Relationships>';

    $workbookRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        . '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        . '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        . '</Relationships>';

    $workbookXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        . 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        . '<sheets><sheet name="' . xlsx_escape($sheetTitle) . '" sheetId="1" r:id="rId1"/></sheets>'
        . '</workbook>';

    // Estilos: 0 normal · 1 encabezado · 2 texto · 3 fecha/hora · 4 decimal
    // · 5 título · 6 subtítulo · 7 entero.
    $stylesXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        . '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        . '<numFmts count="2">'
        . '<numFmt numFmtId="164" formatCode="dd/mm/yyyy\ hh:mm"/>'
        . '<numFmt numFmtId="165" formatCode="#,##0.00"/>'
        . '</numFmts>'
        . '<fonts count="4">'
        . '<font><sz val="10"/><name val="Aptos"/><color rgb="FF1F2937"/></font>'
        . '<font><b/><sz val="10"/><name val="Aptos"/><color rgb="FFFFFFFF"/></font>'
        . '<font><b/><sz val="12"/><name val="Aptos"/><color rgb="FF1F4E78"/></font>'
        . '<font><sz val="10"/><name val="Aptos"/><color rgb="FF4B5563"/></font>'
        . '</fonts>'
        . '<fills count="3">'
        . '<fill><patternFill patternType="none"/></fill>'
        . '<fill><patternFill patternType="gray125"/></fill>'
        . '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>'
        . '</fills>'
        . '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        . '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        . '<cellXfs count="8">'
        . '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        . '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" horizontal="center" wrapText="1"/></xf>'
        . '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        . '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/>'
        . '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/>'
        . '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="center"/></xf>'
        . '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="center"/></xf>'
        . '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyFont="1" applyNumberFormat="1"/>'
        . '</cellXfs>'
        . '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        . '</styleSheet>';

    $rutaLibro = tempnam(sys_get_temp_dir(), 'xlsx_');
    $zip = new ZipArchive();
    if ($zip->open($rutaLibro, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
        @unlink($rutaHoja);
        throw new RuntimeException('No se pudo crear el archivo XLSX temporal.');
    }
    $zip->addFromString('[Content_Types].xml', $contentTypes);
    $zip->addFromString('_rels/.rels', $rootRels);
    $zip->addFromString('xl/_rels/workbook.xml.rels', $workbookRels);
    $zip->addFromString('xl/workbook.xml', $workbookXml);
    $zip->addFromString('xl/styles.xml', $stylesXml);
    $zip->addFile($rutaHoja, 'xl/worksheets/sheet1.xml');
    $zip->close();
    @unlink($rutaHoja);

    return $rutaLibro;
}

/**
 * Envía un .xlsx temporal al navegador sin cargarlo entero en memoria y lo
 * borra del disco. No retorna: termina la ejecución.
 */
function stream_xlsx_download(string $rutaTemporal, string $nombreArchivo): never
{
    $tamano = (int) filesize($rutaTemporal);
    while (ob_get_level() > 0) {
        ob_end_clean();
    }
    header('Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    header('Content-Disposition: attachment; filename="' . $nombreArchivo . '"');
    header('Content-Length: ' . $tamano);
    header('Cache-Control: no-store');
    readfile($rutaTemporal);
    @unlink($rutaTemporal);
    exit;
}
