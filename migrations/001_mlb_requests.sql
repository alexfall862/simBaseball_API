-- 001_mlb_requests.sql
-- Adds league + role columns to organizations,
-- creates mlb_requests and college_baseball_requests tables.

-- -------------------------------------------------------
-- 1. New columns on organizations
-- -------------------------------------------------------

-- League discriminator ("mlb" or "college")
ALTER TABLE organizations ADD COLUMN league VARCHAR(20) NOT NULL DEFAULT 'mlb';

-- MLB role holders (store the username directly)
ALTER TABLE organizations ADD COLUMN owner_name  VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE organizations ADD COLUMN gm_name     VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE organizations ADD COLUMN manager_name VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE organizations ADD COLUMN scout_name  VARCHAR(255) NOT NULL DEFAULT '';

-- College coach (username or "AI")
ALTER TABLE organizations ADD COLUMN coach VARCHAR(255) NOT NULL DEFAULT 'AI';


-- -------------------------------------------------------
-- 2. mlb_requests table
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS mlb_requests (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(255) NOT NULL,
    org_id      INT NOT NULL,
    role        VARCHAR(10)  NOT NULL COMMENT '"o", "gm", "mgr", or "sc"',
    is_owner    TINYINT(1)   NOT NULL DEFAULT 0,
    is_gm       TINYINT(1)   NOT NULL DEFAULT 0,
    is_manager  TINYINT(1)   NOT NULL DEFAULT 0,
    is_scout    TINYINT(1)   NOT NULL DEFAULT 0,
    is_approved TINYINT(1)   NOT NULL DEFAULT 0,
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_mlb_requests_org
        FOREIGN KEY (org_id) REFERENCES organizations (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- -------------------------------------------------------
-- 3. college_baseball_requests table
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS college_baseball_requests (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(255) NOT NULL,
    org_id      INT NOT NULL,
    is_approved TINYINT(1)   NOT NULL DEFAULT 0,
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_college_requests_org
        FOREIGN KEY (org_id) REFERENCES organizations (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- -------------------------------------------------------
-- NOTE: You will also need to update the organization_report
-- VIEW to include the new columns:
--   league, owner_name, gm_name, manager_name, scout_name, coach
-- -------------------------------------------------------
