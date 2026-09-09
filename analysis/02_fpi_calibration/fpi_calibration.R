# Is ESPN FPI worth anything against the DraftKings closer?
#
#   A. Calibration — binned FPI home win prob vs observed home win rate (Wilson CI).
#   B. Accuracy — RMSE of actual margin vs FPI margin, vs the closer, vs a 50/50 blend.
#   C. ATS — when FPI and the closer disagree by |delta| pts, how often does the
#      FPI side cover? Compare to the 52.4% break-even at -110.
#
# Output: analysis/_out/fpi_calibration.csv, fpi_ats_by_delta.csv.
# Mirrors fpi_calibration.py — keep them in lockstep.

suppressPackageStartupMessages(library(dplyr))

.this_dir <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) "analysis/02_fpi_calibration")
source(file.path(.this_dir, "..", "_shared", "load_data.R"))

OUT_DIR      <- normalizePath(file.path(.this_dir, "..", "_out"), mustWork = FALSE)
PROB_BINS    <- c(0, 0.2, 0.4, 0.6, 0.8, 1.0001)
DELTA_BINS   <- c(0, 3, 5, 8, 99)
DELTA_LABELS <- c("0-3", "3-5", "5-8", "8+")
dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

rmse <- function(a, b) sqrt(mean((a - b)^2))

g <- load_games()
if (nrow(g) == 0) {
  cat("no settled games yet — run cfb_edge.py --backfill --date <past saturday>\n")
  quit(status = 0)
}
cat(sprintf("Settled FBS-vs-FBS games with closer + FPI: %s\n\n", format(nrow(g), big.mark = ",")))

# A. calibration — same left-closed bins as pandas cut(right=False)
cat("A. FPI home win-prob calibration (Wilson 95% CI)\n")
g$pbin <- cut(g$home_fpi_p, PROB_BINS, right = FALSE)
cal <- g %>% group_by(pbin) %>% group_map(function(grp, key) {
  w <- wilson(sum(grp$home_won), nrow(grp))
  lab <- sub("\\)$", ")", sub("^\\[", "[", as.character(key$pbin)))
  cat(sprintf("  %-12s n=%4d  pred %5.1f%%  obs %5.1f%% [%5.1f,%5.1f]  Δ%+5.1fpp\n",
              lab, nrow(grp), 100 * mean(grp$home_fpi_p), 100 * w[1], 100 * w[2], 100 * w[3],
              100 * (w[1] - mean(grp$home_fpi_p))))
  data.frame(bin = lab, n = nrow(grp), pred_mean = mean(grp$home_fpi_p),
             obs_rate = w[1], obs_lo = w[2], obs_hi = w[3])
}) %>% bind_rows()
write.csv(cal, file.path(OUT_DIR, "fpi_calibration.csv"), row.names = FALSE)

# B. accuracy
blend   <- 0.5 * g$home_fpi_margin + 0.5 * g$market_margin
r_fpi   <- rmse(g$home_margin, g$home_fpi_margin)
r_mkt   <- rmse(g$home_margin, g$market_margin)
r_blend <- rmse(g$home_margin, blend)
cat("\nB. Margin accuracy (RMSE, lower is better)\n")
cat(sprintf("  FPI margin   %6.2f\n  DK closer    %6.2f\n  50/50 blend  %6.2f\n", r_fpi, r_mkt, r_blend))
cat(sprintf("  verdict: %s by %.2f pts RMSE (MARGIN_SD in cfb_edge.py assumes ~13.5)\n",
            if (r_fpi < r_mkt) "FPI beats the closer" else "the closer beats FPI", abs(r_fpi - r_mkt)))

# C. ATS by |delta|
cat(sprintf("\nC. FPI-side cover rate by |FPI − closer| (break-even at -110 = %.1f%%)\n", 100 * BREAK_EVEN_110))
d <- g[!is.na(g$fpi_side_covered), ]
d$dbin <- cut(d$abs_delta, DELTA_BINS, labels = DELTA_LABELS, right = FALSE)
ats <- d %>% group_by(dbin) %>% group_map(function(grp, key) {
  w <- wilson(sum(grp$fpi_side_covered), nrow(grp))
  v <- if (w[2] > BREAK_EVEN_110) "PROFITABLE (CI lo > BE)" else if (w[3] < BREAK_EVEN_110) "losing (CI hi < BE)" else "inconclusive"
  cat(sprintf("  Δ%-5s n=%4d  cover %5.1f%% [%5.1f,%5.1f]  %s\n",
              as.character(key$dbin), nrow(grp), 100 * w[1], 100 * w[2], 100 * w[3], v))
  data.frame(delta_bin = as.character(key$dbin), n = nrow(grp), covers = sum(grp$fpi_side_covered),
             cover_rate = w[1], ci_lo = w[2], ci_hi = w[3], verdict = v)
}) %>% bind_rows()
w <- wilson(sum(d$fpi_side_covered), nrow(d))
cat(sprintf("  ALL    n=%4d  cover %5.1f%% [%5.1f,%5.1f]\n", nrow(d), 100 * w[1], 100 * w[2], 100 * w[3]))
write.csv(ats, file.path(OUT_DIR, "fpi_ats_by_delta.csv"), row.names = FALSE)
cat(sprintf("\nwrote %s, %s\n", file.path(OUT_DIR, "fpi_calibration.csv"), file.path(OUT_DIR, "fpi_ats_by_delta.csv")))
