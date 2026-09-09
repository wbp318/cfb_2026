# Shared data loader for analysis/ R scripts.
#
#   source("analysis/_shared/load_data.R")
#   games <- load_games()        # one row per completed game w/ closing line + pre-game FPI
#   bets  <- load_paper_bets()   # one row per settled paper bet
#
# Mirrors analysis/_shared/load_data.py — keep them in lockstep.

suppressPackageStartupMessages({
  library(DBI)
  library(RSQLite)
  library(dplyr)
})

.shared_dir <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) "analysis/_shared")
DEFAULT_DB <- normalizePath(file.path(.shared_dir, "..", "..", "data.db"), mustWork = FALSE)
BREAK_EVEN_110 <- 110 / 210      # 52.38% — cover rate needed at -110

# See load_data.py for why "last snapshot" == closing line and why the only
# settled filter is completed=1 + both scores present (no dropped losers).
.GAMES_SQL <- "
WITH last AS (
    SELECT s.*, ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY taken_at DESC) AS rn
    FROM snapshots s
    WHERE home_spread IS NOT NULL AND home_fpi_margin IS NOT NULL
)
SELECT g.id AS game_id, g.date, g.name, g.neutral, g.home, g.away,
       g.home_score, g.away_score,
       last.home_spread, last.home_spread_open, last.total, last.total_open,
       last.home_ml, last.away_ml, last.home_fpi_p, last.home_fpi_margin,
       last.home_fpi, last.away_fpi
FROM games g
JOIN last ON last.game_id = g.id AND last.rn = 1
WHERE g.completed = 1 AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
"

.BETS_SQL <- "
SELECT p.id, p.game_id, g.date, p.kind, p.side, p.line, p.price, p.truth_p, p.edge,
       p.strength, p.stake, p.result, p.profit, p.backfill
FROM paper_bets p JOIN games g ON g.id = p.game_id
WHERE p.result IS NOT NULL
"

.query <- function(sql, db_path) {
  con <- dbConnect(SQLite(), db_path)
  on.exit(dbDisconnect(con))
  dbGetQuery(con, sql)
}

load_games <- function(db_path = DEFAULT_DB, fbs_only = TRUE) {
  df <- .query(.GAMES_SQL, db_path)
  if (fbs_only) df <- df[!is.na(df$home_fpi) & !is.na(df$away_fpi), ]
  df$home_margin      <- df$home_score - df$away_score
  df$market_margin    <- -df$home_spread
  df$fpi_delta        <- df$home_fpi_margin - df$market_margin
  df$ats_margin       <- df$home_margin - df$market_margin
  signed              <- sign(df$ats_margin) * sign(df$fpi_delta)
  df$fpi_side_covered <- ifelse(df$ats_margin == 0 | df$fpi_delta == 0, NA, as.numeric(signed > 0))
  df$home_won         <- as.integer(df$home_margin > 0)
  df$spread_move      <- df$home_spread_open - df$home_spread
  df$abs_delta        <- abs(df$fpi_delta)
  rownames(df) <- NULL
  df
}

.dec <- function(price) ifelse(price > 0, 1 + price / 100, 1 + 100 / abs(price))

load_paper_bets <- function(db_path = DEFAULT_DB) {
  df <- .query(.BETS_SQL, db_path)
  df$pnl_flat <- ifelse(df$result == "W", .dec(df$price) - 1,
                 ifelse(df$result == "L", -1, 0))
  df
}

# Wilson score interval — same closed form as binom::binom.wilson; returned as
# c(point, lo, hi) so the two runtimes print identical numbers.
wilson <- function(k, n, z = 1.959964) {
  if (n == 0) return(c(NA, NA, NA))
  p <- k / n
  denom <- 1 + z^2 / n
  centre <- (p + z^2 / (2 * n)) / denom
  half <- z * sqrt(p * (1 - p) / n + z^2 / (4 * n^2)) / denom
  c(p, centre - half, centre + half)
}
