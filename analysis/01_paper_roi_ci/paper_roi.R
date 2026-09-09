# Flat-bet ROI of the paper ledger by signal kind x strength, with bootstrap 95% CIs.
#
# Strategy under test: every play cfb_edge.py flagged (strength >= 1) is bet flat $1
# at the logged price. PnL = decimal-1 if W, -1 if L, 0 push.
#
# Output: analysis/_out/paper_roi.csv + console table sorted by lower CI.
# Mirrors paper_roi.py — keep them in lockstep. Point estimates must match
# exactly; bootstrap CIs may differ in the last digit (different RNG streams).

suppressPackageStartupMessages({
  library(dplyr)
  library(boot)
})

.this_dir <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) "analysis/01_paper_roi_ci")
source(file.path(.this_dir, "..", "_shared", "load_data.R"))

MIN_BETS  <- 10
BOOT_REPS <- 5000
SEED      <- 20260909
OUT_DIR   <- normalizePath(file.path(.this_dir, "..", "_out"), mustWork = FALSE)
OUT_CSV   <- file.path(OUT_DIR, "paper_roi.csv")

dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)
set.seed(SEED)

bets <- load_paper_bets()
if (nrow(bets) == 0) {
  cat("no settled paper bets yet — run cfb_edge.py --snapshot / --settle (or --backfill)\n")
  quit(status = 0)
}
cat(sprintf("Settled paper bets: %s   |   backfilled: %s   |   Overall flat ROI: %+.1f%%   |   Bootstrap reps: %s\n\n",
            format(nrow(bets), big.mark = ","), format(sum(bets$backfill), big.mark = ","),
            100 * mean(bets$pnl_flat), format(BOOT_REPS, big.mark = ",")))

verdict <- function(lo, hi) {
  if (lo > 0) "PROFITABLE (95% CI > 0)" else if (hi < 0) "losing (95% CI < 0)" else "inconclusive"
}
mean_stat <- function(d, i) mean(d[i])
boot_ci <- function(x) {
  b <- boot(x, mean_stat, R = BOOT_REPS)
  ci <- boot.ci(b, type = "perc")$percent
  c(lo = ci[4], hi = ci[5])
}

groups <- list(list(kind = "ALL", strength = "all", g = bets))
for (key in split(bets, list(bets$kind, bets$strength), drop = TRUE))
  groups[[length(groups) + 1]] <- list(kind = key$kind[1], strength = as.character(key$strength[1]), g = key)
for (key in split(bets, bets$kind))
  groups[[length(groups) + 1]] <- list(kind = key$kind[1], strength = "any", g = key)

rows <- lapply(groups, function(x) {
  g <- x$g
  if (nrow(g) < MIN_BETS) return(NULL)
  ci <- boot_ci(g$pnl_flat)
  data.frame(kind = x$kind, strength = x$strength, bets = nrow(g),
             wins = sum(g$result == "W"), hit_rate = mean(g$result == "W"),
             roi_mean = mean(g$pnl_flat), roi_ci_lo = ci[["lo"]], roi_ci_hi = ci[["hi"]],
             verdict = verdict(ci[["lo"]], ci[["hi"]]), stringsAsFactors = FALSE)
})
out <- bind_rows(rows) %>% arrange(desc(roi_ci_lo))
write.csv(out, OUT_CSV, row.names = FALSE)

cat(sprintf("%-8s%5s%6s%6s%7s%8s%8s%8s  verdict\n", "kind", "str", "bets", "wins", "hit%", "ROI", "CI lo", "CI hi"))
for (i in seq_len(nrow(out))) {
  r <- out[i, ]
  cat(sprintf("%-8s%5s%6d%6d%6.1f%%%+7.1f%%%+7.1f%%%+7.1f%%  %s\n",
              r$kind, r$strength, r$bets, r$wins, 100 * r$hit_rate,
              100 * r$roi_mean, 100 * r$roi_ci_lo, 100 * r$roi_ci_hi, r$verdict))
}
cat(sprintf("\nwrote %s\n", OUT_CSV))
