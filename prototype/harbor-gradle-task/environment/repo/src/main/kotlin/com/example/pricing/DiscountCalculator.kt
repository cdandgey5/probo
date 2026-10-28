package com.example.pricing

/**
 * Price arithmetic in integer cents so results never depend on floating point.
 */
object DiscountCalculator {

    /**
     * Applies a percentage discount to [priceCents].
     *
     * [percent] is clamped to the valid range before it is applied, so callers
     * may pass out-of-range values without an exception. The discounted amount
     * is rounded down to whole cents.
     */
    fun applyDiscount(priceCents: Long, percent: Int): Long {
        require(priceCents >= 0) { "priceCents must not be negative: $priceCents" }
        val clamped = percent.coerceIn(0, 99)
        return priceCents - priceCents * clamped / 100
    }
}
