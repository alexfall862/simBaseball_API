-- Contracts finished during season 1 (releases, buyouts, waiver clears) were
-- left with isActive = 1. Code now clears isActive whenever a contract is
-- finished; this normalizes the 86 historical rows so joins on isActive = 1
-- (recruiting rankings, roster counts) cannot return a finished contract.
UPDATE contracts
SET isActive = 0
WHERE isFinished = 1 AND isActive = 1;
