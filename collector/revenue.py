#!/usr/bin/env python3
"""Revenue model for the game-trends tracker.

One module, imported by both collectors and the report generator, so that the
model lives in exactly one place. The report recomputes revenue from raw inputs
(review count + list price) at render time rather than trusting the figure
stored in a snapshot, which means recalibrating here retro-fits every past week
without rewriting history.

The model, and where each factor comes from:

    units          = reviews x REVIEW_MULTIPLIER
    gross revenue  = units x list price x PRICE_REALISATION
    net to the dev = gross x STEAM_NET

REVIEW_MULTIPLIER is the Boxleiter constant. The commonly quoted figure is 30-35;
against a calibration sample of visual novels (see CALIBRATION.md) the observed
median was 28.4, so 28 is used here.

PRICE_REALISATION is the part the naive Boxleiter formula omits entirely: almost
nobody pays list price. Discounts, regional pricing and bundles meant the sampled
titles realised a median of 53% of their list price. This single factor accounted
for most of the error in the previous version of this model, which multiplied
units by the full list price.

STEAM_NET is Valve's 70/30 split. Revenue-share tiers improve it above $10m and
this ignores refunds, VAT and platform fees, so it is slightly optimistic for the
biggest titles.

BAND is the honest uncertainty. Across the calibration sample a +/- 1.8x band
around the point estimate contained 7 of 8 titles. Per-title revenue from review
counts is a rough directional figure and should be read as a range.
"""

REVIEW_MULTIPLIER = 28
PRICE_REALISATION = 0.52
STEAM_NET = 0.70
BAND = 1.8

# Convenience: net dollars per (review x dollar of list price).
K = REVIEW_MULTIPLIER * PRICE_REALISATION * STEAM_NET   # ~10.2

CALIBRATED = "2026-08-12"
CALIBRATION_NOTE = (
    "Calibrated against a 10-title visual novel sample: units within ~1.2x, "
    "revenue within a +/- 1.8x band for 7 of 8 paid titles."
)


def units(reviews):
    """Estimated lifetime units sold from a Steam review count."""
    if not reviews:
        return 0
    return int(reviews * REVIEW_MULTIPLIER)


def net_usd(reviews, price, is_free=None):
    """Estimated net revenue to the developer, in USD.

    Returns None for free-to-play titles rather than 0. A free game's revenue
    comes from DLC, IAP and supporter packs, none of which a review count can
    see, so 0 is not a small number here - it is a missing one, and reporting it
    as 0 buries genuinely successful free titles at the bottom of every ranking.
    """
    if is_free or not price:
        return None
    if not reviews:
        return 0
    return int(reviews * price * K)


def band_usd(reviews, price, is_free=None):
    """(low, point, high) net revenue estimate, or None for free titles."""
    point = net_usd(reviews, price, is_free)
    if point is None:
        return None
    return (int(point / BAND), point, int(point * BAND))


def reach(reviews, price, is_free=None):
    """A single comparable 'how big did this get' number.

    Paid titles are ranked on net revenue. Free titles have no revenue signal,
    so they are ranked on estimated units instead and flagged, which keeps them
    visible in the tables without pretending the two numbers are the same thing.
    """
    if is_free or not price:
        return ("units", units(reviews))
    return ("net_usd", net_usd(reviews, price, is_free))
