# Does open->close line movement predict the cover?
#
#   A. Steam — when the spread moved >= STEAM_PTS, does the side the market moved
#      TOWARD cover more than 52.4%? ("follow the money")
#   B. Interaction — FPI side cover rate when the move agrees ("with") vs
#      disagrees ("against") with FPI. Evidence behind ⚠market-moved-against.
#
# Output: analysis/_out/line_move.csv.  Mirrors line_move.py — keep in lockstep.

suppressPackageStartupMessages(library(dplyr))

.this_dir <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) "analysis/03_line_move")
source(file.path(.this_dir, "..", "_shared", "load_data.R"))

OUT_DIR   <- normalizePath(file.path(.this_dir, "..", "_out"), mustWork = FALSE)
STEAM_PTS <- 1.5
dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

line <- function(label, k, n) {
  w <- wilson(k, n)
  v <- if (!is.na(w[2]) && w[2] > BREAK_EVEN_110) "PROFITABLE (CI lo > BE)" else if (!is.na(w[3]) && w[3] < BREAK_EVEN_110) "losing (CI hi < BE)" else "inconclusive"
  cat(sprintf("  %-34s n=%4d  cover %5.1f%% [%5.1f,%5.1f]  %s\n", label, n, 100 * w[1], 100 * w[2], 100 * w[3], v))
  data.frame(group = label, n = n, covers = k, cover_rate = w[1], ci_lo = w[2], ci_hi = w[3], verdict = v)
}

g <- load_games()
g <- g[!is.na(g$spread_move) & g$ats_margin != 0, ]
if (nrow(g) == 0) { cat("no settled games with an opener yet\n"); quit(status = 0) }
moved <- g[abs(g$spread_move) >= STEAM_PTS, ]
cat(sprintf("Settled games with opener: %s   |   moved ≥%.1f pts: %s   |   break-even %.1f%%\n\n",
            format(nrow(g), big.mark = ","), STEAM_PTS, format(nrow(moved), big.mark = ","), 100 * BREAK_EVEN_110))

rows <- list()
cat("A. Follow-the-money: did the side the line moved toward cover?\n")
moved$toward_covered <- as.integer(sign(moved$ats_margin) == sign(moved$spread_move))
rows[[1]] <- line("moved-toward side", sum(moved$toward_covered), nrow(moved))
big <- moved[abs(moved$spread_move) >= 3, ]
rows[[2]] <- line("moved-toward side (≥3 pts)", sum(big$toward_covered), nrow(big))

cat("\nB. FPI side vs steam direction\n")
d <- moved[!is.na(moved$fpi_side_covered) & moved$fpi_delta != 0, ]
d$with <- sign(d$spread_move) == sign(d$fpi_delta)
sub <- d[d$with, ];  rows[[3]] <- line("FPI side, steam WITH", sum(sub$fpi_side_covered), nrow(sub))
sub <- d[!d$with, ]; rows[[4]] <- line("FPI side, steam AGAINST", sum(sub$fpi_side_covered), nrow(sub))
still <- g[abs(g$spread_move) < STEAM_PTS & !is.na(g$fpi_side_covered), ]
rows[[5]] <- line("FPI side, no steam", sum(still$fpi_side_covered), nrow(still))
write.csv(bind_rows(rows), file.path(OUT_DIR, "line_move.csv"), row.names = FALSE)
cat(sprintf("\nwrote %s\n", file.path(OUT_DIR, "line_move.csv")))
