-- Migration 012: Service time tracking + contract renewal support
-- Creates player_service_time table, adds 'renewal' to transaction_log ENUM,
-- and seeds initial service time for existing players based on salary + age.

-- 1. Create the service time table
CREATE TABLE IF NOT EXISTS player_service_time (
    player_id          INT NOT NULL PRIMARY KEY,
    mlb_service_years  INT NOT NULL DEFAULT 0,
    last_accrual_year  INT NULL COMMENT 'league_year when last credited to prevent double-counting',
    CONSTRAINT fk_pst_player FOREIGN KEY (player_id) REFERENCES simbbPlayers(id) ON DELETE CASCADE
);

-- 2. Add 'renewal' to the transaction_log ENUM
ALTER TABLE transaction_log
  MODIFY COLUMN transaction_type
    ENUM('trade','release','signing','extension','buyout',
         'promote','demote','ir_place','ir_activate','renewal') NOT NULL;

-- 3. Seed service time for existing players from salary + age
--    Salary determines the tier; age refines within the tier.
--    $40K (minor league)  → 0 service years regardless of age
--    ≤$800K at MLB level  → pre-arb: age 20-22=0, 23-24=1, 25-26=2
--    >$800K at MLB level  → veteran: age ≤27=3, 28=4, 29=5, 30+=6

INSERT INTO player_service_time (player_id, mlb_service_years, last_accrual_year)
SELECT
    c.playerID,
    CASE
        -- Minor league (level < 9): no MLB service time
        WHEN c.current_level < 9 THEN 0
        -- MLB level, salary <= $800K → pre-arb tier, use age
        WHEN d.salary <= 800000 THEN
            CASE
                WHEN p.age <= 22 THEN 0
                WHEN p.age <= 24 THEN 1
                ELSE 2
            END
        -- MLB level, salary > $800K → veteran tier, use age
        ELSE
            CASE
                WHEN p.age <= 27 THEN 3
                WHEN p.age = 28  THEN 4
                WHEN p.age = 29  THEN 5
                ELSE 6
            END
    END,
    NULL
FROM contracts c
JOIN contractDetails d ON d.contractID = c.id AND d.year = c.current_year
JOIN simbbPlayers p ON p.id = c.playerID
WHERE c.isFinished = 0
ON DUPLICATE KEY UPDATE player_id = player_id;
