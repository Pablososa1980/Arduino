-- =============================================================================
-- Migración: ciclo de facturación por suministro.
-- Ejecutar UNA vez en phpMyAdmin (pestaña SQL) ANTES de subir los .php nuevos.
-- No borra ni modifica datos: solo agrega columnas.
-- =============================================================================
ALTER TABLE supplies
    ADD COLUMN billing_day TINYINT UNSIGNED NULL AFTER meter_serial;

ALTER TABLE monthly_summaries
    ADD COLUMN period_start DATE NULL AFTER period,
    ADD COLUMN period_end   DATE NULL AFTER period_start;
