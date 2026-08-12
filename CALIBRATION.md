# Revenue model calibration

**Calibrated 2026-08-12** against Gamalytic's free-tier public figures.
Model lives in `collector/revenue.py`.

## Why

Every revenue figure in this repo was originally the naive Boxleiter formula:

    net = reviews x 35 x list_price x 0.55

That formula has two problems. It multiplies by **list price**, which almost
nobody pays, and it reports **$0** for free-to-play titles, which buries some of
the most successful games in the dataset at the bottom of every ranking.

## Method

Ten visual novels were sampled across price points ($0 to $19.99), cluster types
and scale (7.8k to 128k reviews), and this pipeline's estimates were compared
against Gamalytic's modelled units and gross revenue. Gamalytic's own figures are
modelled, not ground truth, and their published accuracy is self-reported
(77% within 30%), so this is a calibration against a better estimate, not
against reality.

| Title | List | Our units | Gamalytic units | Our gross | Gamalytic gross | Realised price |
|---|---|---|---|---|---|---|
| Coffin of Andy & Leyley | $11.99 | 1,055k | 568k | $12.7M | $4.6M | 68% |
| Slay the Princess PC | $17.99 | 839k | 830k | $15.1M | $10.5M | 70% |
| Milk inside a bag | $1.49 | 1,048k | 809k | $1.6M | $482k | 40% |
| Until Then | $19.99 | 345k | 257k | $6.9M | $2.9M | 57% |
| Volcano Princess | $10.99 | 1,441k | 1,800k | $15.8M | $11.9M | 60% |
| Tales of the Black Forest | $3.99 | 488k | 417k | $1.9M | $429k | 26% |
| Detention | $11.99 | 503k | 496k | $6.0M | $2.9M | 49% |
| Marco & Galaxy Dragon | $19.99 | 247k | 178k | $4.9M | $1.3M | 37% |
| Doki Doki Literature Club | free | 7,375k | 8,600k | $0 | $3.4M | - |
| Helltaker | free | 4,372k | 5,500k | $0 | $717k | - |

## Findings

**Units were roughly right.** Implied review-to-units multiplier: median 28.4,
range 18.8 to 43.7. Our 35 was about 1.2x high. No usable relationship with
price band at this sample size.

**Revenue was 2.6x too high, and units were not the reason.** Units were only
1.2x high while gross was 2.6x high, so the error was almost entirely on the
price side: sampled titles realised a **median 53% of list price** after
discounts, regional pricing and bundles. Cheap titles fared worst (Tales of the
Black Forest at 26%), which is consistent with deep discounting and China-weighted
regional pricing.

**Playtime was already good.** Our median-of-review-samples method landed within
1.06x of Gamalytic's average playtime (median difference +0.4h). No change made.
The two outliers were Until Then (20.7h vs 12.5h) and Milk inside a bag
(0.4h vs 0.8h).

**Free-to-play titles do earn.** Doki Doki Literature Club shows $3.4M gross and
Helltaker $717k, from DLC and supporter packs. A review count cannot see any of
that, so the model now returns `None` rather than `0` and the report prints
"free" instead of a fake zero.

**Review counts differ.** Ours ran a median 0.86x of Gamalytic's, mostly because
market-tier titles are read from SteamSpy, which lags. Not corrected.

## The model now

    units = reviews x 28              # observed median 28.4
    gross = units x list_price x 0.52 # observed median realised price 53%
    net   = gross x 0.70              # Valve's cut

Net dollars per (review x dollar of list price) drops from **19.25 to ~10.2**.

Median error against the sample improves from 2.02x to 1.21x, and 7 of 8 paid
titles fall inside a +/- 1.8x band, which is why the report shows a range on
hover rather than a bare point estimate. Per-title revenue from review counts is
directional. Comparisons between clusters are far more reliable than any single
number, because the multiplier error largely cancels.

## Caveats

- n = 10, all visual novels, all comparatively successful. The multiplier is
  known to vary with genre and with scale; small titles are not represented.
- Calibrated against another model's output, not against reported sales.
- Ignores refunds, VAT, and Valve's revenue-share tiers above $10M.
- Worth re-running when the sample can be widened, or if a Gamalytic API
  subscription makes per-title figures directly available.
