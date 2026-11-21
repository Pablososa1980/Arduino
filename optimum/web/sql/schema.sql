-- =============================================================================
-- Panel de Potencia — esquema MySQL / MariaDB
-- Ejecutar UNA vez en phpMyAdmin sobre la base vacía del sitio.
-- =============================================================================
SET NAMES utf8mb4;

-- Usuarios: admin (ve y administra todo) o consulta (solo sus suministros).
CREATE TABLE users (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(60)  NOT NULL,
    email           VARCHAR(190) NULL,
    full_name       VARCHAR(150) NOT NULL DEFAULT '',
    role            ENUM('admin','consulta') NOT NULL DEFAULT 'consulta',
    password_hash   VARCHAR(255) NOT NULL,
    receive_alerts  TINYINT(1)   NOT NULL DEFAULT 0,   -- recibe correo cuando se supera la tolerancia
    active          TINYINT(1)   NOT NULL DEFAULT 1,
    last_login_at   DATETIME     NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Suministros (puntos de medida del MDC). Se agregan desde el panel.
CREATE TABLE supplies (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    nis             VARCHAR(20)  NOT NULL,                 -- Punto de Medida en el MDC
    name            VARCHAR(150) NOT NULL,
    client          VARCHAR(150) NULL,
    meter_prefix    VARCHAR(20)  NOT NULL DEFAULT 'EGM',   -- el medidor a elegir empieza con esto
    channel         VARCHAR(190) NOT NULL DEFAULT 'Sum Li Active Power + (QI+QIV) (last average 1)- 0 x',
    meter_serial    VARCHAR(40)  NULL,                     -- se completa solo con la primera importación
    billing_day     TINYINT UNSIGNED NULL,                 -- día de cierre de facturación (1..31); NULL = mes calendario
    active          TINYINT(1)   NOT NULL DEFAULT 1,       -- inactivo = el script deja de descargarlo
    notes           TEXT         NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_supplies_nis (nis)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Condiciones contractuales con vigencia: si cambia la potencia contratada o el
-- factor, se agrega una fila nueva con su fecha "vigente desde". Los meses
-- anteriores se siguen evaluando con la condición que regía en ese momento.
CREATE TABLE supply_contracts (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    supply_id       INT UNSIGNED NOT NULL,
    valid_from      DATE         NOT NULL,
    factor          DECIMAL(14,4) NOT NULL,                -- factor multiplicador (TC x TP)
    contracted_kw   DECIMAL(12,2) NOT NULL,
    tolerance_pct   DECIMAL(5,2)  NOT NULL DEFAULT 10.00,
    notes           VARCHAR(255) NULL,
    created_by      INT UNSIGNED NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_contract_from (supply_id, valid_from),
    CONSTRAINT fk_contract_supply FOREIGN KEY (supply_id) REFERENCES supplies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Qué suministros ve cada usuario de consulta (el admin ve todos).
CREATE TABLE user_supply_permissions (
    user_id         INT UNSIGNED NOT NULL,
    supply_id       INT UNSIGNED NOT NULL,
    can_download    TINYINT(1)   NOT NULL DEFAULT 0,       -- puede bajar el Excel de lecturas
    PRIMARY KEY (user_id, supply_id),
    CONSTRAINT fk_perm_user   FOREIGN KEY (user_id)   REFERENCES users(id)    ON DELETE CASCADE,
    CONSTRAINT fk_perm_supply FOREIGN KEY (supply_id) REFERENCES supplies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Lecturas de 15 minutos tal cual vienen del MDC (valor secundario en W).
-- Los kW se calculan aplicando el factor vigente: así, si se corrige un factor,
-- todo el histórico se recalcula sin volver a descargar nada.
CREATE TABLE readings (
    supply_id       INT UNSIGNED NOT NULL,
    ts              DATETIME     NOT NULL,                 -- inicio del intervalo (hora de Paraguay)
    raw_value       DECIMAL(16,4) NULL,                    -- NULL = hueco sin lectura
    status          VARCHAR(30)  NOT NULL DEFAULT '',
    PRIMARY KEY (supply_id, ts),
    CONSTRAINT fk_reading_supply FOREIGN KEY (supply_id) REFERENCES supplies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Resumen por suministro y ciclo de facturación (lo usan la portada y el histórico).
-- period = mes en que cierra el ciclo; sin día de cierre, el ciclo es el mes calendario.
-- Se recalcula solo en cada importación y cuando cambia un contrato.
CREATE TABLE monthly_summaries (
    supply_id           INT UNSIGNED NOT NULL,
    period              CHAR(7)      NOT NULL,             -- AAAA-MM (mes de cierre del ciclo)
    period_start        DATE         NULL,                 -- primer día del ciclo
    period_end          DATE         NULL,                 -- día de cierre (incluido)
    first_ts            DATETIME     NULL,
    last_ts             DATETIME     NULL,
    readings_count      INT UNSIGNED NOT NULL DEFAULT 0,
    gap_count           INT UNSIGNED NOT NULL DEFAULT 0,
    max_kw              DECIMAL(12,2) NULL,
    max_ts              DATETIME     NULL,
    avg_kw              DECIMAL(12,2) NULL,
    energy_kwh          DECIMAL(16,2) NULL,
    contracted_kw       DECIMAL(12,2) NULL,                -- condición vigente al final del mes
    limit_kw            DECIMAL(12,2) NULL,
    tolerance_pct       DECIMAL(5,2)  NULL,
    over_contract_count INT UNSIGNED NOT NULL DEFAULT 0,
    over_limit_count    INT UNSIGNED NOT NULL DEFAULT 0,
    status              ENUM('normal','atencion','critico','sin_datos') NOT NULL DEFAULT 'sin_datos',
    daily_json          MEDIUMTEXT   NULL,                 -- máximos diarios para los gráficos
    updated_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (supply_id, period),
    CONSTRAINT fk_summary_supply FOREIGN KEY (supply_id) REFERENCES supplies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Intervalos que superaron el límite (contratada + tolerancia).
CREATE TABLE alerts (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    supply_id       INT UNSIGNED NOT NULL,
    ts              DATETIME     NOT NULL,
    kw              DECIMAL(12,2) NOT NULL,
    contracted_kw   DECIMAL(12,2) NOT NULL,
    limit_kw        DECIMAL(12,2) NOT NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notified_at     DATETIME     NULL,                     -- NULL = falta avisar por correo
    UNIQUE KEY uq_alert (supply_id, ts),
    KEY ix_alert_pending (notified_at),
    CONSTRAINT fk_alert_supply FOREIGN KEY (supply_id) REFERENCES supplies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Cada envío del script (para saber qué llegó y cuándo).
CREATE TABLE import_runs (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    supply_id       INT UNSIGNED NOT NULL,
    token_id        INT UNSIGNED NULL,
    period_start    DATE         NOT NULL,
    period_end      DATE         NOT NULL,
    readings_count  INT UNSIGNED NOT NULL DEFAULT 0,
    inserted_count  INT UNSIGNED NOT NULL DEFAULT 0,
    updated_count   INT UNSIGNED NOT NULL DEFAULT 0,
    new_alerts      INT UNSIGNED NOT NULL DEFAULT 0,
    meter           VARCHAR(40)  NULL,
    channel         VARCHAR(190) NULL,
    source_file     VARCHAR(190) NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_import_supply (supply_id, created_at),
    CONSTRAINT fk_import_supply FOREIGN KEY (supply_id) REFERENCES supplies(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tokens del script (se guarda solo el hash SHA-256, nunca el token).
CREATE TABLE api_tokens (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    token_hash      CHAR(64)     NOT NULL,
    active          TINYINT(1)   NOT NULL DEFAULT 1,
    expires_at      DATETIME     NULL,
    last_used_at    DATETIME     NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_token_hash (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Registro de auditoría (ingresos, cambios de usuarios, suministros, tokens).
CREATE TABLE audit_logs (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         INT UNSIGNED NULL,
    action          VARCHAR(80)  NOT NULL,
    entity_type     VARCHAR(40)  NULL,
    entity_id       VARCHAR(40)  NULL,
    ip_address      VARCHAR(45)  NULL,
    detail_text     TEXT         NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY ix_audit_created (created_at),
    KEY ix_audit_action_ip (action, ip_address, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
