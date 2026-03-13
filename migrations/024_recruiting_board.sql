-- 024: Recruiting board — explicit watchlist separate from investments
--
-- Allows orgs to add/remove players to their recruiting board
-- independently of whether they have invested points.
-- This is a simple presence table: if a row exists, the player
-- is on the board.

CREATE TABLE IF NOT EXISTS recruiting_board (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    org_id        INT NOT NULL,
    league_year_id INT NOT NULL,
    player_id     INT NOT NULL,
    added_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_board_entry (org_id, league_year_id, player_id),
    INDEX idx_board_org_year (org_id, league_year_id)
);
