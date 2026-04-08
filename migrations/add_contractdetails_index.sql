-- Composite index on contractDetails for the (contractID, year) join pattern.
-- The existing single-column index on contractID forces a sequential scan to
-- match year, which is the main bottleneck in compute_star_rankings() and
-- other contract-chain queries (~424k rows).

CREATE INDEX idx_contractDetails_contract_year
    ON contractDetails (contractID, year);
